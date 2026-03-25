from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping


@dataclass(slots=True)
class BotConfig:
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    metube_base_url: str
    metube_auth_header_name: str | None
    metube_auth_header_value: str | None
    public_host_url: str | None
    public_host_audio_url: str | None
    sqlite_path: str
    poll_interval_seconds: int
    task_timeout_seconds: int
    dedupe_window_seconds: int


def load_config(env: Mapping[str, str]) -> BotConfig:
    required = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID", "METUBE_BASE_URL")
    missing = [key for key in required if not env.get(key)]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required environment variables: {joined}")

    auth_header_name = env.get("METUBE_AUTH_HEADER_NAME") or None
    auth_header_value = env.get("METUBE_AUTH_HEADER_VALUE") or None
    if bool(auth_header_name) != bool(auth_header_value):
        raise ValueError(
            "METUBE_AUTH_HEADER_NAME and METUBE_AUTH_HEADER_VALUE must be provided together"
        )

    poll_interval_seconds = int(env.get("BOT_POLL_INTERVAL_SECONDS", "15"))
    task_timeout_seconds = int(env.get("BOT_TASK_TIMEOUT_SECONDS", "21600"))
    dedupe_window_seconds = int(env.get("BOT_DEDUPE_WINDOW_SECONDS", "300"))

    if poll_interval_seconds <= 0:
        raise ValueError("BOT_POLL_INTERVAL_SECONDS must be greater than 0")
    if task_timeout_seconds <= 0:
        raise ValueError("BOT_TASK_TIMEOUT_SECONDS must be greater than 0")
    if dedupe_window_seconds <= 0:
        raise ValueError("BOT_DEDUPE_WINDOW_SECONDS must be greater than 0")

    return BotConfig(
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"],
        telegram_allowed_chat_id=int(env["TELEGRAM_ALLOWED_CHAT_ID"]),
        metube_base_url=env["METUBE_BASE_URL"].rstrip("/"),
        metube_auth_header_name=auth_header_name,
        metube_auth_header_value=auth_header_value,
        public_host_url=(env.get("PUBLIC_HOST_URL") or "").rstrip("/") or None,
        public_host_audio_url=(env.get("PUBLIC_HOST_AUDIO_URL") or "").rstrip("/") or None,
        sqlite_path=env.get("BOT_SQLITE_PATH", "bot/tasks.sqlite3"),
        poll_interval_seconds=poll_interval_seconds,
        task_timeout_seconds=task_timeout_seconds,
        dedupe_window_seconds=dedupe_window_seconds,
    )
