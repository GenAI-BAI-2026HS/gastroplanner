"""LangGraph-State. Owner: Person B (B4). Alle Nodes lesen ihn.

Basis ist der Vertrag aus Projektplan Abschnitt 5. Die Felder unter «Erweiterung»
brauchen die Router, um zu entscheiden (siehe docs/architektur.md, Abschnitt State).
Faustregel (SW5): Im State stehen Rohdaten, kein formatierter Text.
"""
from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict):
    # --- Vertrag (Projektplan Abschnitt 5) ---------------------------------
    messages: Annotated[list, add_messages]
    intent: str | None             # wochenplanung | anlass | regelfrage | themenfremd
    start_date: str | None         # "YYYY-MM-DD"
    context: dict | None           # {"weather": [...], "calendar": [...]}
    forecast: list[dict] | None
    plausibility: dict | None      # {"ok": bool, "issues": [...]}
    retries: int
    events: list[dict]
    corrections: list[dict]
    staffing: list[dict] | None
    rule_sources: list[dict]
    explanation: str | None
    decision: str | None           # freigeben | anpassen | ablehnen

    # --- Erweiterung --------------------------------------------------------
    allowed: bool | None           # Ergebnis guard
    pending_event: dict | None     # unvollständiger Anlass während der Rückfrage
    anlass_versuche: int           # Anzahl Rückfragen beim Anlass
    feedback: str | None           # Freitext bei «anpassen»
    hinweis: str | None            # Rückfrage von memory, wird in approval angezeigt
    revisions: int                 # Anzahl «anpassen»-Runden
    escalation: str | None         # Grund für Eskalation an den Menschen
    plan_id: str | None            # gesetzt von commit


def initial_state(user_text: str) -> dict:
    """Startwerte für eine neue Anfrage.

    Mit Checkpointer bleibt der State eines Threads erhalten. Deshalb setzt jede neue
    Anfrage alle Laufzeitfelder zurück; nur der Nachrichtenverlauf wird ergänzt.
    """
    return {
        "messages": [("user", user_text)],
        "intent": None, "start_date": None, "context": None, "forecast": None,
        "plausibility": None, "retries": 0, "events": [], "corrections": [],
        "staffing": None, "rule_sources": [], "explanation": None, "decision": None,
        "allowed": None, "pending_event": None, "anlass_versuche": 0, "feedback": None,
        "hinweis": None, "revisions": 0, "escalation": None, "plan_id": None,
    }
