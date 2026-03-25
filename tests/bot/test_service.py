from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from bot.config import BotConfig
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_SUBMITTED
from bot.service import BotService
from bot.store import TaskStore


class FakeMeTubeClient:
    def __init__(self, history=None, add_result=None):
        self.history = history or {"queue": [], "pending": [], "done": []}
        self.add_result = add_result or {"status": "ok"}
        self.added_urls = []

    async def add_download(self, url: str):
        self.added_urls.append(url)
        return self.add_result

    async def fetch_history(self):
        return self.history


class FakeTelegramApi:
    def __init__(self):
        self.messages = []

    async def send_message(self, chat_id: int, text: str):
        self.messages.append((chat_id, text))
        return {"ok": True}


class BotServiceTests(IsolatedAsyncioTestCase):
    def make_config(self, db_path: Path) -> BotConfig:
        return BotConfig(
            telegram_bot_token="token",
            telegram_allowed_chat_id=42,
            metube_base_url="https://metube.internal",
            metube_auth_header_name=None,
            metube_auth_header_value=None,
            public_host_url="https://download.example/files",
            public_host_audio_url="https://download.example/audio",
            sqlite_path=str(db_path),
            poll_interval_seconds=15,
            task_timeout_seconds=21600,
            dedupe_window_seconds=300,
        )

    async def test_handle_update_submits_allowed_url_and_acknowledges(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            metube = FakeMeTubeClient()
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 99,
                        "chat": {"id": 42},
                        "text": "download https://video.example/watch",
                    },
                }
            )

            tasks = store.list_unfinished_tasks()
            self.assertEqual(metube.added_urls, ["https://video.example/watch"])
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].state, STATE_SUBMITTED)
            self.assertEqual(telegram.messages, [(42, "Queued: https://video.example/watch")])

    async def test_handle_update_ignores_unauthorized_chat(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            metube = FakeMeTubeClient()
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 99,
                        "chat": {"id": 7},
                        "text": "download https://video.example/watch",
                    },
                }
            )

            self.assertEqual(store.list_unfinished_tasks(), [])
            self.assertEqual(metube.added_urls, [])
            self.assertEqual(telegram.messages, [])

    async def test_poll_once_sends_finished_download_link(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            store.update_task_state(task_id, STATE_SUBMITTED)
            metube = FakeMeTubeClient(
                history={
                    "queue": [],
                    "pending": [],
                    "done": [
                        {
                            "url": "https://video.example/watch",
                            "status": "finished",
                            "filename": "movie.mp4",
                            "title": "Movie",
                            "quality": "best",
                            "format": "mp4",
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_FINISHED)
            self.assertEqual(task.download_url, "https://download.example/files/movie.mp4")
            self.assertIsNotNone(task.notified_at)
            self.assertEqual(
                telegram.messages,
                [(42, "Finished: Movie\nhttps://download.example/files/movie.mp4")],
            )

    async def test_poll_once_reports_failed_download(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            store.update_task_state(task_id, STATE_SUBMITTED)
            metube = FakeMeTubeClient(
                history={
                    "queue": [],
                    "pending": [],
                    "done": [
                        {
                            "url": "https://video.example/watch",
                            "status": "error",
                            "title": "Movie",
                            "msg": "download failed",
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_FAILED)
            self.assertEqual(task.last_error, "download failed")
            self.assertEqual(
                telegram.messages,
                [(42, "Failed: Movie\nReason: download failed")],
            )
