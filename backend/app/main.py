"""FlowPilot AI backend.

Week 1: Text -> FastAPI -> LangGraph -> Ollama -> structured plan ->
Pydantic validation -> JSON response.

Week 2 adds human-in-the-loop plan persistence and approval: a validated
plan is stored in memory and sits "awaiting_approval" until a human
approves, rejects, or cancels it. No tool is ever actually executed in
either phase.
"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.agent import router as agent_router
from app.api.v1.plans import router as plans_router
from app.core.config import get_settings
from app.core.logging import configure_logging, get_logger

settings = get_settings()
configure_logging(settings.log_level)
logger = get_logger(__name__)

app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description=(
        "Converts natural-language text into a validated, structured "
        "execution plan, then holds it for explicit human approval. "
        "No tool is ever actually executed."
    ),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(agent_router, prefix=settings.api_v1_prefix)
app.include_router(plans_router, prefix=settings.api_v1_prefix)


@app.get("/health", tags=["health"])
async def health() -> dict:
    return {"status": "ok", "service": settings.app_name}
