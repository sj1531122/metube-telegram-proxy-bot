from __future__ import annotations

import asyncio
import json
from typing import Callable
from urllib import parse, request


class TelegramApi:
    def __init__(
        self,
        *,
        bot_token: str,
        get_json: Callable[[str, dict], dict] | None = None,
        post_json: Callable[[str, dict], dict] | None = None,
    ):
        self.base_url = f"https://api.telegram.org/bot{bot_token}"
        self._get_json = get_json
        self._post_json = post_json

    async def get_updates(self, offset: int | None = None, timeout: int = 30) -> list[dict]:
        params = {"timeout": timeout}
        if offset is not None:
            params["offset"] = offset
        endpoint = f"{self.base_url}/getUpdates"
        if self._get_json is not None:
            response = self._get_json(endpoint, params)
        else:
            response = await asyncio.to_thread(self._default_get_json, endpoint, params)
        return response.get("result", [])

    async def send_message(self, chat_id: int, text: str) -> dict:
        endpoint = f"{self.base_url}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        if self._post_json is not None:
            return self._post_json(endpoint, payload)
        return await asyncio.to_thread(self._default_post_json, endpoint, payload)

    @staticmethod
    def _default_get_json(url: str, params: dict) -> dict:
        full_url = f"{url}?{parse.urlencode(params)}"
        http_request = request.Request(full_url, method="GET")
        with request.urlopen(http_request) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_post_json(url: str, payload: dict) -> dict:
        body = json.dumps(payload).encode("utf-8")
        http_request = request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with request.urlopen(http_request) as response:
            return json.loads(response.read().decode("utf-8"))
