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

    def test_load_config_parses_local_runtime_settings(self):
        config = load_config(
            {
                "TELEGRAM_BOT_TOKEN": "token",
                "TELEGRAM_ALLOWED_CHAT_ID": "42",
                "PUBLIC_DOWNLOAD_BASE_URL": "https://downloads.example.com/download/",
                "DOWNLOAD_DIR": "/srv/downloads",
                "STATE_DIR": "/srv/state",
                "HTTP_BIND": "0.0.0.0",
                "HTTP_PORT": "8081",
                "HTTP_TIMEOUT_SECONDS": "45",
                "POLL_INTERVAL_SECONDS": "2.5",
                "TASK_TIMEOUT_SECONDS": "900",
                "BOT_DEDUPE_WINDOW_SECONDS": "30",
            }
        )

        self.assertEqual(config.public_download_base_url, "https://downloads.example.com/download")
        self.assertEqual(config.download_dir, "/srv/downloads")
        self.assertEqual(config.state_dir, "/srv/state")
        self.assertEqual(config.sqlite_path, "/srv/state/tasks.sqlite3")
        self.assertEqual(config.http_bind, "0.0.0.0")
        self.assertEqual(config.http_port, 8081)
        self.assertEqual(config.http_timeout_seconds, 45)
        self.assertEqual(config.poll_interval_seconds, 2.5)
        self.assertEqual(config.task_timeout_seconds, 900)
