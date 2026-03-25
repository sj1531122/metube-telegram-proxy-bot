from unittest import TestCase

from bot.config import BotConfig, load_config


class LoadConfigTests(TestCase):
    def test_load_config_requires_core_environment(self):
        with self.assertRaises(ValueError):
            load_config({})

    def test_load_config_parses_required_settings(self):
        config = load_config(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_ID": "42",
                "METUBE_BASE_URL": "https://metube.example/",
            }
        )

        self.assertEqual(
            config,
            BotConfig(
                telegram_bot_token="token",
                telegram_allowed_chat_id=42,
                metube_base_url="https://metube.example",
                metube_auth_header_name=None,
                metube_auth_header_value=None,
                public_host_url=None,
                public_host_audio_url=None,
                sqlite_path="bot/tasks.sqlite3",
                poll_interval_seconds=15,
                task_timeout_seconds=21600,
                dedupe_window_seconds=300,
            ),
        )
