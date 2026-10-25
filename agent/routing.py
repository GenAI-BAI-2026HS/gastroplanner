"""Alle Verzweigungen des Graphen. Owner: Person B (B4).

Jede Funktion ist rein: State rein, Name des nächsten Nodes raus. Kein LLM, kein I/O.
Damit beantwortet diese Datei die Frage «Wo verzweigt der Graph?» und lässt sich mit
einfachen Dicts testen (tests/test_routing.py).
"""
MAX_RETRIES = 2          # Plausibilität: bis 2× wiederholen (Projektplan B4)
MAX_REVISIONS = 3        # «anpassen»-Runden, danach Eskalation
MAX_RUECKFRAGEN = 3      # Rückfragen beim Anlass, danach Eskalation


def route_after_guard(state) -> str:
    return "supervisor" if state.get("allowed") else "reject"


def route_intent(state) -> str:
    return {"wochenplanung": "context", "anlass": "anlass",
            "regelfrage": "regelfrage"}.get(state.get("intent"), "reject")


def route_after_anlass(state) -> str:
    if state.get("escalation"):
        return "escalate"
    if state.get("pending_event"):
        return "anlass_rueckfrage"
    return "context"


def route_after_step(state) -> str:
    """Gemeinsam für context und forecast: Fehler → Mensch."""
    return "escalate" if state.get("escalation") else "ok"


def route_after_plausibility(state) -> str:
    if state["plausibility"]["ok"]:
        return "staffing"
    return "context" if state["retries"] <= MAX_RETRIES else "escalate"


def route_after_approval(state) -> str:
    decision = state.get("decision")
    if decision == "freigeben":
        return "commit"
    if decision == "anpassen":
        return "memory" if state.get("revisions", 0) < MAX_REVISIONS else "escalate"
    return "end"


def route_after_memory(state) -> str:
    return "approval" if state.get("hinweis") else "staffing"
