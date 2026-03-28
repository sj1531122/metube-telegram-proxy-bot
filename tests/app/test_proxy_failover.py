import asyncio
from dataclasses import dataclass
import unittest

from app.proxy_failover import ProxyFailoverCoordinator, classify_download_error


@dataclass
class FakeTask:
    proxy_generation_started: int


class FakeRuntimeManager:
    def __init__(self, generation: int = 1):
        self.current_generation = generation
        self.switch_calls = 0

    async def switch_to_next_node(self, *, reason: str) -> bool:
        self.switch_calls += 1
        await asyncio.sleep(0)
        self.current_generation += 1
        return True


class ErrorClassificationTests(unittest.TestCase):
    def test_classify_transient_network_error_as_retry_same_node(self) -> None:
        decision = classify_download_error("Read timed out while requesting video metadata")

        self.assertEqual(decision.action, "retry_same_node")

    def test_classify_tiktok_blocked_ip_as_switch_node_when_proxy_enabled(self) -> None:
        decision = classify_download_error(
            "Your IP address is blocked from accessing this post",
            proxy_enabled=True,
        )

        self.assertEqual(decision.action, "switch_node")

    def test_classify_connect_timeout_as_switch_node_when_proxy_enabled(self) -> None:
        decision = classify_download_error(
            "Failed to connect to www.tiktok.com port 443 after 21009 ms: Could not connect to server",
            proxy_enabled=True,
        )

        self.assertEqual(decision.action, "switch_node")

    def test_classify_tiktok_403_as_switch_node_when_proxy_enabled(self) -> None:
        decision = classify_download_error(
            "ERROR: [TikTok] 7603427099658980622: Unable to download webpage: HTTP Error 403: Forbidden",
            proxy_enabled=True,
        )

        self.assertEqual(decision.action, "switch_node")

    def test_classify_tiktok_short_link_about_redirect_as_switch_node_when_proxy_enabled(self) -> None:
        decision = classify_download_error(
            "WARNING: [generic] Falling back on generic information extractor\n"
            "ERROR: Unsupported URL: https://www.tiktok.com/hk/about",
            proxy_enabled=True,
        )

        self.assertEqual(decision.action, "switch_node")

    def test_classify_proxy_connectivity_error_as_switch_node(self) -> None:
        decision = classify_download_error("connection reset by peer while connecting through proxy")

        self.assertEqual(decision.action, "switch_node")

    def test_classify_youtube_rate_limit_error_as_switch_node(self) -> None:
        decision = classify_download_error("HTTP Error 429: Too Many Requests")

        self.assertEqual(decision.action, "switch_node")

    def test_classify_partial_read_download_error_as_switch_node(self) -> None:
        decision = classify_download_error(
            "ERROR: [download] Got error: 1776819 bytes read, 8337267 more expected. Giving up after 10 retries"
        )

        self.assertEqual(decision.action, "switch_node")

    def test_classify_private_video_as_final_fail(self) -> None:
        decision = classify_download_error("Private video. Sign in if you've been granted access.")

        self.assertEqual(decision.action, "final_fail")


class ProxyFailoverCoordinatorTests(unittest.IsolatedAsyncioTestCase):
    async def test_concurrent_failures_only_trigger_one_node_switch(self) -> None:
        runtime = FakeRuntimeManager(generation=3)
        coordinator = ProxyFailoverCoordinator(runtime_manager=runtime)
        first_task = FakeTask(proxy_generation_started=3)
        second_task = FakeTask(proxy_generation_started=3)

        results = await asyncio.gather(
            coordinator.handle_retryable_failure(
                task=first_task,
                error_text="HTTP Error 429: Too Many Requests",
            ),
            coordinator.handle_retryable_failure(
                task=second_task,
                error_text="HTTP Error 429: Too Many Requests",
            ),
        )

        self.assertEqual(runtime.switch_calls, 1)
        self.assertEqual(sorted(results), ["retry_current_generation", "switched_node"])

    async def test_old_generation_failure_retries_without_triggering_another_switch(self) -> None:
        runtime = FakeRuntimeManager(generation=5)
        coordinator = ProxyFailoverCoordinator(runtime_manager=runtime)
        old_task = FakeTask(proxy_generation_started=4)

        result = await coordinator.handle_retryable_failure(
            task=old_task,
            error_text="connection refused",
        )

        self.assertEqual(result, "retry_current_generation")
        self.assertEqual(runtime.switch_calls, 0)


if __name__ == "__main__":
    unittest.main()
