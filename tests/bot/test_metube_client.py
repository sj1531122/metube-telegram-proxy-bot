from unittest import IsolatedAsyncioTestCase

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
