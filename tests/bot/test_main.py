import runpy
from pathlib import Path
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import patch

from bot.errors import TelegramApiError
from bot.main import main, run_iteration


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
    def __init__(self, fail_on_update_id=None):
        self.fail_on_update_id = fail_on_update_id
        self.handled = []
        self.poll_count = 0

    async def handle_update(self, update):
        self.handled.append(update["update_id"])
        if update["update_id"] == self.fail_on_update_id:
            raise TelegramApiError("send failed")

    async def poll_once(self):
        self.poll_count += 1


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

        offset = await run_iteration(service=service, telegram_api=telegram_api, offset=55)

        self.assertEqual(offset, 55)
        self.assertEqual(service.handled, [])
        self.assertEqual(service.poll_count, 1)

    async def test_run_iteration_skips_failed_update_and_continues(self):
        telegram_api = FakeTelegramApi(updates=[{"update_id": 101}, {"update_id": 102}])
        service = FakeService(fail_on_update_id=101)

        offset = await run_iteration(service=service, telegram_api=telegram_api, offset=None)

        self.assertEqual(offset, 103)
        self.assertEqual(service.handled, [101, 102])
        self.assertEqual(service.poll_count, 1)
