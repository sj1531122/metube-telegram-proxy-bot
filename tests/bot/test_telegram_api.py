import json
from unittest import IsolatedAsyncioTestCase
from unittest.mock import patch
from urllib.error import URLError

from bot.errors import TelegramApiError
from bot.telegram_api import TelegramApi


class TelegramApiTests(IsolatedAsyncioTestCase):
    async def test_get_updates_calls_expected_endpoint(self):
        calls = []

        def fake_get(url, params):
            calls.append((url, params))
            return {"ok": True, "result": [{"update_id": 101}]}

        api = TelegramApi(bot_token="token", get_json=fake_get)

        updates = await api.get_updates(offset=55)

        self.assertEqual(updates, [{"update_id": 101}])
        self.assertEqual(
            calls,
            [
                (
                    "https://api.telegram.org/bottoken/getUpdates",
                    {"offset": 55, "timeout": 30},
                )
            ],
        )

    async def test_send_message_posts_expected_payload(self):
        calls = []

        def fake_post(url, payload):
            calls.append((url, payload))
            return {"ok": True, "result": {"message_id": 1}}

        api = TelegramApi(bot_token="token", post_json=fake_post)

        await api.send_message(chat_id=42, text="queued")

        self.assertEqual(
            calls,
            [
                (
                    "https://api.telegram.org/bottoken/sendMessage",
                    {"chat_id": 42, "text": "queued"},
                )
            ],
        )

    async def test_get_updates_raises_when_api_reports_error(self):
        def fake_get(url, params):
            return {"ok": False, "description": "bad token"}

        api = TelegramApi(bot_token="token", get_json=fake_get)

        with self.assertRaises(TelegramApiError):
            await api.get_updates(offset=55)

    async def test_send_message_raises_when_api_reports_error(self):
        def fake_post(url, payload):
            return {"ok": False, "description": "chat not found"}

        api = TelegramApi(bot_token="token", post_json=fake_post)

        with self.assertRaises(TelegramApiError):
            await api.send_message(chat_id=42, text="queued")

    async def test_get_updates_wraps_transport_error(self):
        api = TelegramApi(bot_token="token", timeout_seconds=7)

        with patch.object(TelegramApi, "_default_get_json", side_effect=URLError("offline")):
            with self.assertRaisesRegex(TelegramApiError, "offline"):
                await api.get_updates(offset=55)

    async def test_get_updates_uses_request_timeout_above_long_poll_timeout(self):
        calls = []

        def fake_default_get(url, params, timeout_seconds):
            calls.append((url, params, timeout_seconds))
            return {"ok": True, "result": []}

        api = TelegramApi(bot_token="token", timeout_seconds=30)

        with patch.object(TelegramApi, "_default_get_json", side_effect=fake_default_get):
            await api.get_updates(offset=55, timeout=30)

        self.assertEqual(
            calls,
            [
                (
                    "https://api.telegram.org/bottoken/getUpdates",
                    {"offset": 55, "timeout": 30},
                    35,
                )
            ],
        )

    async def test_send_message_wraps_json_decode_error(self):
        api = TelegramApi(bot_token="token", timeout_seconds=7)

        with patch.object(
            TelegramApi,
            "_default_post_json",
            side_effect=json.JSONDecodeError("bad json", "x", 0),
        ):
            with self.assertRaisesRegex(TelegramApiError, "bad json"):
                await api.send_message(chat_id=42, text="queued")
