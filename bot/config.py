from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping


@dataclass(slots=True)
class BotConfig:
    telegram_bot_token: str
    telegram_allowed_chat_id: int
    metube_base_url: str | None = None
    metube_auth_header_name: str | None = None
    metube_auth_header_value: str | None = None
    public_host_url: str | None = None
    public_host_audio_url: str | None = None
    sqlite_path: str = "bot/tasks.sqlite3"
    http_timeout_seconds: int = 30
    poll_interval_seconds: float = 15.0
    task_timeout_seconds: int = 21600
    dedupe_window_seconds: int = 300
    public_download_base_url: str | None = None
    download_dir: str = "downloads"
    state_dir: str = "bot"
    http_bind: str = "0.0.0.0"
    http_port: int = 8081


def load_config(env: Mapping[str, str]) -> BotConfig:
    missing = [
        key
        for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_ALLOWED_CHAT_ID")
        if not env.get(key)
    ]
    if missing:
        joined = ", ".join(missing)
        raise ValueError(f"Missing required environment variables: {joined}")

    public_download_base_url = (env.get("PUBLIC_DOWNLOAD_BASE_URL") or "").rstrip("/") or None
    metube_base_url = (env.get("METUBE_BASE_URL") or "").rstrip("/") or None
    if public_download_base_url is None and metube_base_url is None:
        raise ValueError(
            "Missing required environment variables: PUBLIC_DOWNLOAD_BASE_URL or METUBE_BASE_URL"
        )

    auth_header_name = env.get("METUBE_AUTH_HEADER_NAME") or None
    auth_header_value = env.get("METUBE_AUTH_HEADER_VALUE") or None
    if bool(auth_header_name) != bool(auth_header_value):
        raise ValueError(
            "METUBE_AUTH_HEADER_NAME and METUBE_AUTH_HEADER_VALUE must be provided together"
        )

    state_dir_value = env.get("STATE_DIR")
    sqlite_path_value = env.get("BOT_SQLITE_PATH")
    if sqlite_path_value:
        sqlite_path = sqlite_path_value
        state_dir = state_dir_value or str(Path(sqlite_path_value).parent)
    else:
        state_dir = state_dir_value or "bot"
        sqlite_path = str(Path(state_dir) / "tasks.sqlite3")

    http_timeout_seconds = int(
        env.get("HTTP_TIMEOUT_SECONDS")
        or env.get("BOT_HTTP_TIMEOUT_SECONDS")
        or "30"
    )
    poll_interval_seconds = float(
        env.get("POLL_INTERVAL_SECONDS")
        or env.get("BOT_POLL_INTERVAL_SECONDS")
        or "15"
    )
    task_timeout_seconds = int(
        env.get("TASK_TIMEOUT_SECONDS")
        or env.get("BOT_TASK_TIMEOUT_SECONDS")
        or "21600"
    )
    dedupe_window_seconds = int(env.get("BOT_DEDUPE_WINDOW_SECONDS", "300"))
    http_port = int(env.get("HTTP_PORT", "8081"))
    http_bind = env.get("HTTP_BIND", "0.0.0.0")

    if http_timeout_seconds <= 0:
        raise ValueError("HTTP_TIMEOUT_SECONDS must be greater than 0")
    if poll_interval_seconds <= 0:
        raise ValueError("POLL_INTERVAL_SECONDS must be greater than 0")
    if task_timeout_seconds <= 0:
        raise ValueError("TASK_TIMEOUT_SECONDS must be greater than 0")
    if dedupe_window_seconds <= 0:
        raise ValueError("BOT_DEDUPE_WINDOW_SECONDS must be greater than 0")
    if http_port <= 0:
        raise ValueError("HTTP_PORT must be greater than 0")
    if not http_bind:
        raise ValueError("HTTP_BIND must not be empty")

    return BotConfig(
        telegram_bot_token=env["TELEGRAM_BOT_TOKEN"],
        telegram_allowed_chat_id=int(env["TELEGRAM_ALLOWED_CHAT_ID"]),
        metube_base_url=metube_base_url,
        metube_auth_header_name=auth_header_name,
        metube_auth_header_value=auth_header_value,
        public_host_url=(env.get("PUBLIC_HOST_URL") or "").rstrip("/") or None,
        public_host_audio_url=(env.get("PUBLIC_HOST_AUDIO_URL") or "").rstrip("/") or None,
        sqlite_path=sqlite_path,
        http_timeout_seconds=http_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        task_timeout_seconds=task_timeout_seconds,
        dedupe_window_seconds=dedupe_window_seconds,
        public_download_base_url=public_download_base_url,
        download_dir=env.get("DOWNLOAD_DIR", "downloads"),
        state_dir=state_dir,
        http_bind=http_bind,
        http_port=http_port,
    )
