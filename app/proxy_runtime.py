from __future__ import annotations

import json
from pathlib import Path
import subprocess
import time
from typing import Callable

from proxy_state import ProxyState, load_proxy_state, save_proxy_state
import vpn


class ProxyRuntimeManager:
    def __init__(
        self,
        *,
        state_path: str | Path,
        xray_config_path: str | Path,
        subscription_loader: Callable[[], str],
        start_xray: Callable[[str], None],
        restart_xray: Callable[[str], None],
        time_fn: Callable[[], float] | None = None,
        cooldown_seconds: float = 600.0,
    ):
        self.state_path = Path(state_path)
        self.xray_config_path = Path(xray_config_path)
        self.subscription_loader = subscription_loader
        self.start_xray = start_xray
        self.restart_xray = restart_xray
        self.time_fn = time_fn or time.time
        self.cooldown_seconds = cooldown_seconds
        self.state = load_proxy_state(self.state_path)
        self.nodes: list[dict] = []
        self.active_node: dict | None = None
        self.active_node_fingerprint: str | None = self.state.active_node_fingerprint
        self.current_generation = self.state.generation
        self._xray_started = False

    async def initialize(self) -> None:
        self.nodes = vpn.parse_subscription_nodes(self.subscription_loader())
        node = self._resolve_initial_node()
        if node is None:
            raise RuntimeError("No valid proxy nodes available")

        if self.current_generation < 1:
            self.current_generation = 1
        self._activate_node(node, restart=False)

    async def switch_to_next_node(self, *, reason: str) -> bool:
        self.nodes = vpn.parse_subscription_nodes(self.subscription_loader())
        next_node = self._select_next_node()
        if next_node is None:
            return False

        self.current_generation += 1
        self._activate_node(next_node, restart=True)
        return True

    def mark_current_node_failed(self, *, reason: str, now: float) -> None:
        if self.active_node_fingerprint is None:
            return
        self.state.failed_fingerprints[self.active_node_fingerprint] = {
            "failed_at": now,
            "cooldown_until": now + self.cooldown_seconds,
            "reason": reason,
        }
        save_proxy_state(self.state_path, self.state)

    def _resolve_initial_node(self) -> dict | None:
        preferred_fingerprint = self.state.active_node_fingerprint
        if preferred_fingerprint:
            for index, node in enumerate(self.nodes):
                fingerprint = vpn.node_fingerprint(node)
                if fingerprint == preferred_fingerprint and not self._is_in_cooldown(fingerprint):
                    self.state.active_node_index_hint = index
                    return node
        return self._select_first_viable_node()

    def _select_first_viable_node(self) -> dict | None:
        for index, node in enumerate(self.nodes):
            fingerprint = vpn.node_fingerprint(node)
            if self._is_in_cooldown(fingerprint):
                continue
            self.state.active_node_index_hint = index
            return node
        return None

    def _select_next_node(self) -> dict | None:
        if not self.nodes:
            return None

        current_index = self._current_node_index()
        total = len(self.nodes)
        for offset in range(1, total + 1):
            index = (current_index + offset) % total
            candidate = self.nodes[index]
            fingerprint = vpn.node_fingerprint(candidate)
            if self._is_in_cooldown(fingerprint):
                continue
            self.state.active_node_index_hint = index
            return candidate
        return None

    def _current_node_index(self) -> int:
        if self.active_node_fingerprint is None:
            return self.state.active_node_index_hint or 0

        for index, node in enumerate(self.nodes):
            if vpn.node_fingerprint(node) == self.active_node_fingerprint:
                return index
        return self.state.active_node_index_hint or 0

    def _is_in_cooldown(self, fingerprint: str) -> bool:
        entry = self.state.failed_fingerprints.get(fingerprint)
        if not isinstance(entry, dict):
            return False
        cooldown_until = entry.get("cooldown_until")
        if cooldown_until is None:
            return False
        return float(cooldown_until) > self.time_fn()

    def _activate_node(self, node: dict, *, restart: bool) -> None:
        config = vpn.render_xray_config(node)
        raw_config = json.dumps(config, indent=2, sort_keys=True)
        self.xray_config_path.parent.mkdir(parents=True, exist_ok=True)
        self.xray_config_path.write_text(raw_config, encoding="utf-8")

        fingerprint = vpn.node_fingerprint(node)
        self.active_node = node
        self.active_node_fingerprint = fingerprint
        self.state.active_node_fingerprint = fingerprint
        self.state.active_node_name = self._node_name(node)
        self.state.generation = self.current_generation
        self.state.last_switch_at = self.time_fn()
        self.state.last_subscription_refresh_at = self.time_fn()
        save_proxy_state(self.state_path, self.state)

        if restart or self._xray_started:
            self.restart_xray(raw_config)
        else:
            self.start_xray(raw_config)
            self._xray_started = True

    @staticmethod
    def _node_name(node: dict) -> str:
        return node["settings"]["vnext"][0]["address"]


def build_proxy_runtime(
    *,
    state_dir: str | Path,
    environ: dict[str, str],
    subscription_loader: Callable[[], str] | None = None,
    start_xray: Callable[[str], None] | None = None,
    restart_xray: Callable[[str], None] | None = None,
    time_fn: Callable[[], float] | None = None,
    xray_config_path: str | Path = "/etc/xray/config.json",
):
    subscription_url = environ.get("VPN_SUBSCRIPTION_URL")
    if not subscription_url:
        return None

    if subscription_loader is None:
        subscription_loader = lambda: vpn.fetch_subscription(subscription_url)

    if start_xray is None or restart_xray is None:
        controller = _build_default_xray_controller(Path(xray_config_path))
        start_xray = start_xray or controller["start"]
        restart_xray = restart_xray or controller["restart"]

    return ProxyRuntimeManager(
        state_path=Path(state_dir) / "proxy_state.json",
        xray_config_path=xray_config_path,
        subscription_loader=subscription_loader,
        start_xray=start_xray,
        restart_xray=restart_xray,
        time_fn=time_fn,
    )


def _build_default_xray_controller(xray_config_path: Path) -> dict[str, Callable[[str], None]]:
    process_holder: dict[str, object] = {"process": None, "log_file": None}

    def _spawn() -> None:
        if process_holder["log_file"] is None:
            process_holder["log_file"] = open("/tmp/xray.log", "ab")
        process_holder["process"] = subprocess.Popen(
            ["xray", "-config", str(xray_config_path)],
            stdout=process_holder["log_file"],
            stderr=process_holder["log_file"],
        )

    def start_xray(_: str) -> None:
        _spawn()

    def restart_xray(_: str) -> None:
        process = process_holder["process"]
        if isinstance(process, subprocess.Popen) and process.poll() is None:
            process.terminate()
            process.wait(timeout=10)
        _spawn()

    return {"start": start_xray, "restart": restart_xray}
