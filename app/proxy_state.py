from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path


@dataclass(slots=True)
class ProxyState:
    active_node_fingerprint: str | None = None
    active_node_index_hint: int | None = None
    generation: int = 0
    subscription_url_hash: str | None = None
    active_node_name: str | None = None
    last_switch_at: float | None = None
    last_subscription_refresh_at: float | None = None
    failed_fingerprints: dict[str, dict[str, object]] = field(default_factory=dict)


def load_proxy_state(path: str | Path) -> ProxyState:
    state_path = Path(path)
    if not state_path.exists():
        return ProxyState()

    try:
        payload = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        return ProxyState()

    if not isinstance(payload, dict):
        return ProxyState()

    failed_fingerprints = payload.get("failed_fingerprints") or {}
    if not isinstance(failed_fingerprints, dict):
        failed_fingerprints = {}

    return ProxyState(
        active_node_fingerprint=payload.get("active_node_fingerprint"),
        active_node_index_hint=payload.get("active_node_index_hint"),
        generation=int(payload.get("generation", 0)),
        subscription_url_hash=payload.get("subscription_url_hash"),
        active_node_name=payload.get("active_node_name"),
        last_switch_at=payload.get("last_switch_at"),
        last_subscription_refresh_at=payload.get("last_subscription_refresh_at"),
        failed_fingerprints=failed_fingerprints,
    )


def save_proxy_state(path: str | Path, state: ProxyState) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_suffix(state_path.suffix + ".tmp")

    payload = {
        "active_node_fingerprint": state.active_node_fingerprint,
        "active_node_index_hint": state.active_node_index_hint,
        "generation": state.generation,
        "subscription_url_hash": state.subscription_url_hash,
        "active_node_name": state.active_node_name,
        "last_switch_at": state.last_switch_at,
        "last_subscription_refresh_at": state.last_subscription_refresh_at,
        "failed_fingerprints": state.failed_fingerprints,
    }

    temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    temp_path.replace(state_path)
