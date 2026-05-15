# cli/client/http.py
"""
Base HTTP client for the ude CLI.

All API clients inherit from UDEHttpClient. It handles:
  - Host/port resolution from UDEConfig
  - Project token injection via X-UDE-Project header
  - Consistent timeout behaviour
  - Retry logic on transient failures (503, 502, connection errors)
  - Mapping HTTP error responses to typed UDEError subclasses
  - JSON request/response serialisation

Never import httpx directly in command files — always go through
a typed client (cli/client/pipeline.py etc.) that inherits from here.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from cli.core.config import UDEConfig
from cli.core.errors import APIError, StackNotRunningError

_RETRYABLE_STATUSES = {502, 503, 504}
_MAX_RETRIES   = 3
_RETRY_BACKOFF = [0.5, 1.0, 2.0]


class UDEHttpClient:

    def __init__(self, config: UDEConfig) -> None:
        self._config   = config
        self._base_url = config.api_base_url
        self._timeout  = config.timeout

    # ── Public HTTP verbs ─────────────────────────────────────────────────────

    def get(self, path: str, params: dict | None = None) -> Any:
        return self._request("GET", path, params=params)

    def post(self, path: str, body: dict | None = None) -> Any:
        return self._request("POST", path, json=body)

    def patch(self, path: str, body: dict | None = None) -> Any:
        return self._request("PATCH", path, json=body)

    def delete(self, path: str) -> Any:
        return self._request("DELETE", path)

    # ── Streaming ─────────────────────────────────────────────────────────────

    def stream_lines(self, path: str, params: dict | None = None):
        """Generator yielding decoded lines from a streaming HTTP response."""
        url = f"{self._base_url}{path}"
        try:
            with httpx.stream(
                "GET",
                url,
                params=params,
                timeout=None,
                headers=self._headers(),
            ) as resp:
                resp.raise_for_status()
                for line in resp.iter_lines():
                    if line:
                        yield line
        except httpx.ConnectError:
            raise StackNotRunningError(self._config.host, self._config.port)

    # ── Internal ──────────────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        path: str,
        params: dict | None = None,
        json:   dict | None = None,
    ) -> Any:
        url = f"{self._base_url}{path}"

        for attempt, backoff in enumerate(_RETRY_BACKOFF):
            try:
                resp = httpx.request(
                    method,
                    url,
                    params=params,
                    json=json,
                    timeout=self._timeout,
                    headers=self._headers(),
                    follow_redirects=True,
                )

                if resp.status_code in _RETRYABLE_STATUSES and attempt < _MAX_RETRIES - 1:
                    time.sleep(backoff)
                    continue

                if resp.status_code >= 400:
                    detail = _extract_detail(resp)
                    raise APIError(resp.status_code, detail)

                if resp.content:
                    return resp.json()
                return {}

            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(backoff)
                    continue
                raise StackNotRunningError(
                    self._config.host, self._config.port
                ) from exc

        raise StackNotRunningError(self._config.host, self._config.port)

    def _headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   "ude-cli/2.3.0",
        }
        # Inject project token on every request — scopes all API operations
        if self._config.project_token:
            headers["X-UDE-Project"] = self._config.project_token
        return headers


def _extract_detail(resp: httpx.Response) -> str:
    try:
        body   = resp.json()
        detail = body.get("detail", "")
        if isinstance(detail, list):
            return "; ".join(d.get("msg", str(d)) for d in detail)
        return str(detail) or resp.text
    except Exception:
        return resp.text or f"HTTP {resp.status_code}"