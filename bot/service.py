from __future__ import annotations

import logging
import time

from bot.config import BotConfig
from bot.errors import TelegramApiError
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_TIMEOUT, BotTask
from bot.url_utils import extract_urls, normalize_source_url

logger = logging.getLogger(__name__)
_REJECTED = object()


class BotService:
    def __init__(self, *, config: BotConfig, store, telegram_api, metube_client=None, time_fn=None):
        self.config = config
        self.store = store
        self.telegram_api = telegram_api
        self.metube_client = metube_client
        self.time_fn = time_fn or time.time

    async def handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        user_id = self._admitted_user_id(message)
        if user_id is _REJECTED:
            return

        text = message.get("text") or ""
        urls = extract_urls(text)
        if not urls:
            return

        message_id = message.get("message_id", 0)
        for url in urls:
            source_url = normalize_source_url(url)
            duplicate = self.store.find_recent_duplicate(
                user_id=user_id,
                source_url=source_url,
                within_seconds=self.config.dedupe_window_seconds,
            )
            if duplicate is not None:
                await self._send_message(chat_id, f"Already queued: {source_url}")
                continue

            self.store.create_task(
                chat_id=chat_id,
                telegram_message_id=message_id,
                source_url=source_url,
                user_id=user_id,
            )
            await self._send_message(chat_id, f"Queued: {source_url}")

    def _multi_user_mode(self) -> bool:
        return bool(self.config.telegram_allowed_user_ids)

    def _admitted_user_id(self, message: dict) -> int | None | object:
        chat = message.get("chat") or {}
        chat_id = chat.get("id")
        if self._multi_user_mode():
            if chat.get("type") != "private":
                return _REJECTED
            user_id = (message.get("from") or {}).get("id")
            if user_id not in self.config.telegram_allowed_user_ids:
                return _REJECTED
            return user_id

        if chat_id != self.config.telegram_allowed_chat_id:
            return _REJECTED
        return None

    async def poll_once(self) -> None:
        self._mark_timed_out_tasks()
        for task in self.store.list_pending_notifications():
            await self._notify_terminal_task(task)

    def _mark_timed_out_tasks(self) -> None:
        now = self.time_fn()
        for task in self.store.list_unfinished_tasks():
            if self._is_timed_out(task, now=now):
                self.store.update_task_state(
                    task.id,
                    STATE_TIMEOUT,
                    last_error="task timed out",
                    finished_at=now,
                )
                logger.warning("task timed out for task_id=%s url=%s", task.id, task.source_url)

    def _is_timed_out(self, task: BotTask, *, now: float) -> bool:
        return (now - task.submitted_at) > self.config.task_timeout_seconds

    async def _notify_terminal_task(self, task: BotTask) -> None:
        if task.state == STATE_FINISHED:
            title = task.title or task.source_url
            if not task.download_url:
                self.store.update_task_state(
                    task.id,
                    STATE_FAILED,
                    title=title,
                    last_error="missing download url",
                )
                return
            await self._send_message(task.chat_id, f"Finished: {title}\n{task.download_url}")
            self.store.mark_notified(task.id)
            logger.info("task finished for task_id=%s title=%s", task.id, title)
            return

        if task.state == STATE_FAILED:
            title = task.title or task.source_url
            reason = task.last_error or "download failed"
            await self._send_message(task.chat_id, f"Failed: {title}\nReason: {reason}")
            self.store.mark_notified(task.id)
            logger.warning("task failed for task_id=%s title=%s: %s", task.id, title, reason)
            return

        if task.state == STATE_TIMEOUT:
            await self._send_message(task.chat_id, f"Timeout: {task.source_url}")
            self.store.mark_notified(task.id)

    async def _send_message(self, chat_id: int, text: str) -> dict:
        try:
            return await self.telegram_api.send_message(chat_id, text)
        except TelegramApiError as exc:
            logger.warning("telegram send failed for chat_id=%s: %s", chat_id, exc)
            raise
