import pytest

import app.services.ollama_service as ollama_service


@pytest.fixture(autouse=True)
def reset_llm_provider_override():
    """Ensure no test's fake provider leaks into the next test."""
    yield
    ollama_service.set_llm_provider(None)


class FakeProvider:
    """Test double for LLMProvider: returns a canned value or raises."""

    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def generate_json(self, user_text: str):
        if self._error is not None:
            raise self._error
        return self._result
