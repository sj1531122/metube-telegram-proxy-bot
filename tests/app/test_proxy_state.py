from pathlib import Path
from tempfile import TemporaryDirectory
import sys
import unittest


APP_DIR = Path(__file__).resolve().parents[2] / "app"

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from proxy_state import ProxyState, load_proxy_state, save_proxy_state


class ProxyStatePersistenceTests(unittest.TestCase):
    def test_load_proxy_state_returns_defaults_when_file_is_missing(self) -> None:
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proxy_state.json"

            state = load_proxy_state(state_path)

            self.assertIsNone(state.active_node_fingerprint)
            self.assertIsNone(state.active_node_index_hint)
            self.assertEqual(state.generation, 0)
            self.assertEqual(state.failed_fingerprints, {})

    def test_load_proxy_state_returns_defaults_when_json_is_corrupted(self) -> None:
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proxy_state.json"
            state_path.write_text("{not-json", encoding="utf-8")

            state = load_proxy_state(state_path)

            self.assertIsNone(state.active_node_fingerprint)
            self.assertEqual(state.failed_fingerprints, {})

    def test_save_proxy_state_writes_atomically_and_cleans_up_temp_file(self) -> None:
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proxy_state.json"
            state = ProxyState(
                active_node_fingerprint="fingerprint-a",
                active_node_index_hint=2,
                generation=3,
            )

            save_proxy_state(state_path, state)

            self.assertTrue(state_path.exists())
            self.assertFalse(state_path.with_suffix(".json.tmp").exists())

    def test_failed_node_cooldown_metadata_roundtrips(self) -> None:
        with TemporaryDirectory() as tmp:
            state_path = Path(tmp) / "proxy_state.json"
            state = ProxyState(
                active_node_fingerprint="fingerprint-a",
                active_node_index_hint=1,
                generation=5,
                failed_fingerprints={
                    "fingerprint-a": {
                        "failed_at": 123.0,
                        "cooldown_until": 456.0,
                        "reason": "youtube_rate_limit",
                    }
                },
            )

            save_proxy_state(state_path, state)
            reloaded = load_proxy_state(state_path)

            self.assertEqual(reloaded.active_node_fingerprint, "fingerprint-a")
            self.assertEqual(reloaded.active_node_index_hint, 1)
            self.assertEqual(reloaded.generation, 5)
            self.assertEqual(
                reloaded.failed_fingerprints["fingerprint-a"]["cooldown_until"],
                456.0,
            )


if __name__ == "__main__":
    unittest.main()
