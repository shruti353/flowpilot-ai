"""FlowPilot AI backend - Week 1 vertical slice.

Text -> FastAPI -> LangGraph -> Ollama -> structured plan -> Pydantic
validation -> JSON response. No real external actions happen in this phase.
"""

from fastapi import FastAPI

from app.api.v1.agent import router as agent_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description=(
        "Week 1 vertical slice: converts natural-language text into a "
        "validated, structured, human-approvable execution plan. No tool "
        "is ever actually executed."
    ),
)

app.include_router(agent_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
