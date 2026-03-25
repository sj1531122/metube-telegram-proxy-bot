from unittest import TestCase

from bot.main import main


class MainModuleTests(TestCase):
    def test_main_is_callable(self):
        self.assertTrue(callable(main))
