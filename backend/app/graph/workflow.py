from langgraph.graph import END, START, StateGraph

from app.agents.arithmetic import arithmetic_node
from app.agents.blooms import blooms_node
from app.agents.ingestion import ingest_node
from app.agents.syllabus import syllabus_node
from app.agents.synthesizer import synthesizer_node
from app.graph.state import ScrutinyState


def build_graph():
    graph = StateGraph(ScrutinyState)
    graph.add_node("ingest", ingest_node)
    graph.add_node("arithmetic", arithmetic_node)
    graph.add_node("syllabus", syllabus_node)
    graph.add_node("blooms", blooms_node)
    graph.add_node("synthesizer", synthesizer_node)

    graph.add_edge(START, "ingest")
    graph.add_edge("ingest", "arithmetic")
    graph.add_edge("ingest", "syllabus")
    graph.add_edge("ingest", "blooms")
    graph.add_edge(["arithmetic", "syllabus", "blooms"], "synthesizer")
    graph.add_edge("synthesizer", END)
    return graph.compile()


_APP = None


def get_app():
    global _APP
    if _APP is None:
        _APP = build_graph()
    return _APP


def run_scrutiny(payload: dict) -> dict:
    return get_app().invoke(payload)
