"""Explicit, deterministic LangGraph workflow:

START -> UNDERSTAND_REQUEST -> GENERATE_PLAN -> INFER_TITLES -> ENRICH_DATETIME
    -> RESOLVE_RECIPIENTS -> FILTER_OPTIONAL_FIELDS -> VALIDATE_PLAN -> END

No conditional branching and no loops - each node checks `state["errors"]`
itself and no-ops if an earlier node already failed, which keeps the graph
topology linear and easy to reason about. INFER_TITLES, ENRICH_DATETIME,
RESOLVE_RECIPIENTS, and FILTER_OPTIONAL_FIELDS all run after the LLM plan
is generated and before it is validated/persisted: they patch
state["raw_plan"] in place (titles, then resolved datetimes, then email
recipient resolution, then dropping genuinely-optional missing-information
entries) and never replace or regenerate the LLM's plan.
"""

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.enrich_datetime import enrich_datetime
from app.agent.nodes.filter_optional_fields import filter_optional_fields
from app.agent.nodes.infer_titles import infer_titles
from app.agent.nodes.plan import generate_plan
from app.agent.nodes.resolve_recipients import resolve_recipients
from app.agent.nodes.understand import understand_request
from app.agent.nodes.validate import validate_plan
from app.agent.state import AgentState, initial_state


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("UNDERSTAND_REQUEST", understand_request)
    graph.add_node("GENERATE_PLAN", generate_plan)
    graph.add_node("INFER_TITLES", infer_titles)
    graph.add_node("ENRICH_DATETIME", enrich_datetime)
    graph.add_node("RESOLVE_RECIPIENTS", resolve_recipients)
    graph.add_node("FILTER_OPTIONAL_FIELDS", filter_optional_fields)
    graph.add_node("VALIDATE_PLAN", validate_plan)

    graph.add_edge(START, "UNDERSTAND_REQUEST")
    graph.add_edge("UNDERSTAND_REQUEST", "GENERATE_PLAN")
    graph.add_edge("GENERATE_PLAN", "INFER_TITLES")
    graph.add_edge("INFER_TITLES", "ENRICH_DATETIME")
    graph.add_edge("ENRICH_DATETIME", "RESOLVE_RECIPIENTS")
    graph.add_edge("RESOLVE_RECIPIENTS", "FILTER_OPTIONAL_FIELDS")
    graph.add_edge("FILTER_OPTIONAL_FIELDS", "VALIDATE_PLAN")
    graph.add_edge("VALIDATE_PLAN", END)

    return graph.compile()


_compiled_graph = build_agent_graph()


async def run_agent_graph(user_text: str, request_id: str) -> AgentState:
    result = await _compiled_graph.ainvoke(initial_state(request_id, user_text))
    return result
