import base64
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch


APP_DIR = Path(__file__).resolve().parents[2] / "app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import vpn


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


class ParseSubscriptionNodesTests(unittest.TestCase):
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

    def test_parse_subscription_nodes_returns_all_supported_nodes_in_order(self) -> None:
        raw_subscription = "\n".join(
            [
                "not-a-node",
                self.vless_link,
                "ss://ignored-example",
                self.vmess_link,
            ]
        )

        nodes = vpn.parse_subscription_nodes(raw_subscription)

        self.assertEqual([node["protocol"] for node in nodes], ["vless", "vmess"])
        self.assertEqual(nodes[0]["settings"]["vnext"][0]["address"], "hk.example.com")
        self.assertEqual(nodes[1]["settings"]["vnext"][0]["address"], "us.example.com")

    def test_node_fingerprint_is_stable_when_subscription_order_changes(self) -> None:
        original_nodes = vpn.parse_subscription_nodes("\n".join([self.vless_link, self.vmess_link]))
        reordered_nodes = vpn.parse_subscription_nodes("\n".join([self.vmess_link, self.vless_link]))

        self.assertEqual(
            vpn.node_fingerprint(original_nodes[0]),
            vpn.node_fingerprint(reordered_nodes[1]),
        )
        self.assertEqual(
            vpn.node_fingerprint(original_nodes[1]),
            vpn.node_fingerprint(reordered_nodes[0]),
        )

    def test_parse_subscription_nodes_skips_invalid_lines_without_aborting(self) -> None:
        raw_subscription = "\n".join(
            [
                "vless://missing-parts",
                self.vless_link,
                "vmess://not-base64",
                self.vmess_link,
            ]
        )

        nodes = vpn.parse_subscription_nodes(raw_subscription)

        self.assertEqual(len(nodes), 2)


class FetchSubscriptionTests(unittest.TestCase):
    def test_fetch_subscription_bypasses_process_proxy_environment(self) -> None:
        response = Mock()
        response.read.return_value = b"subscription-data"

        context_manager = MagicMock()
        context_manager.__enter__.return_value = response

        opener = Mock()
        opener.open.return_value = context_manager

        with (
            patch.dict(
                "os.environ",
                {
                    "http_proxy": "http://127.0.0.1:10809",
                    "https_proxy": "http://127.0.0.1:10809",
                },
                clear=False,
            ),
            patch("vpn.urllib.request.ProxyHandler", return_value="no-proxy-handler") as proxy_handler,
            patch("vpn.urllib.request.build_opener", return_value=opener) as build_opener,
            patch("vpn.urllib.request.urlopen") as urlopen,
        ):
            urlopen.return_value.__enter__.return_value.read.return_value = b"subscription-data"

            result = vpn.fetch_subscription("https://example.com/subscription")

        self.assertEqual(result, "subscription-data")
        proxy_handler.assert_called_once_with({})
        build_opener.assert_called_once_with("no-proxy-handler")
        opener.open.assert_called_once()
        request_arg = opener.open.call_args.args[0]
        self.assertIsInstance(request_arg, vpn.urllib.request.Request)
        self.assertEqual(request_arg.full_url, "https://example.com/subscription")
        urlopen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
