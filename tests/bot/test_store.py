from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from bot.models import STATE_RECEIVED
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
