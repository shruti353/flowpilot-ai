"""Tests for app/services/ollama_service.py's OllamaProvider.

Regression coverage for a reported connectivity bug: curl and Python's
urllib could both reach a local Ollama server at http://127.0.0.1:11434,
and get_settings() resolved the right URL/model, but OllamaProvider still
failed with "Failed to reach Ollama". Root cause: httpx.AsyncClient honors
HTTP_PROXY/HTTPS_PROXY/NO_PROXY-style environment variables by default,
which can route a local loopback call through a system proxy. The fix pins
`trust_env=False` on the client so this call is never affected by proxy
env vars - these tests assert the client is actually constructed that way,
and that error handling / JSON parsing behavior is otherwise unchanged.
"""

import httpx
import pytest

from app.services.ollama_service import OllamaProvider, OllamaServiceError


class _FakeResponse:
    def __init__(self, json_body: dict, status_error: Exception | None = None):
        self._json_body = json_body
        self._status_error = status_error

    def raise_for_status(self) -> None:
        if self._status_error is not None:
            raise self._status_error

    def json(self):
        return self._json_body


class _FakeAsyncClient:
    """Stands in for httpx.AsyncClient: records the kwargs it was
    constructed with (so tests can assert on them) and returns a canned
    response instead of making a real network call."""

    created_with: dict | None = None
    response: _FakeResponse | None = None
    raise_on_post: Exception | None = None

    def __init__(self, **kwargs) -> None:
        type(self).created_with = kwargs

    async def __aenter__(self) -> "_FakeAsyncClient":
        return self

    async def __aexit__(self, *exc_info) -> bool:
        return False

    async def post(self, url: str, json: dict):
        if type(self).raise_on_post is not None:
            raise type(self).raise_on_post
        return type(self).response


@pytest.fixture(autouse=True)
def _reset_fake_client():
    _FakeAsyncClient.created_with = None
    _FakeAsyncClient.response = None
    _FakeAsyncClient.raise_on_post = None
    yield
    _FakeAsyncClient.created_with = None
    _FakeAsyncClient.response = None
    _FakeAsyncClient.raise_on_post = None


@pytest.mark.asyncio
async def test_generate_json_creates_client_with_trust_env_false(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.response = _FakeResponse({"response": '{"ok": true}'})

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2:3b", timeout_seconds=5.0)
    result = await provider.generate_json("hello")

    assert result == {"ok": True}
    assert _FakeAsyncClient.created_with == {"timeout": 5.0, "trust_env": False}


@pytest.mark.asyncio
async def test_http_error_still_raises_ollama_service_error_with_reachability_message(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.raise_on_post = httpx.ConnectError("connection refused")

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2:3b", timeout_seconds=5.0)

    with pytest.raises(OllamaServiceError) as exc_info:
        await provider.generate_json("hello")

    assert "Failed to reach Ollama at http://127.0.0.1:11434" in str(exc_info.value)
    assert "llama3.2:3b" in str(exc_info.value)


@pytest.mark.asyncio
async def test_non_2xx_status_still_raises_ollama_service_error(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    request = httpx.Request("POST", "http://127.0.0.1:11434/api/generate")
    status_error = httpx.HTTPStatusError(
        "server error", request=request, response=httpx.Response(500, request=request)
    )
    _FakeAsyncClient.response = _FakeResponse({}, status_error=status_error)

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2:3b", timeout_seconds=5.0)

    with pytest.raises(OllamaServiceError):
        await provider.generate_json("hello")


@pytest.mark.asyncio
async def test_invalid_json_response_still_raises_ollama_service_error(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.response = _FakeResponse({"response": "not valid json"})

    provider = OllamaProvider(base_url="http://127.0.0.1:11434", model="llama3.2:3b", timeout_seconds=5.0)

    with pytest.raises(OllamaServiceError) as exc_info:
        await provider.generate_json("hello")

    assert "not valid JSON" in str(exc_info.value)


@pytest.mark.asyncio
async def test_base_url_trailing_slash_is_stripped_in_request_url(monkeypatch):
    monkeypatch.setattr(httpx, "AsyncClient", _FakeAsyncClient)
    _FakeAsyncClient.response = _FakeResponse({"response": "{}"})

    captured = {}

    async def post(self, url, json):
        captured["url"] = url
        return _FakeAsyncClient.response

    monkeypatch.setattr(_FakeAsyncClient, "post", post)

    provider = OllamaProvider(base_url="http://127.0.0.1:11434/", model="llama3.2:3b")
    await provider.generate_json("hello")

    assert captured["url"] == "http://127.0.0.1:11434/api/generate"
