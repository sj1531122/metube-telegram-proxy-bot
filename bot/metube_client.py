from __future__ import annotations

import asyncio
import json
from typing import Callable
from urllib import error, request

from bot.errors import MeTubeApiError


class MeTubeClient:
    def __init__(
        self,
        *,
        base_url: str,
        auth_header_name: str | None = None,
        auth_header_value: str | None = None,
        timeout_seconds: int = 30,
        quality: str = "best",
        media_format: str = "any",
        post_json: Callable[[str, dict, dict[str, str]], dict] | None = None,
        get_json: Callable[[str, dict[str, str]], dict] | None = None,
    ):
        self.base_url = base_url.rstrip("/")
        self.auth_header_name = auth_header_name
        self.auth_header_value = auth_header_value
        self.timeout_seconds = timeout_seconds
        self.quality = quality
        self.media_format = media_format
        self._post_json = post_json
        self._get_json = get_json

    async def add_download(self, url: str) -> dict:
        payload = {
            "url": url,
            "quality": self.quality,
            "format": self.media_format,
            "auto_start": True,
        }
        headers = self._build_headers()
        endpoint = f"{self.base_url}/add"
        try:
            if self._post_json is not None:
                response = self._post_json(endpoint, payload, headers)
            else:
                response = await asyncio.to_thread(
                    self._default_post_json,
                    endpoint,
                    payload,
                    headers,
                    self.timeout_seconds,
                )
        except MeTubeApiError:
            raise
        except (error.HTTPError, error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise MeTubeApiError(f"MeTube add request failed: {exc}") from exc
        if not isinstance(response, dict):
            raise MeTubeApiError("invalid add response from MeTube")
        return response

    async def fetch_history(self) -> dict:
        headers = self._build_headers()
        endpoint = f"{self.base_url}/history"
        try:
            if self._get_json is not None:
                data = self._get_json(endpoint, headers)
            else:
                data = await asyncio.to_thread(
                    self._default_get_json,
                    endpoint,
                    headers,
                    self.timeout_seconds,
                )
        except MeTubeApiError:
            raise
        except (error.HTTPError, error.URLError, TimeoutError, OSError, json.JSONDecodeError) as exc:
            raise MeTubeApiError(f"MeTube history request failed: {exc}") from exc
        if not isinstance(data, dict):
            raise MeTubeApiError("invalid history response from MeTube")

        return {
            "queue": data.get("queue", []),
            "pending": data.get("pending", []),
            "done": data.get("done", []),
        }

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {}
        if self.auth_header_name and self.auth_header_value:
            headers[self.auth_header_name] = self.auth_header_value
        return headers

    @staticmethod
    def _default_post_json(
        url: str,
        payload: dict,
        headers: dict[str, str],
        timeout_seconds: int,
    ) -> dict:
        body = json.dumps(payload).encode("utf-8")
        request_headers = {"Content-Type": "application/json", **headers}
        http_request = request.Request(url, data=body, headers=request_headers, method="POST")
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))

    @staticmethod
    def _default_get_json(url: str, headers: dict[str, str], timeout_seconds: int) -> dict:
        http_request = request.Request(url, headers=headers, method="GET")
        with request.urlopen(http_request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
