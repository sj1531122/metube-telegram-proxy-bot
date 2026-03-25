from __future__ import annotations

import asyncio
import os

from bot.config import load_config
from bot.errors import BotIntegrationError
from bot.metube_client import MeTubeClient
from bot.service import BotService
from bot.store import TaskStore
from bot.telegram_api import TelegramApi


async def run_iteration(*, service: BotService, telegram_api: TelegramApi, offset: int | None) -> int | None:
    try:
        updates = await telegram_api.get_updates(offset=offset)
    except BotIntegrationError:
        updates = []

    next_offset = offset
    for update in updates:
        try:
            await service.handle_update(update)
        except BotIntegrationError:
            pass

        update_id = update.get("update_id")
        if isinstance(update_id, int):
            next_offset = update_id + 1

    try:
        await service.poll_once()
    except BotIntegrationError:
        pass

    return next_offset


async def run_bot() -> None:
    config = load_config(os.environ)
    store = TaskStore(config.sqlite_path)
    metube_client = MeTubeClient(
        base_url=config.metube_base_url,
        auth_header_name=config.metube_auth_header_name,
        auth_header_value=config.metube_auth_header_value,
    )
    telegram_api = TelegramApi(bot_token=config.telegram_bot_token)
    service = BotService(
        config=config,
        store=store,
        metube_client=metube_client,
        telegram_api=telegram_api,
    )

    offset: int | None = None
    while True:
        offset = await run_iteration(service=service, telegram_api=telegram_api, offset=offset)
        await asyncio.sleep(config.poll_interval_seconds)


def main() -> None:
    asyncio.run(run_bot())


if __name__ == "__main__":
    main()
