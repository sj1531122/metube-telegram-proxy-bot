from __future__ import annotations

import sqlite3
import time
from pathlib import Path
from typing import Iterable

from bot.models import (
    BotTask,
    STATE_FAILED,
    STATE_FINISHED,
    STATE_QUEUED,
    STATE_RECEIVED,
    STATE_SUBMITTED,
    STATE_TIMEOUT,
)

UNFINISHED_STATES = (
    STATE_RECEIVED,
    STATE_SUBMITTED,
    STATE_QUEUED,
)


class TaskStore:
    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.db_path)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS tasks (
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

    def create_task(self, chat_id: int, telegram_message_id: int, source_url: str) -> int:
        submitted_at = time.time()
        with self._connect() as connection:
            cursor = connection.execute(
                """
                INSERT INTO tasks (
                    chat_id,
                    telegram_message_id,
                    source_url,
                    submitted_at,
                    state
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (chat_id, telegram_message_id, source_url, submitted_at, STATE_RECEIVED),
            )
            return int(cursor.lastrowid)

    def get_task(self, task_id: int) -> BotTask:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
        if row is None:
            raise KeyError(task_id)
        return self._row_to_task(row)

    def find_recent_duplicate(self, source_url: str, within_seconds: int) -> BotTask | None:
        cutoff = time.time() - within_seconds
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE source_url = ?
                  AND submitted_at >= ?
                ORDER BY submitted_at DESC
                LIMIT 1
                """,
                (source_url, cutoff),
            ).fetchone()
        return None if row is None else self._row_to_task(row)

    def list_unfinished_tasks(self) -> list[BotTask]:
        placeholders = ", ".join("?" for _ in UNFINISHED_STATES)
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT * FROM tasks WHERE state IN ({placeholders}) ORDER BY submitted_at ASC",
                UNFINISHED_STATES,
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def update_task_state(
        self,
        task_id: int,
        state: str,
        *,
        download_url: str | None = None,
        filename: str | None = None,
        title: str | None = None,
        last_error: str | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                UPDATE tasks
                SET state = ?,
                    download_url = COALESCE(?, download_url),
                    filename = COALESCE(?, filename),
                    title = COALESCE(?, title),
                    last_error = COALESCE(?, last_error)
                WHERE id = ?
                """,
                (state, download_url, filename, title, last_error, task_id),
            )

    def mark_notified(self, task_id: int, notified_at: float | None = None) -> None:
        if notified_at is None:
            notified_at = time.time()
        with self._connect() as connection:
            connection.execute(
                "UPDATE tasks SET notified_at = ? WHERE id = ?",
                (notified_at, task_id),
            )

    @staticmethod
    def _row_to_task(row: sqlite3.Row) -> BotTask:
        return BotTask(
            id=row["id"],
            chat_id=row["chat_id"],
            telegram_message_id=row["telegram_message_id"],
            source_url=row["source_url"],
            state=row["state"],
            submitted_at=row["submitted_at"],
            download_url=row["download_url"],
            filename=row["filename"],
            title=row["title"],
            last_error=row["last_error"],
            notified_at=row["notified_at"],
        )
