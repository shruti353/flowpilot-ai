"""Regression test for env-file loading: Settings must always load the
project-root .env, regardless of the process's current working directory
(e.g. uvicorn launched from backend/, or pytest launched from the repo
root) - see app/core/config.py's _REPO_ROOT_ENV_FILE.
"""

from pathlib import Path

from app.core.config import Settings

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND_DIR = REPO_ROOT / "backend"


def test_settings_loads_root_env_when_cwd_is_backend_dir(monkeypatch):
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_CALENDAR_WEBHOOK_PATH", raising=False)
    monkeypatch.chdir(BACKEND_DIR)

    settings = Settings()

    assert settings.n8n_base_url == "http://localhost:5678"
    assert settings.n8n_calendar_webhook_path == "/webhook/flowpilot-calendar"
    assert settings.resolved_n8n_calendar_webhook_url == "http://localhost:5678/webhook/flowpilot-calendar"


def test_settings_loads_root_env_when_cwd_is_unrelated_directory(tmp_path, monkeypatch):
    monkeypatch.delenv("N8N_BASE_URL", raising=False)
    monkeypatch.delenv("N8N_CALENDAR_WEBHOOK_PATH", raising=False)
    monkeypatch.chdir(tmp_path)

    settings = Settings()

    assert settings.resolved_n8n_calendar_webhook_url == "http://localhost:5678/webhook/flowpilot-calendar"
