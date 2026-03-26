from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import IsolatedAsyncioTestCase

from bot.config import BotConfig
from bot.errors import MeTubeApiError, TelegramApiError
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_RETRYING, STATE_SUBMITTED
from bot.service import BotService
from bot.store import TaskStore


class FakeMeTubeClient:
    def __init__(self, history=None, add_result=None):
        self.history = history or {"queue": [], "pending": [], "done": []}
        self.add_result = add_result or {"status": "ok"}
        self.added_urls = []
        self.cleared_done_ids = []
        self.raise_on_add = None
        self.raise_on_fetch = None
        self.raise_on_clear_done = None

    async def add_download(self, url: str):
        if self.raise_on_add is not None:
            raise self.raise_on_add
        self.added_urls.append(url)
        return self.add_result

    async def fetch_history(self):
        if self.raise_on_fetch is not None:
            raise self.raise_on_fetch
        return self.history

    async def clear_done_entries(self, ids: list[str]):
        if self.raise_on_clear_done is not None:
            raise self.raise_on_clear_done
        self.cleared_done_ids.append(ids)
        return {"status": "ok"}


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
            http_timeout_seconds=30,
            poll_interval_seconds=15,
            task_timeout_seconds=21600,
            dedupe_window_seconds=300,
        )

    def create_task(
        self,
        store: TaskStore,
        *,
        state: str = STATE_SUBMITTED,
        source_url: str = "https://video.example/watch",
        retry_count: int = 0,
        max_retries: int | None = None,
        next_retry_at: float | None = None,
        retry_notice_sent_at: float | None = None,
        last_attempt_submitted_at: float | None = None,
    ) -> int:
        task_id = store.create_task(
            chat_id=42,
            telegram_message_id=99,
            source_url=source_url,
        )
        store.update_task_state(
            task_id,
            state,
            retry_count=retry_count,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
            retry_notice_sent_at=retry_notice_sent_at,
            last_attempt_submitted_at=last_attempt_submitted_at,
        )
        return task_id

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

    async def test_handle_update_normalizes_youtube_short_url_for_submission_and_history_matching(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            metube = FakeMeTubeClient(
                history={
                    "queue": [],
                    "pending": [],
                    "done": [
                        {
                            "url": "https://www.youtube.com/watch?v=lNjhCIvNaI4",
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

            await service.handle_update(
                {
                    "update_id": 1,
                    "message": {
                        "message_id": 99,
                        "chat": {"id": 42},
                        "text": "download https://youtu.be/lNjhCIvNaI4?si=5ZD1RXPJXZ0j7l8b",
                    },
                }
            )
            await service.poll_once()

            task = store.get_task(1)
            self.assertEqual(metube.added_urls, ["https://www.youtube.com/watch?v=lNjhCIvNaI4"])
            self.assertEqual(task.source_url, "https://www.youtube.com/watch?v=lNjhCIvNaI4")
            self.assertEqual(task.state, STATE_FINISHED)
            self.assertEqual(
                telegram.messages,
                [
                    (42, "Queued: https://www.youtube.com/watch?v=lNjhCIvNaI4"),
                    (42, "Finished: Movie\nhttps://download.example/files/movie.mp4"),
                ],
            )

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

            with self.assertLogs("bot.service", "INFO") as logs:
                await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_FINISHED)
            self.assertEqual(task.download_url, "https://download.example/files/movie.mp4")
            self.assertIsNotNone(task.notified_at)
            self.assertEqual(
                telegram.messages,
                [(42, "Finished: Movie\nhttps://download.example/files/movie.mp4")],
            )
            self.assertTrue(any("task finished" in entry for entry in logs.output))

    async def test_poll_once_reports_failed_download_after_retry_budget_is_exhausted(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                retry_count=5,
                max_retries=5,
                retry_notice_sent_at=950.0,
                last_attempt_submitted_at=900.0,
            )
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
                            "timestamp": 950.0,
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: 1000.0,
            )

            with self.assertLogs("bot.service", "WARNING") as logs:
                await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_FAILED)
            self.assertEqual(task.last_error, "download failed")
            self.assertEqual(
                telegram.messages,
                [(42, "Failed: Movie\nReason: download failed")],
            )
            self.assertTrue(any("task failed" in entry for entry in logs.output))

    async def test_poll_once_moves_first_failure_to_retrying_and_sends_retry_notice(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                last_attempt_submitted_at=900.0,
            )
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
                            "timestamp": 950.0,
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: 1000.0,
            )

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.retry_count, 0)
            self.assertEqual(task.max_retries, 5)
            self.assertEqual(task.next_retry_at, 1030.0)
            self.assertEqual(task.retry_notice_sent_at, 1000.0)
            self.assertEqual(task.last_error, "download failed")
            self.assertEqual(
                telegram.messages,
                [(42, "Failed once, retrying automatically (1/5): Movie")],
            )

    async def test_poll_once_does_not_refail_retrying_task_from_same_done_entry(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                last_attempt_submitted_at=900.0,
            )
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
                            "timestamp": 950.0,
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            now = [1000.0]
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: now[0],
            )

            await service.poll_once()
            now[0] = 1010.0
            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.next_retry_at, 1030.0)
            self.assertEqual(
                telegram.messages,
                [(42, "Failed once, retrying automatically (1/5): Movie")],
            )

    async def test_poll_once_resubmits_retrying_task_and_clears_done_entry(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                state=STATE_RETRYING,
                retry_count=0,
                max_retries=5,
                next_retry_at=1000.0,
                retry_notice_sent_at=950.0,
                last_attempt_submitted_at=900.0,
            )
            metube = FakeMeTubeClient()
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: 1000.0,
            )

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(metube.added_urls, ["https://video.example/watch"])
            self.assertEqual(metube.cleared_done_ids, [["https://video.example/watch"]])
            self.assertEqual(task.state, STATE_SUBMITTED)
            self.assertEqual(task.retry_count, 1)
            self.assertIsNone(task.next_retry_at)
            self.assertEqual(task.last_attempt_submitted_at, 1000.0)
            self.assertEqual(telegram.messages, [])

    async def test_poll_once_logs_delete_failure_without_crashing_retry_flow(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                state=STATE_RETRYING,
                retry_count=0,
                max_retries=5,
                next_retry_at=1000.0,
                retry_notice_sent_at=950.0,
                last_attempt_submitted_at=900.0,
            )
            metube = FakeMeTubeClient()
            metube.raise_on_clear_done = MeTubeApiError("delete failed")
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: 1000.0,
            )

            with self.assertLogs("bot.service", "WARNING") as logs:
                await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_SUBMITTED)
            self.assertEqual(task.retry_count, 1)
            self.assertTrue(any("delete failed" in entry for entry in logs.output))

    async def test_poll_once_ignores_stale_failed_done_entry_after_retry_submission(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                retry_count=1,
                max_retries=5,
                retry_notice_sent_at=950.0,
                last_attempt_submitted_at=1000.0,
            )
            metube = FakeMeTubeClient(
                history={
                    "queue": [],
                    "pending": [],
                    "done": [
                        {
                            "url": "https://video.example/watch",
                            "status": "error",
                            "title": "Movie",
                            "msg": "stale failure",
                            "timestamp": 950.0,
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: 1100.0,
            )

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_SUBMITTED)
            self.assertEqual(task.last_error, None)
            self.assertEqual(telegram.messages, [])

    async def test_poll_once_does_not_send_second_retry_notice_after_another_failed_attempt(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            task_id = self.create_task(
                store,
                last_attempt_submitted_at=900.0,
            )
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
                            "timestamp": 950.0,
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            now = [1000.0]
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: now[0],
            )

            await service.poll_once()
            metube.history = {"queue": [], "pending": [], "done": []}
            now[0] = 1030.0
            await service.poll_once()
            metube.history = {
                "queue": [],
                "pending": [],
                "done": [
                    {
                        "url": "https://video.example/watch",
                        "status": "error",
                        "title": "Movie",
                        "msg": "download failed again",
                        "timestamp": 1040.0,
                    }
                ],
            }
            now[0] = 1050.0
            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.retry_count, 1)
            self.assertEqual(task.next_retry_at, 1110.0)
            self.assertEqual(len(telegram.messages), 1)
            self.assertEqual(
                telegram.messages[0],
                (42, "Failed once, retrying automatically (1/5): Movie"),
            )

    async def test_handle_update_reports_submission_exception(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            metube = FakeMeTubeClient()
            metube.raise_on_add = MeTubeApiError("metube unavailable")
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            with self.assertLogs("bot.service", "WARNING") as logs:
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

            task = store.find_recent_duplicate("https://video.example/watch", within_seconds=300)
            self.assertIsNotNone(task)
            self.assertEqual(task.state, STATE_FAILED)
            self.assertEqual(task.last_error, "metube unavailable")
            self.assertEqual(
                telegram.messages,
                [(42, "Failed: https://video.example/watch\nReason: metube unavailable")],
            )
            self.assertTrue(any("download submission failed" in entry for entry in logs.output))

    async def test_handle_update_logs_telegram_send_failure(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            store = TaskStore(db_path)
            metube = FakeMeTubeClient()
            telegram = FakeTelegramApi()
            telegram.raise_exc = TelegramApiError("chat blocked")
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            with self.assertLogs("bot.service", "WARNING") as logs:
                with self.assertRaisesRegex(TelegramApiError, "chat blocked"):
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

    async def test_poll_once_ignores_history_fetch_exception(self):
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
            metube = FakeMeTubeClient()
            metube.raise_on_fetch = MeTubeApiError("history unavailable")
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_SUBMITTED)
            self.assertEqual(telegram.messages, [])

    async def test_poll_once_uses_audio_public_host_for_audio_downloads(self):
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
                            "filename": "track.mp3",
                            "title": "Track",
                            "quality": "audio",
                            "format": "mp3",
                        }
                    ],
                }
            )
            telegram = FakeTelegramApi()
            service = BotService(config=config, store=store, metube_client=metube, telegram_api=telegram)

            await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.download_url, "https://download.example/audio/track.mp3")
            self.assertEqual(
                telegram.messages,
                [(42, "Finished: Track\nhttps://download.example/audio/track.mp3")],
            )

    async def test_poll_once_logs_task_timeout(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            config = self.make_config(db_path)
            config.task_timeout_seconds = 1
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=42,
                telegram_message_id=99,
                source_url="https://video.example/watch",
            )
            task = store.get_task(task_id)
            store.update_task_state(task_id, STATE_SUBMITTED)
            metube = FakeMeTubeClient()
            telegram = FakeTelegramApi()
            service = BotService(
                config=config,
                store=store,
                metube_client=metube,
                telegram_api=telegram,
                time_fn=lambda: task.submitted_at + 5,
            )

            with self.assertLogs("bot.service", "WARNING") as logs:
                await service.poll_once()

            task = store.get_task(task_id)
            self.assertEqual(task.last_error, "task timed out")
            self.assertEqual(telegram.messages, [(42, "Timeout: https://video.example/watch")])
            self.assertTrue(any("task timed out" in entry for entry in logs.output))
