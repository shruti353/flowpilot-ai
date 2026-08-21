"""UNDERSTAND_REQUEST node: normalize input and prepare state for planning.

No LLM call here - request-level validation already happened in the
Pydantic request model, so this node only trims whitespace and short-circuits
if a previous node already recorded a fatal error.
"""

from app.agent.state import AgentState
from app.core.logging import get_logger

logger = get_logger(__name__)


def understand_request(state: AgentState) -> AgentState:
    if state.get("errors"):
        return state

    logger.info("node started: UNDERSTAND_REQUEST", extra={"request_id": state["request_id"]})

    text = state.get("user_text", "").strip()
    if not text:
        state["errors"].append("user_text must not be empty")
        state["status"] = "failed"
        return state

    state["user_text"] = text
    state["status"] = "understood"

    logger.info("node completed: UNDERSTAND_REQUEST", extra={"request_id": state["request_id"]})
    return state
