import asyncio
import base64
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.proxy_runtime import ProxyRuntimeManager, build_proxy_runtime
from app.proxy_state import ProxyState, save_proxy_state
from app import vpn


def _make_vmess_link(*, host: str, port: int, node_id: str, name: str) -> str:
    payload = {
        "v": "2",
        "ps": name,
        "add": host,
        "port": str(port),
        "id": node_id,
        "aid": "0",
        "scy": "auto",
        "net": "ws",
        "type": "none",
        "host": host,
        "path": "/websocket",
        "tls": "tls",
        "sni": host,
    }
    encoded = base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii")
    return f"vmess://{encoded}"


class ProxyRuntimeManagerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.vless_link = (
            "vless://11111111-1111-1111-1111-111111111111@hk.example.com:443"
            "?security=tls&type=ws&sni=hk.example.com&host=cdn.hk.example.com&path=%2Fws#hk-01"
        )
        self.vmess_link = _make_vmess_link(
            host="us.example.com",
            port=8443,
            node_id="22222222-2222-2222-2222-222222222222",
            name="us-01",
        )
        self.jp_link = (
            "vless://33333333-3333-3333-3333-333333333333@jp.example.com:443"
            "?security=tls&type=ws&sni=jp.example.com&host=cdn.jp.example.com&path=%2Fws#jp-01"
        )

    async def test_initialize_restores_previous_active_node_by_fingerprint_when_order_changes(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime_calls: list[str] = []
            state_path = Path(tmp) / "proxy_state.json"
            config_path = Path(tmp) / "xray-config.json"
            persisted_node = vpn.parse_subscription_nodes(self.vless_link)[0]
            save_proxy_state(
                state_path,
                ProxyState(
                    active_node_fingerprint=vpn.node_fingerprint(persisted_node),
                    active_node_index_hint=0,
                    generation=7,
                ),
            )

            manager = ProxyRuntimeManager(
                state_path=state_path,
                xray_config_path=config_path,
                subscription_loader=lambda: "\n".join([self.vmess_link, self.vless_link]),
                start_xray=lambda config: runtime_calls.append(json.loads(config)["outbounds"][0]["protocol"]),
                restart_xray=lambda config: runtime_calls.append(f"restart:{json.loads(config)['outbounds'][0]['protocol']}"),
            )

            await manager.initialize()

            self.assertEqual(manager.active_node_fingerprint, vpn.node_fingerprint(persisted_node))
            self.assertEqual(runtime_calls, ["vless"])

    async def test_initialize_falls_back_to_next_viable_node_when_previous_node_disappears(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime_calls: list[str] = []
            state_path = Path(tmp) / "proxy_state.json"
            config_path = Path(tmp) / "xray-config.json"
            missing_node = vpn.parse_subscription_nodes(self.vless_link)[0]
            save_proxy_state(
                state_path,
                ProxyState(
                    active_node_fingerprint=vpn.node_fingerprint(missing_node),
                    active_node_index_hint=0,
                    generation=4,
                ),
            )

            manager = ProxyRuntimeManager(
                state_path=state_path,
                xray_config_path=config_path,
                subscription_loader=lambda: self.vmess_link,
                start_xray=lambda config: runtime_calls.append(json.loads(config)["outbounds"][0]["protocol"]),
                restart_xray=lambda config: runtime_calls.append(f"restart:{json.loads(config)['outbounds'][0]['protocol']}"),
            )

            await manager.initialize()

            expected_node = vpn.parse_subscription_nodes(self.vmess_link)[0]
            self.assertEqual(manager.active_node_fingerprint, vpn.node_fingerprint(expected_node))
            self.assertEqual(runtime_calls, ["vmess"])

    async def test_switch_to_next_node_skips_cooled_down_nodes_and_bumps_generation(self) -> None:
        with TemporaryDirectory() as tmp:
            runtime_calls: list[str] = []
            state_path = Path(tmp) / "proxy_state.json"
            config_path = Path(tmp) / "xray-config.json"
            now = 1_000.0

            manager = ProxyRuntimeManager(
                state_path=state_path,
                xray_config_path=config_path,
                subscription_loader=lambda: "\n".join([self.vless_link, self.vmess_link, self.jp_link]),
                start_xray=lambda config: runtime_calls.append(f"start:{json.loads(config)['outbounds'][0]['settings']['vnext'][0]['address']}"),
                restart_xray=lambda config: runtime_calls.append(f"restart:{json.loads(config)['outbounds'][0]['settings']['vnext'][0]['address']}"),
                time_fn=lambda: now,
            )

            await manager.initialize()
            active_before_switch = manager.active_node_fingerprint
            manager.mark_current_node_failed(reason="youtube_rate_limit", now=now)

            first_fallback = vpn.parse_subscription_nodes(self.vmess_link)[0]
            manager.state.failed_fingerprints[vpn.node_fingerprint(first_fallback)] = {
                "failed_at": now,
                "cooldown_until": now + 600,
                "reason": "proxy_error",
            }

            switched = await manager.switch_to_next_node(reason="youtube_rate_limit")

            expected_node = vpn.parse_subscription_nodes(self.jp_link)[0]
            self.assertTrue(switched)
            self.assertNotEqual(manager.active_node_fingerprint, active_before_switch)
            self.assertEqual(manager.active_node_fingerprint, vpn.node_fingerprint(expected_node))
            self.assertEqual(manager.current_generation, 2)
            self.assertIn("restart:jp.example.com", runtime_calls)
            self.assertTrue(config_path.exists())


class BuildProxyRuntimeTests(unittest.TestCase):
    def test_build_proxy_runtime_returns_none_when_subscription_url_is_absent(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = build_proxy_runtime(
                state_dir=Path(tmp),
                environ={},
                subscription_loader=lambda: "",
                start_xray=lambda config: None,
                restart_xray=lambda config: None,
            )

            self.assertIsNone(manager)

    def test_build_proxy_runtime_returns_manager_when_subscription_url_is_present(self) -> None:
        with TemporaryDirectory() as tmp:
            manager = build_proxy_runtime(
                state_dir=Path(tmp),
                environ={"VPN_SUBSCRIPTION_URL": "https://example.com/subscription"},
                subscription_loader=lambda: "",
                start_xray=lambda config: None,
                restart_xray=lambda config: None,
            )

            self.assertIsInstance(manager, ProxyRuntimeManager)
            self.assertEqual(manager.state_path, Path(tmp) / "proxy_state.json")
            self.assertEqual(manager.xray_config_path, Path(tmp) / "xray-config.json")


if __name__ == "__main__":
    unittest.main()
