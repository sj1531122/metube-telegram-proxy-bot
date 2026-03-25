from unittest import TestCase

from bot.url_utils import extract_urls


class ExtractUrlsTests(TestCase):
    def test_extract_urls_returns_all_http_links(self):
        text = "one https://a.example/x two https://b.example/y"

        self.assertEqual(
            extract_urls(text),
            ["https://a.example/x", "https://b.example/y"],
        )

    def test_extract_urls_strips_trailing_punctuation(self):
        text = "see https://a.example/x, and https://b.example/y.)"

        self.assertEqual(
            extract_urls(text),
            ["https://a.example/x", "https://b.example/y"],
        )
