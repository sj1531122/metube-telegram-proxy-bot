import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from urllib.error import URLError

from bot.errors import MeTubeApiError
from bot.metube_client import MeTubeClient


class MeTubeClientTests(IsolatedAsyncioTestCase):
    async def test_add_download_posts_expected_payload(self):
        calls = []

        def fake_post(url, payload, headers):
            calls.append((url, payload, headers))
            return {"status": "ok"}

        client = MeTubeClient(
            base_url="https://metube.example",
            auth_header_name="Authorization",
            auth_header_value="Bearer token",
            post_json=fake_post,
        )

        result = await client.add_download("https://video.example/watch")

        self.assertEqual(result, {"status": "ok"})
        self.assertEqual(
            calls,
            [
                (
                    "https://metube.example/add",
                    {
                        "url": "https://video.example/watch",
                        "quality": "best",
                        "format": "any",
                        "auto_start": True,
                    },
                    {"Authorization": "Bearer token"},
                )
            ],
        )

    async def test_fetch_history_returns_normalized_shape(self):
        def fake_get(url, headers):
            self.assertEqual(url, "https://metube.example/history")
            self.assertEqual(headers, {})
            return {"done": [{"url": "https://done.example"}]}

        client = MeTubeClient(
            base_url="https://metube.example",
            get_json=fake_get,
        )

        history = await client.fetch_history()

        self.assertEqual(
            history,
            {
                "queue": [],
                "pending": [],
                "done": [{"url": "https://done.example"}],
            },
        )

    async def test_add_download_wraps_transport_error(self):
        client = MeTubeClient(base_url="https://metube.example", timeout_seconds=7)

        with patch.object(MeTubeClient, "_default_post_json", side_effect=URLError("metube down")):
            with self.assertRaisesRegex(MeTubeApiError, "metube down"):
                await client.add_download("https://video.example/watch")

    async def test_fetch_history_wraps_json_decode_error(self):
        client = MeTubeClient(base_url="https://metube.example", timeout_seconds=7)

        with patch.object(
            MeTubeClient,
            "_default_get_json",
            side_effect=json.JSONDecodeError("bad json", "x", 0),
        ):
            with self.assertRaisesRegex(MeTubeApiError, "bad json"):
                await client.fetch_history()
