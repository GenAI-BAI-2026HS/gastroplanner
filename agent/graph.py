"""Verdrahtung des Graphen. Owner: Person B (B4).

Hier stehen nur add_node, add_edge, add_conditional_edges und compile.
Die Logik steht in agent/nodes/, die Verzweigungen in agent/routing.py.

Bewusst Conditional Edges statt Command(goto=...): Die Ziele stehen explizit hier,
deshalb zeichnet draw_mermaid() alle Pfeile korrekt (Folien, README).
"""
from langgraph.graph import END, START, StateGraph

from agent import routing as r
from agent.nodes import anlass, approval, ende, explain, guard, memory, planung, regelfrage, supervisor
from agent.state import AgentState


def build_graph(checkpointer=None):
    b = StateGraph(AgentState)

    # --- Nodes -----------------------------------------------------------------
    b.add_node("guard", guard.guard)                       # LLM, Helin
    b.add_node("reject", guard.reject)
    b.add_node("supervisor", supervisor.supervisor)        # LLM, B
    b.add_node("regelfrage", regelfrage.regelfrage)        # LLM + RAG, Helin
    b.add_node("anlass", anlass.anlass)                    # LLM, B
    b.add_node("anlass_rueckfrage", anlass.anlass_rueckfrage)  # Mensch
    b.add_node("context", planung.context)                 # Tool (MCP)
    b.add_node("forecast", planung.forecast)               # Tool, A
    b.add_node("plausibility", planung.plausibility)       # Regeln, A
    b.add_node("staffing", planung.staffing)               # Tool, Helin
    b.add_node("explain", explain.explain)                 # LLM + RAG, B
    b.add_node("approval", approval.approval)              # Mensch, B
    b.add_node("memory", memory.memory)                    # LLM, Helin
    b.add_node("commit", approval.commit)                  # Tool, B
    b.add_node("escalate", ende.escalate)

    # --- Kanten ----------------------------------------------------------------
    b.add_edge(START, "guard")
    b.add_conditional_edges("guard", r.route_after_guard, ["supervisor", "reject"])
    b.add_conditional_edges("supervisor", r.route_intent,
                            ["context", "anlass", "regelfrage", "reject"])
    b.add_conditional_edges("anlass", r.route_after_anlass,
                            ["anlass_rueckfrage", "context", "escalate"])
    b.add_edge("anlass_rueckfrage", "anlass")
    b.add_conditional_edges("context", r.route_after_step,
                            {"ok": "forecast", "escalate": "escalate"})
    b.add_conditional_edges("forecast", r.route_after_step,
                            {"ok": "plausibility", "escalate": "escalate"})
    b.add_conditional_edges("plausibility", r.route_after_plausibility,
                            ["staffing", "context", "escalate"])
    b.add_edge("staffing", "explain")
    b.add_edge("explain", "approval")
    b.add_conditional_edges("approval", r.route_after_approval,
                            {"commit": "commit", "memory": "memory",
                             "escalate": "escalate", "end": END})
    b.add_conditional_edges("memory", r.route_after_memory, ["staffing", "approval"])
    for end_node in ("regelfrage", "reject", "escalate", "commit"):
        b.add_edge(end_node, END)

    return b.compile(checkpointer=checkpointer)


def sqlite_checkpointer():
    """Checkpointer für die App: überlebt Neustarts (Datei data/checkpoints.db)."""
    import sqlite3

    from langgraph.checkpoint.sqlite import SqliteSaver

    import config

    config.CHECKPOINT_DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    return SqliteSaver(sqlite3.connect(config.CHECKPOINT_DB_PATH, check_same_thread=False))
