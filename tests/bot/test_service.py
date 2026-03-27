from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from bot.config import BotConfig
from bot.errors import TelegramApiError
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_QUEUED, STATE_TIMEOUT
from bot.service import BotService
from bot.store import TaskStore


class FakeTelegramApi:
    def __init__(self):
        self.messages = []
        self.raise_exc = None

    async def send_message(self, chat_id: int, text: str):
        if self.raise_exc is not None:
            raise self.raise_exc
        self.messages.append((chat_id, text))
        return {"ok": True}


class BotServiceTests(IsolatedAsyncioTestCase):
    def make_config(
        self,
        db_path: Path,
        *,
        telegram_allowed_chat_id: int | None = 42,
        telegram_allowed_user_ids: tuple[int, ...] = (),
    ) -> BotConfig:
        return BotConfig(
            telegram_bot_token="token",
            telegram_allowed_chat_id=telegram_allowed_chat_id,
            telegram_allowed_user_ids=telegram_allowed_user_ids,
            sqlite_path=str(db_path),
            public_download_base_url="https://downloads.example.com/download",
            download_dir="downloads",
            state_dir=str(db_path.parent),
            http_timeout_seconds=30,
            poll_interval_seconds=1.0,
            task_timeout_seconds=60,
            dedupe_window_seconds=300,
            http_bind="0.0.0.0",
            http_port=8081,
        )

    async def test_handle_update_queues_allowed_url_and_acknowledges(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

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
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].state, STATE_QUEUED)
            self.assertEqual(tasks[0].source_url, "https://video.example/watch")
            self.assertEqual(telegram.messages, [(42, "Queued: https://video.example/watch")])

    async def test_handle_update_normalizes_youtube_short_url_for_queueing(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 99,
                        "chat": {"id": 42},
                        "text": "download https://youtu.be/lNjhCIvNaI4?si=abc",
                    },
                }
            )

            task = store.get_task(1)
            self.assertEqual(task.source_url, "https://www.youtube.com/watch?v=lNjhCIvNaI4")
            self.assertEqual(
                telegram.messages,
                [(42, "Queued: https://www.youtube.com/watch?v=lNjhCIvNaI4")],
            )

    async def test_handle_update_reports_duplicate_recent_url(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            update = {
                "update_id": 1,
                "message": {
                    "message_id": 99,
                    "chat": {"id": 42},
                    "text": "download https://video.example/watch",
                },
            }
            await service.handle_update(update)
            await service.handle_update(update)

            self.assertEqual(len(store.list_unfinished_tasks()), 1)
            self.assertEqual(
                telegram.messages,
                [
                    (42, "Queued: https://video.example/watch"),
                    (42, "Already queued: https://video.example/watch"),
                ],
            )

    async def test_handle_update_ignores_unauthorized_chat(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

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
            self.assertEqual(telegram.messages, [])

    async def test_handle_update_private_mode_queues_authorized_private_user(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path, telegram_allowed_user_ids=(101,))
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 5001, "type": "private"},
                        "from": {"id": 101},
                        "text": "download https://video.example/watch",
                    }
                }
            )

            tasks = store.list_unfinished_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].user_id, 101)
            self.assertEqual(tasks[0].source_url, "https://video.example/watch")
            self.assertEqual(telegram.messages, [(5001, "Queued: https://video.example/watch")])

    async def test_handle_update_private_mode_ignores_unauthorized_private_user(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path, telegram_allowed_user_ids=(101,))
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 5001, "type": "private"},
                        "from": {"id": 999},
                        "text": "download https://video.example/watch",
                    }
                }
            )

            self.assertEqual(store.list_unfinished_tasks(), [])
            self.assertEqual(telegram.messages, [])

    async def test_handle_update_private_mode_ignores_authorized_user_in_group_chat(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path, telegram_allowed_user_ids=(101,))
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": -2001, "type": "group"},
                        "from": {"id": 101},
                        "text": "download https://video.example/watch",
                    }
                }
            )

            self.assertEqual(store.list_unfinished_tasks(), [])
            self.assertEqual(telegram.messages, [])

    async def test_handle_update_private_mode_dedupes_same_user_same_url(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path, telegram_allowed_user_ids=(101,))
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)
            update = {
                "message": {
                    "message_id": 1,
                    "chat": {"id": 5001, "type": "private"},
                    "from": {"id": 101},
                    "text": "download https://video.example/watch",
                }
            }

            await service.handle_update(update)
            await service.handle_update(update)

            tasks = store.list_unfinished_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertEqual(tasks[0].user_id, 101)
            self.assertEqual(
                telegram.messages,
                [
                    (5001, "Queued: https://video.example/watch"),
                    (5001, "Already queued: https://video.example/watch"),
                ],
            )

    async def test_handle_update_private_mode_allows_same_url_for_different_users(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path, telegram_allowed_user_ids=(101, 202))
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 5001, "type": "private"},
                        "from": {"id": 101},
                        "text": "download https://video.example/watch",
                    }
                }
            )
            await service.handle_update(
                {
                    "message": {
                        "message_id": 2,
                        "chat": {"id": 5002, "type": "private"},
                        "from": {"id": 202},
                        "text": "download https://video.example/watch",
                    }
                }
            )

            tasks = store.list_unfinished_tasks()
            self.assertEqual(len(tasks), 2)
            self.assertEqual(tasks[0].user_id, 101)
            self.assertEqual(tasks[1].user_id, 202)
            self.assertEqual(
                telegram.messages,
                [
                    (5001, "Queued: https://video.example/watch"),
                    (5002, "Queued: https://video.example/watch"),
                ],
            )

    async def test_handle_update_legacy_mode_uses_chat_gate_when_user_list_empty(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(
                db_path,
                telegram_allowed_chat_id=42,
                telegram_allowed_user_ids=(),
            )
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.handle_update(
                {
                    "message": {
                        "message_id": 1,
                        "chat": {"id": 42, "type": "group"},
                        "from": {"id": 999},
                        "text": "download https://video.example/watch",
                    }
                }
            )

            tasks = store.list_unfinished_tasks()
            self.assertEqual(len(tasks), 1)
            self.assertIsNone(tasks[0].user_id)
            self.assertEqual(telegram.messages, [(42, "Queued: https://video.example/watch")])

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
            store.update_task_state(
                task_id,
                STATE_FINISHED,
                title="Movie",
                filename="movie.mp4",
                download_url="https://downloads.example.com/download/movie.mp4",
            )
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertIsNotNone(task.notified_at)
            self.assertEqual(
                telegram.messages,
                [(42, "Finished: Movie\nhttps://downloads.example.com/download/movie.mp4")],
            )

    async def test_poll_once_sends_failed_message(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            store.update_task_state(
                task_id,
                STATE_FAILED,
                title="Movie",
                last_error="download failed",
            )
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.poll_once()

            self.assertEqual(
                telegram.messages,
                [(42, "Failed: Movie\nReason: download failed")],
            )

    async def test_poll_once_marks_aged_task_timeout_and_notifies(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            task = store.get_task(task_id)
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                telegram_api=telegram,
                time_fn=lambda: task.submitted_at + config.task_timeout_seconds + 1,
            )

            await service.poll_once()

            refreshed = store.get_task(task_id)
            self.assertEqual(refreshed.state, STATE_TIMEOUT)
            self.assertEqual(
                telegram.messages,
                [(42, "Timeout: https://video.example/watch")],
            )

    async def test_poll_once_does_not_resend_notified_terminal_task(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            store.update_task_state(
                task_id,
                STATE_FINISHED,
                title="Movie",
                download_url="https://downloads.example.com/download/movie.mp4",
            )
            store.mark_notified(task_id, notified_at=123.0)
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, telegram_api=telegram)

            await service.poll_once()

            self.assertEqual(telegram.messages, [])

    async def test_handle_update_logs_telegram_send_failure(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            telegram = FakeTelegramApi()
            telegram.raise_exc = TelegramApiError("send failed")
            service = BotService(config=config, store=store, telegram_api=telegram)

            with self.assertLogs("bot.service", "WARNING") as logs:
                with self.assertRaises(TelegramApiError):
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

            self.assertTrue(any("telegram send failed" in entry for entry in logs.output))
