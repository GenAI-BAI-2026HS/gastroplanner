"""Deterministische Planungskette ohne LLM. Owner: Person B (B4).

Die Nodes rufen nur die Vertragsfunktionen (über agent/backends.py) auf und schreiben
Rohdaten in den State. Fehler werden hier gefangen und als `escalation` gesetzt;
der Router entscheidet dann (sichtbar im Trace, statt den Lauf abzubrechen).
"""
import config
from agent import backends

DAYS = config.HORIZON_DAYS


def context(state):
    try:
        weather = backends.get_weather(state["start_date"], DAYS)
        calendar = backends.get_calendar(state["start_date"], DAYS)
    except Exception as e:  # API weg → nie Werte erfinden (B2), an den Menschen eskalieren
        return {"escalation": f"Wetter oder Kalender nicht verfügbar: {e}"}
    return {"context": {"weather": weather, "calendar": calendar}, "escalation": None}


def forecast(state):
    try:
        return {"forecast": backends.forecast_guests(state["start_date"], DAYS)}
    except Exception as e:
        return {"escalation": f"Prognose fehlgeschlagen: {e}"}


def plausibility(state):
    result = backends.check_plausibility(state["forecast"], state["start_date"], DAYS)
    return {"plausibility": result,
            "retries": state.get("retries", 0) + (0 if result["ok"] else 1)}


def staffing(state):
    corrections = backends.get_corrections()          # Langzeit-Memory (C5)
    plan = backends.calculate_staffing(state["forecast"], state.get("events", []), corrections)
    return {"staffing": plan, "corrections": corrections}
