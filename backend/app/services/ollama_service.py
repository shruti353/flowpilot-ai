"""LLM provider layer.

The agent graph only ever calls `get_llm_provider().generate_json(...)`. It
does not know or care that Ollama is behind it, so a different provider can
be dropped in later (e.g. a hosted API) without touching `app/agent`.
"""

import json
from typing import Any, Protocol

import httpx

from app.core.config import get_settings
from app.prompts.planner_prompt import SYSTEM_PROMPT


class OllamaServiceError(Exception):
    """Raised when the LLM cannot be reached or returns something unusable."""


class LLMProvider(Protocol):
    async def generate_json(self, user_text: str) -> Any:
        """Return the provider's response parsed as JSON (dict/list/etc.)."""
        ...


class OllamaProvider:
    """Talks to a local/remote Ollama server's /api/generate endpoint."""

    def __init__(self, base_url: str, model: str, timeout_seconds: float = 60.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._model = model
        self._timeout_seconds = timeout_seconds

    async def generate_json(self, user_text: str) -> Any:
        try:
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.post(
                    f"{self._base_url}/api/generate",
                    json={
                        "model": self._model,
                        "system": SYSTEM_PROMPT,
                        "prompt": user_text,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0},
                    },
                )
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise OllamaServiceError(
                f"Failed to reach Ollama at {self._base_url} (model={self._model}): {exc}"
            ) from exc

        payload = response.json()
        raw_text = payload.get("response", "")
        try:
            return json.loads(raw_text)
        except json.JSONDecodeError as exc:
            raise OllamaServiceError(f"Ollama returned a response that was not valid JSON: {exc}") from exc


_default_provider: LLMProvider | None = None
_provider_override: LLMProvider | None = None


def set_llm_provider(provider: LLMProvider | None) -> None:
    """Override the provider used by the agent graph. Pass None to reset.

    Intended for tests: `ollama_service.set_llm_provider(FakeProvider(...))`.
    """
    global _provider_override
    _provider_override = provider


def get_llm_provider() -> LLMProvider:
    if _provider_override is not None:
        return _provider_override

    global _default_provider
    if _default_provider is None:
        settings = get_settings()
        _default_provider = OllamaProvider(
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_seconds=settings.ollama_timeout_seconds,
        )
    return _default_provider
