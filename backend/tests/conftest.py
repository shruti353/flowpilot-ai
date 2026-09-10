import pytest

import app.execution.n8n_client as n8n_client
import app.services.ollama_service as ollama_service
import app.repositories.contacts_repository as contacts_repository
from app.repositories.contacts_repository import ContactsRepository
from app.repositories.plan_repository import get_plan_repository


@pytest.fixture(autouse=True)
def reset_llm_provider_override():
    """Ensure no test's fake provider leaks into the next test."""
    yield
    ollama_service.set_llm_provider(None)


@pytest.fixture(autouse=True)
def reset_plan_repository():
    """Ensure the in-memory plan store starts empty for every test."""
    get_plan_repository().clear()
    yield
    get_plan_repository().clear()


@pytest.fixture(autouse=True)
def reset_n8n_client_override():
    """Ensure no test's fake n8n client leaks into the next test."""
    yield
    n8n_client.set_n8n_client(None)


@pytest.fixture(autouse=True)
def reset_contacts_repository():
    """Give every test a fresh, empty, in-memory Contacts/Teams store -
    never the real file-backed one from app/core/config.py's default."""
    contacts_repository.set_contacts_repository(ContactsRepository(":memory:"))
    yield
    contacts_repository.set_contacts_repository(None)


class FakeProvider:
    """Test double for LLMProvider: returns a canned value or raises."""

    def __init__(self, result=None, error: Exception | None = None):
        self._result = result
        self._error = error

    async def generate_json(self, user_text: str):
        if self._error is not None:
            raise self._error
        return self._result


class FakeN8nClient:
    """Test double for N8nClient: returns a canned body or raises, and
    records every call so tests can assert it was/wasn't reached."""

    def __init__(self, result: dict | None = None, error: Exception | None = None):
        self._result = result if result is not None else {"success": True}
        self._error = error
        self.calls: list[dict] = []

    async def post(self, url: str, payload: dict, timeout_seconds: float):
        self.calls.append({"url": url, "payload": payload, "timeout_seconds": timeout_seconds})
        if self._error is not None:
            raise self._error
        return self._result
