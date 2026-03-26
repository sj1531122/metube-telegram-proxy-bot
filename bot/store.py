from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path

from bot.models import (
    BotTask,
    STATE_DOWNLOADING,
    STATE_FAILED,
    STATE_FINISHED,
    STATE_QUEUED,
    STATE_RECEIVED,
    STATE_RETRYING,
    STATE_SUBMITTED,
    STATE_TIMEOUT,
)

UNFINISHED_STATES = (
    STATE_RECEIVED,
    STATE_SUBMITTED,
    STATE_QUEUED,
    STATE_DOWNLOADING,
    STATE_RETRYING,
)
_UNSET = object()


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
                    started_at REAL,
                    finished_at REAL,
                    notified_at REAL,
                    proxy_generation_started INTEGER,
                    failover_attempts INTEGER NOT NULL DEFAULT 0,
                    attempted_node_fingerprints TEXT,
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    max_retries INTEGER,
                    next_retry_at REAL,
                    retry_notice_sent_at REAL,
                    last_attempt_submitted_at REAL
                )
                """
            )
            existing_columns = {
                row["name"]
                for row in connection.execute("PRAGMA table_info(tasks)").fetchall()
            }
            migrations = {
                "retry_count": "ALTER TABLE tasks ADD COLUMN retry_count INTEGER NOT NULL DEFAULT 0",
                "max_retries": "ALTER TABLE tasks ADD COLUMN max_retries INTEGER",
                "next_retry_at": "ALTER TABLE tasks ADD COLUMN next_retry_at REAL",
                "retry_notice_sent_at": "ALTER TABLE tasks ADD COLUMN retry_notice_sent_at REAL",
                "last_attempt_submitted_at": "ALTER TABLE tasks ADD COLUMN last_attempt_submitted_at REAL",
                "started_at": "ALTER TABLE tasks ADD COLUMN started_at REAL",
                "finished_at": "ALTER TABLE tasks ADD COLUMN finished_at REAL",
                "proxy_generation_started": "ALTER TABLE tasks ADD COLUMN proxy_generation_started INTEGER",
                "failover_attempts": "ALTER TABLE tasks ADD COLUMN failover_attempts INTEGER NOT NULL DEFAULT 0",
                "attempted_node_fingerprints": "ALTER TABLE tasks ADD COLUMN attempted_node_fingerprints TEXT",
            }
            for column_name, ddl in migrations.items():
                if column_name not in existing_columns:
                    try:
                        connection.execute(ddl)
                    except sqlite3.OperationalError as exc:
                        if "duplicate column name" not in str(exc).lower():
                            raise

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
                (chat_id, telegram_message_id, source_url, submitted_at, STATE_QUEUED),
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

    def list_pending_notifications(self) -> list[BotTask]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM tasks
                WHERE state IN (?, ?, ?)
                  AND notified_at IS NULL
                ORDER BY submitted_at ASC
                """,
                (STATE_FINISHED, STATE_FAILED, STATE_TIMEOUT),
            ).fetchall()
        return [self._row_to_task(row) for row in rows]

    def claim_next_runnable_task(self, *, now: float | None = None) -> BotTask | None:
        if now is None:
            now = time.time()

        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM tasks
                WHERE state = ?
                   OR (state = ? AND (next_retry_at IS NULL OR next_retry_at <= ?))
                ORDER BY submitted_at ASC
                LIMIT 1
                """,
                (STATE_QUEUED, STATE_RETRYING, now),
            ).fetchone()
            if row is None:
                return None

            connection.execute(
                """
                UPDATE tasks
                SET state = ?, started_at = ?, next_retry_at = NULL
                WHERE id = ?
                """,
                (STATE_DOWNLOADING, now, row["id"]),
            )
            row = connection.execute(
                "SELECT * FROM tasks WHERE id = ?",
                (row["id"],),
            ).fetchone()

        return None if row is None else self._row_to_task(row)

    def recover_inflight_tasks(self, *, now: float | None = None) -> int:
        if now is None:
            now = time.time()

        with self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE tasks
                SET state = ?, next_retry_at = ?
                WHERE state = ?
                """,
                (STATE_RETRYING, now, STATE_DOWNLOADING),
            )
            return cursor.rowcount

    def update_task_state(
        self,
        task_id: int,
        state: str,
        *,
        started_at: float | None | object = _UNSET,
        finished_at: float | None | object = _UNSET,
        download_url: str | None | object = _UNSET,
        filename: str | None | object = _UNSET,
        title: str | None | object = _UNSET,
        last_error: str | None | object = _UNSET,
        proxy_generation_started: int | None | object = _UNSET,
        failover_attempts: int | object = _UNSET,
        attempted_node_fingerprints: list[str] | None | object = _UNSET,
        retry_count: int | object = _UNSET,
        max_retries: int | None | object = _UNSET,
        next_retry_at: float | None | object = _UNSET,
        retry_notice_sent_at: float | None | object = _UNSET,
        last_attempt_submitted_at: float | None | object = _UNSET,
    ) -> None:
        assignments = ["state = ?"]
        values: list[object] = [state]
        serialized_attempted_node_fingerprints = attempted_node_fingerprints
        if attempted_node_fingerprints is not _UNSET:
            if attempted_node_fingerprints is None:
                serialized_attempted_node_fingerprints = None
            else:
                serialized_attempted_node_fingerprints = json.dumps(attempted_node_fingerprints)
        field_values = (
            ("started_at", started_at),
            ("finished_at", finished_at),
            ("download_url", download_url),
            ("filename", filename),
            ("title", title),
            ("last_error", last_error),
            ("proxy_generation_started", proxy_generation_started),
            ("failover_attempts", failover_attempts),
            ("attempted_node_fingerprints", serialized_attempted_node_fingerprints),
            ("retry_count", retry_count),
            ("max_retries", max_retries),
            ("next_retry_at", next_retry_at),
            ("retry_notice_sent_at", retry_notice_sent_at),
            ("last_attempt_submitted_at", last_attempt_submitted_at),
        )
        for column_name, value in field_values:
            if value is not _UNSET:
                assignments.append(f"{column_name} = ?")
                values.append(value)
        values.append(task_id)
        with self._connect() as connection:
            connection.execute(
                f"UPDATE tasks SET {', '.join(assignments)} WHERE id = ?",
                values,
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
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            download_url=row["download_url"],
            filename=row["filename"],
            title=row["title"],
            last_error=row["last_error"],
            notified_at=row["notified_at"],
            proxy_generation_started=row["proxy_generation_started"],
            failover_attempts=row["failover_attempts"],
            attempted_node_fingerprints=TaskStore._decode_attempted_node_fingerprints(
                row["attempted_node_fingerprints"]
            ),
            retry_count=row["retry_count"],
            max_retries=row["max_retries"],
            next_retry_at=row["next_retry_at"],
            retry_notice_sent_at=row["retry_notice_sent_at"],
            last_attempt_submitted_at=row["last_attempt_submitted_at"],
        )

    @staticmethod
    def _decode_attempted_node_fingerprints(raw_value: str | None) -> list[str]:
        if not raw_value:
            return []
        try:
            payload = json.loads(raw_value)
        except (TypeError, ValueError, json.JSONDecodeError):
            return []
        if not isinstance(payload, list):
            return []
        return [str(item) for item in payload]
