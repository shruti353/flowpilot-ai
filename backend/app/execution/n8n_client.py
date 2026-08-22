"""HTTP client for calling n8n webhooks.

Isolated from the adapter logic the same way `ollama_service.py` isolates
the LLM provider: production code talks to a real n8n server over HTTP,
tests swap in a fake via `set_n8n_client` so no test needs a live n8n
instance. This module never sees Google credentials - those live only in
n8n's own credential store.
"""

from typing import Any, Protocol

import httpx


class N8nWebhookError(Exception):
    """Raised for any n8n call that didn't come back as a usable response
    - unreachable, timed out, non-2xx, or not valid JSON."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class N8nClient(Protocol):
    async def post(self, url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        ...


class HttpxN8nClient:
    """Default N8nClient backed by a real HTTP call."""

    async def post(self, url: str, payload: dict[str, Any], timeout_seconds: float) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=timeout_seconds) as client:
                response = await client.post(url, json=payload)
        except httpx.TimeoutException as exc:
            raise N8nWebhookError(
                "N8N_TIMEOUT", "The n8n workflow did not respond in time."
            ) from exc
        except httpx.HTTPError as exc:
            raise N8nWebhookError(
                "N8N_UNREACHABLE", f"Could not reach the n8n webhook at {url}: {exc}"
            ) from exc

        if response.status_code >= 400:
            raise N8nWebhookError(
                "N8N_HTTP_ERROR", f"n8n webhook returned HTTP {response.status_code}."
            )

        try:
            body = response.json()
        except ValueError as exc:
            raise N8nWebhookError(
                "N8N_INVALID_RESPONSE", "n8n webhook returned a response that was not valid JSON."
            ) from exc

        if not isinstance(body, dict):
            raise N8nWebhookError(
                "N8N_INVALID_RESPONSE", "n8n webhook returned a JSON response that was not an object."
            )
        return body


_default_client: N8nClient = HttpxN8nClient()
_client_override: N8nClient | None = None


def set_n8n_client(client: N8nClient | None) -> None:
    """Override the client used by every adapter. Pass None to reset.

    Intended for tests: `n8n_client.set_n8n_client(FakeN8nClient(...))`.
    """
    global _client_override
    _client_override = client


def get_n8n_client() -> N8nClient:
    return _client_override or _default_client
