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
    STATE_RETRYING,
    STATE_SUBMITTED,
    STATE_TIMEOUT,
    BotTask,
)
from bot.url_utils import extract_urls, normalize_source_url

AUDIO_FORMATS = {"mp3", "m4a", "opus", "wav", "flac"}
RETRY_DELAYS_SECONDS = (30, 60, 120, 300, 600)
DEFAULT_MAX_RETRIES = len(RETRY_DELAYS_SECONDS)
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
            source_url = normalize_source_url(url)
            duplicate = self.store.find_recent_duplicate(
                source_url=source_url,
                within_seconds=self.config.dedupe_window_seconds,
            )
            if duplicate is not None:
                await self._send_message(chat_id, f"Already queued: {source_url}")
                continue

            task_id = self.store.create_task(
                chat_id=chat_id,
                telegram_message_id=message_id,
                source_url=source_url,
            )
            try:
                result = await self.metube_client.add_download(source_url)
            except MeTubeApiError as exc:
                reason = str(exc) or "submission failed"
                self.store.update_task_state(task_id, STATE_FAILED, last_error=reason)
                self.store.mark_notified(task_id)
                logger.warning("download submission failed for url=%s: %s", source_url, reason)
                await self._send_message(chat_id, f"Failed: {source_url}\nReason: {reason}")
                continue
            if result.get("status") == "ok":
                self.store.update_task_state(
                    task_id,
                    STATE_SUBMITTED,
                    max_retries=DEFAULT_MAX_RETRIES,
                    last_attempt_submitted_at=self.time_fn(),
                )
                await self._send_message(chat_id, f"Queued: {source_url}")
            else:
                reason = result.get("msg") or "submission failed"
                self.store.update_task_state(task_id, STATE_FAILED, last_error=reason)
                self.store.mark_notified(task_id)
                logger.warning("download submission failed for url=%s: %s", source_url, reason)
                await self._send_message(chat_id, f"Failed: {source_url}\nReason: {reason}")

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

            if task.state == STATE_RETRYING:
                await self._process_retrying_task(task)
                continue

            done_entry = self._find_entry(history.get("done", []), task.source_url)
            if done_entry is not None:
                if self._is_stale_done_entry(task, done_entry):
                    continue
                await self._handle_done_entry(task, done_entry)
                continue

            queued_entry = self._find_entry(history.get("queue", []), task.source_url)
            pending_entry = self._find_entry(history.get("pending", []), task.source_url)
            if queued_entry is not None or pending_entry is not None:
                self.store.update_task_state(task.id, STATE_QUEUED)

    def _is_timed_out(self, task: BotTask) -> bool:
        return (self.time_fn() - task.submitted_at) > self.config.task_timeout_seconds

    @staticmethod
    def _task_max_retries(task: BotTask) -> int:
        return task.max_retries or DEFAULT_MAX_RETRIES

    @staticmethod
    def _is_stale_done_entry(task: BotTask, entry: dict) -> bool:
        if task.last_attempt_submitted_at is None:
            return False
        entry_timestamp = entry.get("timestamp")
        if entry_timestamp is None:
            return False
        return float(entry_timestamp) <= task.last_attempt_submitted_at

    @staticmethod
    def _find_entry(entries: list[dict], source_url: str) -> dict | None:
        normalized_source_url = normalize_source_url(source_url)
        for entry in entries:
            entry_url = entry.get("url")
            if isinstance(entry_url, str) and normalize_source_url(entry_url) == normalized_source_url:
                return entry
        return None

    async def _process_retrying_task(self, task: BotTask) -> None:
        next_retry_at = task.next_retry_at
        if next_retry_at is None or next_retry_at > self.time_fn():
            return

        retry_attempt = task.retry_count + 1
        max_retries = self._task_max_retries(task)
        try:
            result = await self.metube_client.add_download(task.source_url)
        except MeTubeApiError as exc:
            await self._handle_retry_submission_failure(
                task,
                retry_attempt=retry_attempt,
                max_retries=max_retries,
                reason=str(exc) or "submission failed",
            )
            return

        if result.get("status") != "ok":
            await self._handle_retry_submission_failure(
                task,
                retry_attempt=retry_attempt,
                max_retries=max_retries,
                reason=result.get("msg") or "submission failed",
            )
            return

        submitted_at = self.time_fn()
        self.store.update_task_state(
            task.id,
            STATE_SUBMITTED,
            retry_count=retry_attempt,
            max_retries=max_retries,
            next_retry_at=None,
            last_error=None,
            last_attempt_submitted_at=submitted_at,
        )
        try:
            await self.metube_client.clear_done_entries([normalize_source_url(task.source_url)])
        except MeTubeApiError as exc:
            logger.warning(
                "failed to clear stale done entry for task_id=%s url=%s: %s",
                task.id,
                task.source_url,
                exc,
            )

    async def _handle_retry_submission_failure(
        self,
        task: BotTask,
        *,
        retry_attempt: int,
        max_retries: int,
        reason: str,
    ) -> None:
        if retry_attempt >= max_retries:
            await self._finalize_failed_task(
                task,
                title=task.title or task.source_url,
                reason=reason,
            )
            return

        next_retry_at = self.time_fn() + RETRY_DELAYS_SECONDS[retry_attempt]
        self.store.update_task_state(
            task.id,
            STATE_RETRYING,
            retry_count=retry_attempt,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
            last_error=reason,
        )

    async def _handle_done_entry(self, task: BotTask, entry: dict) -> None:
        title = entry.get("title") or task.source_url
        if entry.get("status") == "finished":
            filename = entry.get("filename")
            if not filename:
                await self._finalize_failed_task(
                    task,
                    title=title,
                    reason="completed_without_filename",
                )
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
        await self._handle_failed_done_entry(task, title=title, reason=reason)

    async def _handle_failed_done_entry(self, task: BotTask, *, title: str, reason: str) -> None:
        max_retries = self._task_max_retries(task)
        if task.retry_count >= max_retries:
            await self._finalize_failed_task(task, title=title, reason=reason)
            return

        retry_notice_sent_at = task.retry_notice_sent_at
        if retry_notice_sent_at is None:
            retry_notice_sent_at = self.time_fn()
        next_retry_at = self.time_fn() + RETRY_DELAYS_SECONDS[task.retry_count]
        self.store.update_task_state(
            task.id,
            STATE_RETRYING,
            title=title,
            last_error=reason,
            max_retries=max_retries,
            next_retry_at=next_retry_at,
            retry_notice_sent_at=retry_notice_sent_at,
        )
        if task.retry_notice_sent_at is None:
            try:
                await self._send_message(
                    task.chat_id,
                    f"Failed once, retrying automatically (1/{max_retries}): {title}",
                )
            except TelegramApiError:
                logger.warning(
                    "retry notice send failed for task_id=%s url=%s",
                    task.id,
                    task.source_url,
                )

    async def _finalize_failed_task(self, task: BotTask, *, title: str, reason: str) -> None:
        self.store.update_task_state(
            task.id,
            STATE_FAILED,
            title=title,
            last_error=reason,
            next_retry_at=None,
        )
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
