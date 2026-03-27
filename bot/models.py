from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

STATE_RECEIVED = "received"
STATE_SUBMITTED = "submitted"
STATE_QUEUED = "queued"
STATE_DOWNLOADING = "downloading"
STATE_RETRYING = "retrying"
STATE_FINISHED = "finished"
STATE_FAILED = "failed"
STATE_TIMEOUT = "timeout"


@dataclass(slots=True)
class BotTask:
    id: int
    chat_id: int
    telegram_message_id: int
    source_url: str
    state: str
    submitted_at: float
    user_id: int | None = None
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    download_url: Optional[str] = None
    filename: Optional[str] = None
    title: Optional[str] = None
    last_error: Optional[str] = None
    notified_at: Optional[float] = None
    proxy_generation_started: Optional[int] = None
    failover_attempts: int = 0
    attempted_node_fingerprints: list[str] = field(default_factory=list)
    retry_count: int = 0
    max_retries: Optional[int] = None
    next_retry_at: Optional[float] = None
    retry_notice_sent_at: Optional[float] = None
    last_attempt_submitted_at: Optional[float] = None
