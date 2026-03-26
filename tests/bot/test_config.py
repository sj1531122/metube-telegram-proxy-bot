from unittest import TestCase

from bot.config import BotConfig, load_config


class LoadConfigTests(TestCase):
    def test_load_config_requires_core_environment(self):
        with self.assertRaises(ValueError):
            load_config({})

    def test_load_config_requires_complete_auth_header_pair(self):
        with self.assertRaises(ValueError):
            load_config(
                {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_ALLOWED_CHAT_ID": "42",
                    "METUBE_BASE_URL": "https://metube.example/",
                    "METUBE_AUTH_HEADER_NAME": "Authorization",
                }
            )

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
                http_timeout_seconds=30,
                poll_interval_seconds=15,
                task_timeout_seconds=21600,
                dedupe_window_seconds=300,
            ),
        )

    def test_load_config_normalizes_public_urls_and_positive_intervals(self):
        config = load_config(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_ID": "42",
                "METUBE_BASE_URL": "https://metube.example/",
                "PUBLIC_HOST_URL": "https://download.example/files/",
                "PUBLIC_HOST_AUDIO_URL": "https://download.example/audio/",
                "BOT_HTTP_TIMEOUT_SECONDS": "25",
                "BOT_POLL_INTERVAL_SECONDS": "10",
                "BOT_TASK_TIMEOUT_SECONDS": "20",
                "BOT_DEDUPE_WINDOW_SECONDS": "30",
            }
        )

        self.assertEqual(config.public_host_url, "https://download.example/files")
        self.assertEqual(config.public_host_audio_url, "https://download.example/audio")
        self.assertEqual(config.http_timeout_seconds, 25)

        with self.assertRaises(ValueError):
            load_config(
                {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_ALLOWED_CHAT_ID": "42",
                    "METUBE_BASE_URL": "https://metube.example/",
                    "BOT_POLL_INTERVAL_SECONDS": "0",
                }
            )

        with self.assertRaises(ValueError):
            load_config(
                {
                    "TELEGRAM_BOT_TOKEN": "token",
                    "TELEGRAM_ALLOWED_CHAT_ID": "42",
                    "METUBE_BASE_URL": "https://metube.example/",
                    "BOT_HTTP_TIMEOUT_SECONDS": "0",
                }
            )
