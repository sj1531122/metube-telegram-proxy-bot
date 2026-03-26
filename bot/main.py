from __future__ import annotations

import asyncio
import logging
import os

from app.proxy_runtime import build_proxy_runtime
from bot.config import load_config
from bot.download_server import start_download_server
from bot.errors import BotIntegrationError
from bot.service import BotService
from bot.store import TaskStore
from bot.telegram_api import TelegramApi
from bot.worker import DownloadWorker

logger = logging.getLogger(__name__)


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


async def run_iteration(*, service: BotService, telegram_api: TelegramApi, offset: int | None) -> int | None:
    try:
        updates = await telegram_api.get_updates(offset=offset)
    except BotIntegrationError as exc:
        logger.warning("telegram polling failed: %s", exc)
        updates = []

    next_offset = offset
    for update in updates:
        try:
            await service.handle_update(update)
        except BotIntegrationError as exc:
            logger.warning(
                "update handling failed for update_id=%s: %s",
                update.get("update_id"),
                exc,
            )

        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1

    try:
        await service.poll_once()
    except BotIntegrationError as exc:
        logger.warning("history polling failed: %s", exc)

    return next_offset


async def run_bot() -> None:
    configure_logging()
    config = load_config(os.environ)
    logger.info(
        "bot starting with poll_interval_seconds=%s task_timeout_seconds=%s http_timeout_seconds=%s",
        config.poll_interval_seconds,
        config.task_timeout_seconds,
        config.http_timeout_seconds,
    )
    store = TaskStore(config.sqlite_path)
    store.recover_inflight_tasks()

    proxy_runtime = build_proxy_runtime(
        state_dir=config.state_dir,
        environ=dict(os.environ),
    )
    if proxy_runtime is not None:
        await proxy_runtime.initialize()

    server = await start_download_server(
        download_dir=config.download_dir,
        bind=config.http_bind,
        port=config.http_port,
    )
    telegram_api = TelegramApi(
        bot_token=config.telegram_bot_token,
        timeout_seconds=config.http_timeout_seconds,
    )
    service = BotService(
        config=config,
        store=store,
        telegram_api=telegram_api,
    )
    worker = DownloadWorker(
        config=config,
        store=store,
        proxy_runtime=proxy_runtime,
    )
    await worker.start()

    offset: int | None = None
    try:
        while True:
            offset = await run_iteration(service=service, telegram_api=telegram_api, offset=offset)
            await asyncio.sleep(config.poll_interval_seconds)
    finally:
        await worker.stop()
        await server.close()


def main() -> None:
    configure_logging()
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
