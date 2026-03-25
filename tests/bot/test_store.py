import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from bot.models import STATE_FINISHED, STATE_RECEIVED, STATE_RETRYING, STATE_SUBMITTED
from bot.store import TaskStore


class TaskStoreTests(TestCase):
    def test_insert_and_reload_roundtrip(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)

            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://a.example",
            )

            reloaded = TaskStore(db_path)
            task = reloaded.get_task(task_id)

            self.assertEqual(task.id, task_id)
            self.assertEqual(task.chat_id, 1)
            self.assertEqual(task.telegram_message_id, 10)
            self.assertEqual(task.source_url, "https://a.example")
            self.assertEqual(task.state, STATE_RECEIVED)

    def test_find_recent_duplicate_returns_matching_task(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://a.example",
            )

            duplicate = store.find_recent_duplicate(
                source_url="https://a.example",
                within_seconds=300,
            )

            self.assertIsNotNone(duplicate)
            self.assertEqual(duplicate.id, task_id)

    def test_retry_metadata_fields_roundtrip(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://a.example",
            )

            store.update_task_state(
                task_id,
                STATE_RETRYING,
                retry_count=1,
                max_retries=3,
                next_retry_at=123.0,
                retry_notice_sent_at=124.0,
                last_attempt_submitted_at=125.0,
            )

            task = TaskStore(db_path).get_task(task_id)
            self.assertEqual(task.state, STATE_RETRYING)
            self.assertEqual(task.retry_count, 1)
            self.assertEqual(task.max_retries, 3)
            self.assertEqual(task.next_retry_at, 123.0)
            self.assertEqual(task.retry_notice_sent_at, 124.0)
            self.assertEqual(task.last_attempt_submitted_at, 125.0)

    def test_update_task_state_can_clear_retry_metadata_fields(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)
            task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://a.example",
            )

            store.update_task_state(
                task_id,
                STATE_RETRYING,
                retry_count=1,
                max_retries=5,
                next_retry_at=123.0,
                retry_notice_sent_at=124.0,
                last_attempt_submitted_at=125.0,
            )
            store.update_task_state(
                task_id,
                STATE_SUBMITTED,
                max_retries=None,
                next_retry_at=None,
                retry_notice_sent_at=None,
                last_attempt_submitted_at=None,
            )

            task = store.get_task(task_id)
            self.assertEqual(task.state, STATE_SUBMITTED)
            self.assertEqual(task.retry_count, 1)
            self.assertIsNone(task.max_retries)
            self.assertIsNone(task.next_retry_at)
            self.assertIsNone(task.retry_notice_sent_at)
            self.assertIsNone(task.last_attempt_submitted_at)

    def test_init_db_migrates_legacy_schema_in_place(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            with sqlite3.connect(db_path) as connection:
                connection.execute(
                    """
                    CREATE TABLE tasks (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        chat_id INTEGER NOT NULL,
                        telegram_message_id INTEGER NOT NULL,
                        source_url TEXT NOT NULL,
                        submitted_at REAL NOT NULL,
                        state TEXT NOT NULL,
                        download_url TEXT,
                        filename TEXT,
                        title TEXT,
                        last_error TEXT,
                        notified_at REAL
                    )
                    """
                )
                connection.execute(
                    """
                    INSERT INTO tasks (
                        chat_id,
                        telegram_message_id,
                        source_url,
                        submitted_at,
                        state
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (1, 10, "https://a.example", 100.0, STATE_RECEIVED),
                )

            store = TaskStore(db_path)
            task = store.get_task(1)
            self.assertEqual(task.source_url, "https://a.example")
            self.assertEqual(task.retry_count, 0)
            self.assertIsNone(task.max_retries)
            self.assertIsNone(task.next_retry_at)
            self.assertIsNone(task.retry_notice_sent_at)
            self.assertIsNone(task.last_attempt_submitted_at)

    def test_init_db_ignores_duplicate_column_race(self):
        class FakeCursor:
            def __init__(self, rows):
                self._rows = rows

            def fetchall(self):
                return self._rows

        class FakeConnection:
            def __init__(self):
                self.alter_calls = []

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def execute(self, sql):
                if sql == "PRAGMA table_info(tasks)":
                    return FakeCursor(
                        [
                            {"name": "id"},
                            {"name": "chat_id"},
                            {"name": "telegram_message_id"},
                            {"name": "source_url"},
                            {"name": "submitted_at"},
                            {"name": "state"},
                            {"name": "download_url"},
                            {"name": "filename"},
                            {"name": "title"},
                            {"name": "last_error"},
                            {"name": "notified_at"},
                        ]
                    )
                if sql.startswith("ALTER TABLE"):
                    self.alter_calls.append(sql)
                    if "retry_count" in sql:
                        raise sqlite3.OperationalError("duplicate column name: retry_count")
                return FakeCursor([])

        class FakeTaskStore(TaskStore):
            def __init__(self, connection):
                self._connection = connection

            def _connect(self):
                return self._connection

        fake_connection = FakeConnection()
        store = FakeTaskStore(fake_connection)

        store._init_db()

        self.assertEqual(len(fake_connection.alter_calls), 5)

    def test_list_unfinished_tasks_includes_retrying(self):
        with TemporaryDirectory() as tmp:
            db_path = Path(tmp) / "tasks.sqlite3"
            store = TaskStore(db_path)
            retrying_task_id = store.create_task(
                chat_id=1,
                telegram_message_id=10,
                source_url="https://retry.example",
            )
            done_task_id = store.create_task(
                chat_id=2,
                telegram_message_id=20,
                source_url="https://done.example",
            )

            store.update_task_state(retrying_task_id, STATE_RETRYING)
            store.update_task_state(done_task_id, STATE_FINISHED)

            unfinished_ids = {task.id for task in store.list_unfinished_tasks()}
            self.assertIn(retrying_task_id, unfinished_ids)
            self.assertNotIn(done_task_id, unfinished_ids)
