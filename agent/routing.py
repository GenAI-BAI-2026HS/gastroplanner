"""Alle Verzweigungen des Graphen. Aufgabe B4.

Jede Funktion ist rein: State rein, Name des nächsten Nodes raus. Kein LLM, kein I/O.
Damit beantwortet diese Datei die Frage «Wo verzweigt der Graph?» und lässt sich mit
einfachen Dicts testen (tests/test_routing.py).

Schleifen und ihre Grenzen:
- anlass ↔ anlass_rueckfrage: MAX_RUECKFRAGEN, danach escalate
- reservation ↔ reservation_rueckfrage: 2 × MAX_RUECKFRAGEN (6 Pflichtfelder), danach escalate
- reservation_aendern ↔ reservation_aendern_rueckfrage: MAX_RUECKFRAGEN, danach Ende ohne Änderung
- approval → korrektur → reservation → … → staffing → … → approval: zählt als «anpassen»-Runde
- approval → korrektur → staffing → … → approval: MAX_REVISIONS, danach escalate
- plausibility → fallback → plausibility: höchstens einmal (fallback_grund gesetzt)
- Wiederholung bei Datenfehlern: im Node, nicht im Graphen (planung.MAX_VERSUCHE)
- regelfrage ↔ regel_tools (Tool-Calling): regelfrage.MAX_SUCHEN, danach muss das LLM antworten
"""
from langgraph.prebuilt import tools_condition

MAX_REVISIONS = 3        # «anpassen»-Runden, danach Eskalation
MAX_RUECKFRAGEN = 3      # Rückfragen beim Anlass, danach Eskalation


def route_after_guard(state) -> str:
    return "supervisor" if state.get("allowed") else "reject"


def route_intent(state) -> str:
    return {"wochenplanung": "context", "anlass": "anlass", "reservation": "reservation",
            "reservation_aendern": "reservation_aendern",
            "regelfrage": "regelfrage"}.get(state.get("intent"), "reject")


def route_after_reservation_aendern(state) -> str:
    p = state.get("pending_aenderung")
    if p is None:
        return "end"                               # aufgegeben, nichts geändert
    return "reservation_aendern_bestaetigung" if p.get("vollstaendig") else "reservation_aendern_rueckfrage"


def route_after_reservation_aendern_bestaetigung(state) -> str:
    return "reservation_aendern_speichern" if state.get("decision") == "speichern" else "end"


def _ende_reservation(state) -> str:
    """Reservation ohne Speichern beendet: aus «anpassen» zurück zur Freigabe, sonst Ende."""
    return "approval" if state.get("reservation_aus_anpassung") else "end"


def route_after_reservation(state) -> str:
    if state.get("escalation"):
        return "escalate"
    if state.get("reservation_vorhanden") or state.get("reservation_abgelehnt"):
        return _ende_reservation(state)            # schon im System / unter 10 Personen
    if (state.get("pending_reservation") or {}).get("vollstaendig"):
        return "reservation_bestaetigung"
    return "reservation_rueckfrage"


def route_after_reservation_bestaetigung(state) -> str:
    if state.get("decision") == "speichern":
        return "reservation_speichern"
    return _ende_reservation(state)


def route_after_reservation_speichern(state) -> str:
    """Aus «anpassen»: mit der neuen Reservation neu rechnen und wieder zur Freigabe."""
    return "staffing" if state.get("reservation_aus_anpassung") else "end"


def route_after_anlass(state) -> str:
    if state.get("escalation"):
        return "escalate"
    if state.get("pending_event"):
        return "anlass_rueckfrage"
    return "context"


def route_after_context(state) -> str:
    """Wie route_after_step, zusätzlich: Woche schon freigegeben → Ende ohne neuen Plan."""
    if state.get("plan_vorhanden"):
        return "end"
    return route_after_step(state)


def route_after_step(state) -> str:
    """Gemeinsam für context, forecast und fallback: Fehler → Mensch."""
    return "escalate" if state.get("escalation") else "ok"


def route_after_plausibility(state) -> str:
    """Unplausibel → einmal Ersatzprognose (Wochentagsmittel), sonst Eskalation.

    Keine Wiederholung der Regression: Sie ist deterministisch, derselbe Input liefert
    dasselbe unplausible Ergebnis.
    """
    if state["plausibility"]["ok"]:
        return "staffing"
    return "fallback" if state.get("fallback_grund") is None else "escalate"


def route_after_approval(state) -> str:
    decision = state.get("decision")
    if decision == "freigeben":
        return "commit"
    if decision == "anpassen":
        return "korrektur" if state.get("revisions", 0) < MAX_REVISIONS else "escalate"
    return "end"


def route_after_regelfrage(state) -> str:
    """Hat das LLM ein Tool gewählt? Dann ausführen, sonst ist die Antwort fertig.

    tools_condition (LangGraph) prüft, ob die letzte Nachricht tool_calls enthält.
    """
    return "regel_tools" if tools_condition(state, messages_key="regel_messages") == "tools" else "end"


def route_after_korrektur(state) -> str:
    """Klare Korrektur → neu rechnen. Unklar → Rückfrage in der Freigabe, nichts gespeichert.
    Reservation im Feedback → Reservationsagent, danach neu rechnen."""
    if state.get("reservation_aus_anpassung"):
        return "reservation"
    return "approval" if state.get("hinweis") else "staffing"
