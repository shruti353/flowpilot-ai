"""GENERATE_PLAN node: ask the LLM provider for a structured (but not yet
validated) plan.
"""

import app.services.ollama_service as ollama_service
from app.agent.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)


async def generate_plan(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    logger.info("node started: GENERATE_PLAN", extra={"request_id": state["request_id"]})

    provider = ollama_service.get_llm_provider()
    try:
        raw_plan = await provider.generate_json(state["user_text"])
    except ollama_service.OllamaServiceError as exc:
        logger.error(
            "LLM generation failed: %s", exc, extra={"request_id": state["request_id"]}
        )
        state["errors"].append(str(exc))
        state["status"] = "llm_error"
        return state

    state["raw_plan"] = raw_plan
    state["intent"] = raw_plan.get("intent") if isinstance(raw_plan, dict) else None
    state["status"] = "plan_generated"

    logger.info("node completed: GENERATE_PLAN", extra={"request_id": state["request_id"]})
    return state
