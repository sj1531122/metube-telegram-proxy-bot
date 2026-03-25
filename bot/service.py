from __future__ import annotations

import logging
import time
from urllib.parse import quote

from bot.config import BotConfig
from bot.errors import MeTubeApiError, TelegramApiError
from bot.models import (
    STATE_FAILED,
    STATE_FINISHED,
    STATE_QUEUED,
    STATE_SUBMITTED,
    STATE_TIMEOUT,
    BotTask,
)
from bot.url_utils import extract_urls

AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav", "flac"}
logger = logging.getLogger(__name__)


class BotService:
    def __init__(self, *, config: BotConfig, store, metube_client, telegram_api, time_fn=None):
        self.config = config
        self.store = store
        self.metube_client = metube_client
        self.telegram_api = telegram_api
        self.time_fn = time_fn or time.time

    async def handle_update(self, update: dict) -> None:
        message = update.get("message") or {}
        chat_id = (message.get("chat") or {}).get("id")
        if chat_id != self.config.telegram_allowed_chat_id:
            return

        text = message.get("text") or ""
        urls = extract_urls(text)
        if not urls:
            return

        message_id = message.get("message_id", 0)
        for url in urls:
            duplicate = self.store.find_recent_duplicate(
                source_url=url,
                within_seconds=self.config.dedupe_window_seconds,
            )
            if duplicate is not None:
                await self._send_message(chat_id, f"Already queued: {url}")
                continue

            task_id = self.store.create_task(
                chat_id=chat_id,
                telegram_message_id=message_id,
                source_url=url,
            )
            try:
                result = await self.metube_client.add_download(url)
            except MeTubeApiError as exc:
                reason = str(exc) or "submission failed"
                self.store.update_task_state(task_id, STATE_FAILED, last_error=reason)
                self.store.mark_notified(task_id)
                logger.warning("download submission failed for url=%s: %s", url, reason)
                await self._send_message(chat_id, f"Failed: {url}\nReason: {reason}")
                continue
            if result.get("status") == "ok":
                self.store.update_task_state(task_id, STATE_SUBMITTED)
                await self._send_message(chat_id, f"Queued: {url}")
            else:
                reason = result.get("msg") or "submission failed"
                self.store.update_task_state(task_id, STATE_FAILED, last_error=reason)
                self.store.mark_notified(task_id)
                logger.warning("download submission failed for url=%s: %s", url, reason)
                await self._send_message(chat_id, f"Failed: {url}\nReason: {reason}")

    async def poll_once(self) -> None:
        try:
            history = await self.metube_client.fetch_history()
        except MeTubeApiError as exc:
            logger.warning("MeTube history fetch failed: %s", exc)
            return
        for task in self.store.list_unfinished_tasks():
            if self._is_timed_out(task):
                self.store.update_task_state(task.id, STATE_TIMEOUT, last_error="task timed out")
                self.store.mark_notified(task.id)
                logger.warning("task timed out for task_id=%s url=%s", task.id, task.source_url)
                await self._send_message(task.chat_id, f"Timeout: {task.source_url}")
                continue

            done_entry = self._find_entry(history.get("done", []), task.source_url)
            if done_entry is not None:
                await self._handle_done_entry(task, done_entry)
                continue

            queued_entry = self._find_entry(history.get("queue", []), task.source_url)
            pending_entry = self._find_entry(history.get("pending", []), task.source_url)
            if queued_entry is not None or pending_entry is not None:
                self.store.update_task_state(task.id, STATE_QUEUED)

    def _is_timed_out(self, task: BotTask) -> bool:
        return (self.time_fn() - task.submitted_at) > self.config.task_timeout_seconds

    @staticmethod
    def _find_entry(entries: list[dict], source_url: str) -> dict | None:
        for entry in entries:
            if entry.get("url") == source_url:
                return entry
        return None

    async def _handle_done_entry(self, task: BotTask, entry: dict) -> None:
        title = entry.get("title") or task.source_url
        if entry.get("status") == "finished":
            filename = entry.get("filename")
            if not filename:
                reason = "completed_without_filename"
                self.store.update_task_state(task.id, STATE_FAILED, title=title, last_error=reason)
                self.store.mark_notified(task.id)
                await self._send_message(task.chat_id, f"Failed: {title}\nReason: {reason}")
                return

            download_url = self._build_download_url(entry, filename)
            self.store.update_task_state(
                task.id,
                STATE_FINISHED,
                title=title,
                filename=filename,
                download_url=download_url,
            )
            self.store.mark_notified(task.id)
            logger.info("task finished for task_id=%s title=%s", task.id, title)
            await self._send_message(task.chat_id, f"Finished: {title}\n{download_url}")
            return

        reason = entry.get("msg") or entry.get("error") or "download failed"
        self.store.update_task_state(task.id, STATE_FAILED, title=title, last_error=reason)
        self.store.mark_notified(task.id)
        logger.warning("task failed for task_id=%s title=%s: %s", task.id, title, reason)
        await self._send_message(task.chat_id, f"Failed: {title}\nReason: {reason}")

    def _build_download_url(self, entry: dict, filename: str) -> str:
        encoded_filename = quote(filename, safe="/")
        if self._is_audio_entry(entry):
            base_url = self.config.public_host_audio_url or f"{self.config.metube_base_url}/audio_download"
        else:
            base_url = self.config.public_host_url or f"{self.config.metube_base_url}/download"
        return f"{base_url.rstrip('/')}/{encoded_filename}"

    @staticmethod
    def _is_audio_entry(entry: dict) -> bool:
        if entry.get("quality") == "audio":
            return True
        return (entry.get("format") or "").lower() in AUDIO_FORMATS

    async def _send_message(self, chat_id: int, text: str) -> dict:
        try:
            return await self.telegram_api.send_message(chat_id, text)
        except TelegramApiError as exc:
            logger.warning("telegram send failed for chat_id=%s: %s", chat_id, exc)
            raise
