from unittest import IsolatedAsyncioTestCase

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
