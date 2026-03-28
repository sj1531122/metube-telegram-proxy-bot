from __future__ import annotations

import asyncio
from typing import NamedTuple


class FailoverDecision(NamedTuple):
    action: str
    reason: str


SWITCH_PATTERNS = (
    "connection refused",
    "network is unreachable",
    "connection reset by peer",
    "more expected",
    "proxy error",
    "socks",
    "tls handshake",
    "temporarily unavailable",
    "http error 429",
    "too many requests",
    "confirm you're not a bot",
    "unusual traffic",
    "rate limit",
    "request has been blocked",
)

PROXY_ONLY_SWITCH_PATTERNS = (
    "your ip address is blocked from accessing this post",
    "could not connect to server",
    "failed to connect to",
    "connection timed out after",
)

RETRY_SAME_NODE_PATTERNS = (
    "timed out",
    "temporary failure",
    "remote end closed connection",
    "connection aborted",
)

FINAL_FAIL_PATTERNS = (
    "private video",
    "video unavailable",
    "unsupported url",
    "members-only",
    "copyright",
    "login required",
    "age-restricted",
)


def classify_download_error(error_text: str, *, proxy_enabled: bool = False) -> FailoverDecision:
    normalized = (error_text or "").lower()

    for pattern in FINAL_FAIL_PATTERNS:
        if pattern in normalized:
            return FailoverDecision("final_fail", pattern)

    if proxy_enabled:
        if "[tiktok]" in normalized and "http error 403" in normalized:
            return FailoverDecision("switch_node", "tiktok http error 403")
        for pattern in PROXY_ONLY_SWITCH_PATTERNS:
            if pattern in normalized:
                return FailoverDecision("switch_node", pattern)

    for pattern in RETRY_SAME_NODE_PATTERNS:
        if pattern in normalized:
            return FailoverDecision("retry_same_node", pattern)

    for pattern in SWITCH_PATTERNS:
        if pattern in normalized:
            return FailoverDecision("switch_node", pattern)

    return FailoverDecision("final_fail", "unclassified")


class ProxyFailoverCoordinator:
    def __init__(self, *, runtime_manager):
        self.runtime_manager = runtime_manager
        self._lock = asyncio.Lock()

    async def handle_retryable_failure(self, *, task, error_text: str) -> str:
        decision = classify_download_error(error_text, proxy_enabled=True)
        if decision.action != "switch_node":
            return decision.action

        if task.proxy_generation_started != self.runtime_manager.current_generation:
            return "retry_current_generation"

        async with self._lock:
            if task.proxy_generation_started != self.runtime_manager.current_generation:
                return "retry_current_generation"

            switched = await self.runtime_manager.switch_to_next_node(reason=decision.reason)
            if not switched:
                return "final_fail"
            return "switched_node"
