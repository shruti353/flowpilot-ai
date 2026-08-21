"""Explicit, deterministic LangGraph workflow:

START -> UNDERSTAND_REQUEST -> GENERATE_PLAN -> VALIDATE_PLAN -> END

No conditional branching and no loops - each node checks `state["errors"]`
itself and no-ops if an earlier node already failed, which keeps the graph
topology linear and easy to reason about.
"""

from langgraph.graph import END, START, StateGraph

from app.agent.nodes.plan import generate_plan
from app.agent.nodes.understand import understand_request
from app.agent.nodes.validate import validate_plan
from app.agent.state import AgentState, initial_state


def build_agent_graph():
    graph = StateGraph(AgentState)

    graph.add_node("UNDERSTAND_REQUEST", understand_request)
    graph.add_node("GENERATE_PLAN", generate_plan)
    graph.add_node("VALIDATE_PLAN", validate_plan)

    graph.add_edge(START, "UNDERSTAND_REQUEST")
    graph.add_edge("UNDERSTAND_REQUEST", "GENERATE_PLAN")
    graph.add_edge("GENERATE_PLAN", "VALIDATE_PLAN")
    graph.add_edge("VALIDATE_PLAN", END)

    return graph.compile()


_compiled_graph = build_agent_graph()


async def run_agent_graph(user_text: str, request_id: str) -> AgentState:
    result = await _compiled_graph.ainvoke(initial_state(request_id, user_text))
    return result
