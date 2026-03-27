from __future__ import annotations

import asyncio
import json
from typing import Callable
from urllib import error, parse, request

from bot.errors import TelegramApiError


class TelegramApi:
    def __init__(
        self,
        *,
        bot_token: str,
        timeout_seconds: int = 30,
        get_json: Callable[[str, dict], dict] | None = None,
        post_json: Callable[[str, dict], dict] | None = None,
    ):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self.timeout_seconds = timeout_seconds
        self._get_json = get_json
        self._post_json = post_json

    async def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        endpoint = f"{self.base_url}/getUpdates"
        request_timeout_seconds = max(self.timeout_seconds, timeout + 5)
        try:
            if self._get_json is not None:
                response = self._get_json(endpoint, params)
            else:
                response = await asyncio.to_thread(
                    self._default_get_json,
                    endpoint,
                    params,
                    request_timeout_seconds,
                )
        except TelegramApiError:
            raise
        except (error.HTTPError, error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise TelegramApiError(f"telegram getUpdates request failed: {exc}") from exc
        if not isinstance(response, dict):
            raise TelegramApiError("invalid getUpdates response from Telegram")
        self._ensure_ok(response)
        return response.get("result", [])

    async def send_message(self, chat_id: int, text: str) -> dict:
        endpoint = f"{self.base_url}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            if self._post_json is not None:
                response = self._post_json(endpoint, payload)
            else:
                response = await asyncio.to_thread(
                    self._default_post_json,
                    endpoint,
                    payload,
                    self.timeout_seconds,
                )
        except TelegramApiError:
            raise
        except (error.HTTPError, error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise TelegramApiError(f"telegram sendMessage request failed: {exc}") from exc
        if not isinstance(response, dict):
            raise TelegramApiError("invalid sendMessage response from Telegram")
        self._ensure_ok(response)
        return response

    @staticmethod
    def _ensure_ok(response: dict) -> None:
        if not response.get("ok", True):
            raise TelegramApiError(response.get("description") or "telegram api request failed")

    @staticmethod
    def _default_get_json(url: str, params: dict, timeout_seconds: int) -> dict:
        full_url = f"{url}?{parse.urlencode(params)}"
        http_request = request.Request(full_url, method="GET")
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_post_json(url: str, payload: dict, timeout_seconds: int) -> dict:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
