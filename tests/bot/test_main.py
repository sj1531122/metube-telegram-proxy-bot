import asyncio
import runpy
from pathlib import Path
from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, MagicMock, patch

from bot.errors import TelegramApiError
from bot.main import main, run_bot, run_iteration


class MainModuleTests(TestCase):
    def test_main_is_callable(self):
        self.assertTrue(callable(main))

    def test_running_module_as_script_invokes_main(self):
        calls = []

        def fake_run(coro):
            calls.append(coro)
            coro.close()

        with patch("asyncio.run", fake_run):
            module_path = Path(__file__).resolve().parents[2] / "bot" / "main.py"
            runpy.run_path(str(module_path), run_name="__main__")

        self.assertEqual(len(calls), 1)


class FakeTelegramApi:
    def __init__(self, updates=None, exc=None):
        self.updates = updates or []
        self.exc = exc
        self.offsets = []

    async def get_updates(self, offset=None, timeout=30):
        self.offsets.append((offset, timeout))
        if self.exc is not None:
            raise self.exc
        return self.updates


class FakeService:
    def __init__(self, fail_on_update_id=None, poll_exc=None):
        self.fail_on_update_id = fail_on_update_id
        self.poll_exc = poll_exc
        self.handled = []
        self.poll_count = 0

    async def handle_update(self, update):
        self.handled.append(update["update_id"])
        if update["update_id"] == self.fail_on_update_id:
            raise TelegramApiError("send failed")

    async def poll_once(self):
        self.poll_count += 1
        if self.poll_exc is not None:
            raise self.poll_exc


class RunIterationTests(IsolatedAsyncioTestCase):
    async def test_run_iteration_advances_offset_and_polls(self):
        telegram_api = FakeTelegramApi(updates=[{"update_id": 101}, {"update_id": 102}])
        service = FakeService()

        offset = await run_iteration(service=service, telegram_api=telegram_api, offset=55)

        self.assertEqual(offset, 103)
        self.assertEqual(service.handled, [101, 102])
        self.assertEqual(service.poll_count, 1)

    async def test_run_iteration_still_polls_when_get_updates_fails(self):
        telegram_api = FakeTelegramApi(exc=TelegramApiError("bad token"))
        service = FakeService()

        with self.assertLogs("bot.main", "WARNING") as logs:
            offset = await run_iteration(service=service, telegram_api=telegram_api, offset=55)

        self.assertEqual(offset, 55)
        self.assertEqual(service.handled, [])
        self.assertEqual(service.poll_count, 1)
        self.assertTrue(any("telegram polling failed" in entry for entry in logs.output))

    async def test_run_iteration_skips_failed_update_and_continues(self):
        telegram_api = FakeTelegramApi(updates=[{"update_id": 101}, {"update_id": 102}])
        service = FakeService(fail_on_update_id=101)

        with self.assertLogs("bot.main", "WARNING") as logs:
            offset = await run_iteration(service=service, telegram_api=telegram_api, offset=None)

        self.assertEqual(offset, 103)
        self.assertEqual(service.handled, [101, 102])
        self.assertEqual(service.poll_count, 1)
        self.assertTrue(any("update handling failed" in entry for entry in logs.output))

    async def test_run_iteration_logs_poll_once_failure(self):
        telegram_api = FakeTelegramApi(updates=[])
        service = FakeService(poll_exc=TelegramApiError("history unavailable"))

        with self.assertLogs("bot.main", "WARNING") as logs:
            offset = await run_iteration(service=service, telegram_api=telegram_api, offset=55)

        self.assertEqual(offset, 55)
        self.assertEqual(service.poll_count, 1)
        self.assertTrue(any("history polling failed" in entry for entry in logs.output))


class RunBotTests(IsolatedAsyncioTestCase):
    async def test_run_bot_initializes_proxy_worker_and_file_server(self):
        config = SimpleNamespace(
            telegram_bot_token="token",
            telegram_allowed_chat_id=42,
            sqlite_path="state/tasks.sqlite3",
            state_dir="state",
            download_dir="downloads",
            http_bind="0.0.0.0",
            http_port=8081,
            http_timeout_seconds=30,
            poll_interval_seconds=1.0,
            task_timeout_seconds=600,
            dedupe_window_seconds=300,
            public_download_base_url="https://downloads.example.com/download",
        )
        store = MagicMock()
        proxy_runtime = SimpleNamespace(initialize=AsyncMock())
        server = SimpleNamespace(close=AsyncMock())
        worker = SimpleNamespace(start=AsyncMock(), stop=AsyncMock())

        with (
            patch("bot.main.load_config", return_value=config),
            patch("bot.main.TaskStore", return_value=store),
            patch("bot.main.TelegramApi"),
            patch("bot.main.BotService"),
            patch("bot.main.build_proxy_runtime", return_value=proxy_runtime),
            patch("bot.main.start_download_server", AsyncMock(return_value=server)),
            patch("bot.main.DownloadWorker", return_value=worker),
            patch("bot.main.run_iteration", AsyncMock(side_effect=asyncio.CancelledError)),
        ):
            with self.assertRaises(asyncio.CancelledError):
                await run_bot()

        store.recover_inflight_tasks.assert_called_once()
        proxy_runtime.initialize.assert_awaited_once()
        worker.start.assert_awaited_once()
        worker.stop.assert_awaited_once()
        server.close.assert_awaited_once()
