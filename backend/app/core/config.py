"""Application configuration loaded from environment variables / .env file."""

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve the project-root .env by this file's own location rather than the
# process's current working directory - config.py lives at
# backend/app/core/config.py, so the repo root is three parents up. This
# makes env loading independent of where uvicorn/pytest/etc. is launched
# from, and avoids ever needing a second .env under backend/.
_REPO_ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
_REPO_ROOT_CONTACTS_DB_FILE = Path(__file__).resolve().parents[3] / "flowpilot_contacts.db"


class Settings(BaseSettings):
    """Runtime configuration for the FlowPilot AI backend."""

    app_name: str = "FlowPilot AI"
    api_v1_prefix: str = "/api/v1"

    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:3b"
    ollama_timeout_seconds: float = 90.0

    log_level: str = "INFO"

    # Comma-separated list of origins allowed to call this API from a
    # browser (local frontend dev). Kept as a plain string so it's trivial
    # to set from a .env file; use cors_allowed_origins_list to consume it.
    cors_allowed_origins: str = "http://localhost:5173,http://127.0.0.1:5173"

    # --- Week 3: execution ------------------------------------------------
    # IANA timezone used to resolve relative datetime expressions
    # ("tomorrow at 3 PM") at execution time. Never inferred from the LLM.
    flowpilot_timezone: str = "Asia/Kolkata"
    # Used as the calendar event's end time when the plan didn't specify one.
    default_event_duration_minutes: int = 60

    # Either set n8n_calendar_webhook_url directly, or set n8n_base_url and
    # let it combine with n8n_calendar_webhook_path. Leaving both unset
    # means execution is not configured - actions fail with a structured
    # N8N_NOT_CONFIGURED error rather than silently doing nothing.
    n8n_base_url: str | None = None
    n8n_calendar_webhook_path: str = "/webhook/flowpilot-calendar"
    n8n_calendar_webhook_url: str | None = None
    n8n_timeout_seconds: float = 30.0

    # --- Week 5: contacts/teams -------------------------------------------
    # SQLite file backing persistent Contacts/Teams storage - survives a
    # backend restart, unlike the in-memory PlanRepository. Never committed
    # (see .gitignore) - it holds real user contact data.
    contacts_db_path: str = str(_REPO_ROOT_CONTACTS_DB_FILE)

    model_config = SettingsConfigDict(
        env_file=_REPO_ROOT_ENV_FILE,
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]

    @property
    def resolved_n8n_calendar_webhook_url(self) -> str | None:
        if self.n8n_calendar_webhook_url:
            return self.n8n_calendar_webhook_url
        if self.n8n_base_url:
            return self.n8n_base_url.rstrip("/") + "/" + self.n8n_calendar_webhook_path.lstrip("/")
        return None


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()
