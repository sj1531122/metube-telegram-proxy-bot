from __future__ import annotations

import asyncio
import time
from urllib.parse import quote

from app.proxy_failover import classify_download_error
from bot.download_executor import run_download
from bot.models import STATE_FAILED, STATE_FINISHED, STATE_RETRYING, STATE_TIMEOUT

SAME_NODE_RETRY_DELAYS = (10.0, 30.0, 60.0)
MAX_DISTINCT_NODE_ATTEMPTS = 3
LOCAL_PROXY_URL = "http://127.0.0.1:10809"


class DownloadWorker:
    def __init__(
        self,
        *,
        config,
        store,
        download_runner=run_download,
        proxy_runtime=None,
        time_fn=None,
        sleep_fn=asyncio.sleep,
    ):
        self.config = config
        self.store = store
        self.download_runner = download_runner
        self.proxy_runtime = proxy_runtime
        self.time_fn = time_fn or time.time
        self.sleep_fn = sleep_fn
        self._loop_task: asyncio.Task[None] | None = None
        self._stopping = False

    async def start(self) -> None:
        if self._loop_task is not None and not self._loop_task.done():
            return
        self._stopping = False
        self._loop_task = asyncio.create_task(self._run_loop())

    async def stop(self) -> None:
        self._stopping = True
        if self._loop_task is not None:
            await self._loop_task

    async def run_one_task(self) -> bool:
        now = float(self.time_fn())
        task = self.store.claim_next_runnable_task(now=now)
        if task is None:
            return False

        attempted_fingerprints = list(task.attempted_node_fingerprints)
        active_fingerprint = self._active_node_fingerprint()
        proxy_generation_started = None
        if self.proxy_runtime is not None:
            proxy_generation_started = self.proxy_runtime.current_generation
            if active_fingerprint and active_fingerprint not in attempted_fingerprints:
                attempted_fingerprints.append(active_fingerprint)

        self.store.update_task_state(
            task.id,
            task.state,
            proxy_generation_started=proxy_generation_started,
            attempted_node_fingerprints=attempted_fingerprints,
        )

        result = await self.download_runner(
            source_url=task.source_url,
            download_dir=self.config.download_dir,
            proxy_url=self._proxy_url(),
            cookies_file=self.config.cookies_file,
            extra_args=self.config.ytdlp_extra_args,
            timeout_seconds=self.config.task_timeout_seconds,
        )

        finished_at = float(self.time_fn())
        if result.ok:
            self.store.update_task_state(
                task.id,
                STATE_FINISHED,
                title=result.title,
                filename=result.filename,
                download_url=self._build_download_url(result.filename),
                last_error=None,
                finished_at=finished_at,
                attempted_node_fingerprints=attempted_fingerprints,
                proxy_generation_started=proxy_generation_started,
            )
            return True

        error_text = result.error_text or "download failed"
        if result.timed_out:
            self.store.update_task_state(
                task.id,
                STATE_TIMEOUT,
                last_error=error_text,
                finished_at=finished_at,
                attempted_node_fingerprints=attempted_fingerprints,
                proxy_generation_started=proxy_generation_started,
            )
            return True

        decision = classify_download_error(
            error_text,
            proxy_enabled=self.proxy_runtime is not None,
        )
        if decision.action == "retry_same_node":
            self._retry_same_node(
                task_id=task.id,
                retry_count=task.retry_count,
                error_text=error_text,
                attempted_fingerprints=attempted_fingerprints,
                proxy_generation_started=proxy_generation_started,
                now=finished_at,
            )
            return True

        if decision.action == "switch_node" and self.proxy_runtime is not None:
            if len(attempted_fingerprints) >= MAX_DISTINCT_NODE_ATTEMPTS:
                self.store.update_task_state(
                    task.id,
                    STATE_FAILED,
                    last_error=error_text,
                    finished_at=finished_at,
                    attempted_node_fingerprints=attempted_fingerprints,
                    proxy_generation_started=proxy_generation_started,
                )
                return True

            if (
                task.proxy_generation_started is not None
                and task.proxy_generation_started != self.proxy_runtime.current_generation
            ):
                self.store.update_task_state(
                    task.id,
                    STATE_RETRYING,
                    next_retry_at=finished_at,
                    last_error=error_text,
                    attempted_node_fingerprints=attempted_fingerprints,
                    proxy_generation_started=self.proxy_runtime.current_generation,
                )
                return True

            self.proxy_runtime.mark_current_node_failed(reason=decision.reason, now=finished_at)
            switched = await self.proxy_runtime.switch_to_next_node(reason=decision.reason)
            if switched:
                self.store.update_task_state(
                    task.id,
                    STATE_RETRYING,
                    next_retry_at=finished_at,
                    last_error=error_text,
                    failover_attempts=task.failover_attempts + 1,
                    attempted_node_fingerprints=attempted_fingerprints,
                    proxy_generation_started=self.proxy_runtime.current_generation,
                )
                return True

        self.store.update_task_state(
            task.id,
            STATE_FAILED,
            last_error=error_text,
            finished_at=finished_at,
            attempted_node_fingerprints=attempted_fingerprints,
            proxy_generation_started=proxy_generation_started,
        )
        return True

    async def _run_loop(self) -> None:
        while not self._stopping:
            worked = await self.run_one_task()
            if worked:
                continue
            await self.sleep_fn(float(self.config.poll_interval_seconds))

    def _retry_same_node(
        self,
        *,
        task_id: int,
        retry_count: int,
        error_text: str,
        attempted_fingerprints: list[str],
        proxy_generation_started: int | None,
        now: float,
    ) -> None:
        if retry_count >= len(SAME_NODE_RETRY_DELAYS):
            self.store.update_task_state(
                task_id,
                STATE_FAILED,
                last_error=error_text,
                finished_at=now,
                attempted_node_fingerprints=attempted_fingerprints,
                proxy_generation_started=proxy_generation_started,
            )
            return

        self.store.update_task_state(
            task_id,
            STATE_RETRYING,
            retry_count=retry_count + 1,
            next_retry_at=now + SAME_NODE_RETRY_DELAYS[retry_count],
            last_error=error_text,
            attempted_node_fingerprints=attempted_fingerprints,
            proxy_generation_started=proxy_generation_started,
        )

    def _proxy_url(self) -> str | None:
        if self.proxy_runtime is None:
            return None
        return LOCAL_PROXY_URL

    def _active_node_fingerprint(self) -> str | None:
        if self.proxy_runtime is None:
            return None
        return self.proxy_runtime.active_node_fingerprint

    def _build_download_url(self, filename: str | None) -> str | None:
        if not filename:
            return None
        return f"{self.config.public_download_base_url.rstrip('/')}/{quote(filename, safe='/')}"
