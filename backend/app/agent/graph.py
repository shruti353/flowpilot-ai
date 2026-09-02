"""Explicit, deterministic LangGraph workflow:

START -> UNDERSTAND_REQUEST -> GENERATE_PLAN -> INFER_TITLES -> VALIDATE_PLAN -> END

No conditional branching and no loops - each node checks `state["errors"]`
itself and no-ops if an earlier node already failed, which keeps the graph
topology linear and easy to reason about. INFER_TITLES runs after the LLM
plan is generated and before it is validated/persisted: it patches
state["raw_plan"] in place with deterministically-inferred calendar event
titles, it never replaces or regenerates the LLM's plan.
"""

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.infer_titles import infer_titles
from app.agent.nodes.plan import generate_plan
from app.agent.nodes.understand import understand_request
from app.agent.nodes.validate import validate_plan
from app.agent.state import AgentState, initial_state


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("UNDERSTAND_REQUEST", understand_request)
    graph.add_node("GENERATE_PLAN", generate_plan)
    graph.add_node("INFER_TITLES", infer_titles)
    graph.add_node("VALIDATE_PLAN", validate_plan)

    graph.add_edge(START, "UNDERSTAND_REQUEST")
    graph.add_edge("UNDERSTAND_REQUEST", "GENERATE_PLAN")
    graph.add_edge("GENERATE_PLAN", "INFER_TITLES")
    graph.add_edge("INFER_TITLES", "VALIDATE_PLAN")
    graph.add_edge("VALIDATE_PLAN", END)

    return graph.compile()


_compiled_graph = build_agent_graph()


async def run_agent_graph(user_text: str, request_id: str) -> AgentState:
    result = await _compiled_graph.ainvoke(initial_state(request_id, user_text))
    return result
