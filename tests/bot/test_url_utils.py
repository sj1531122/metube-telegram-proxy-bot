from unittest import TestCase

from bot.url_utils import extract_urls, normalize_source_url


class ExtractUrlsTests(TestCase):
    def test_extract_urls_returns_all_http_links(self):
        text = "one https://a.example/x two https://b.example/y"

        self.assertEqual(
            extract_urls(text),
            ["https://a.example/x", "https://b.example/y"],
        )


class NormalizeSourceUrlTests(TestCase):
    def test_normalize_source_url_converts_youtu_be_link_to_canonical_watch_url(self):
        self.assertEqual(
            normalize_source_url("https://youtu.be/lNjhCIvNaI4?si=5ZD1RXPJXZ0j7l8b"),
            "https://www.youtube.com/watch?v=lNjhCIvNaI4",
        )

    def test_normalize_source_url_strips_youtube_tracking_params(self):
        self.assertEqual(
            normalize_source_url(
                "https://www.youtube.com/watch?v=Igcb9I9ocR8&si=FlBvRCdMGFnquxUB&t=12"
            ),
            "https://www.youtube.com/watch?v=Igcb9I9ocR8",
        )

    def test_extract_urls_strips_trailing_punctuation(self):
        text = "see https://a.example/x, and https://b.example/y.)"

        self.assertEqual(
            extract_urls(text),
            ["https://a.example/x", "https://b.example/y"],
        )
