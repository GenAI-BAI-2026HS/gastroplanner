"""Deterministische Planungskette ohne LLM. Aufgabe B4.

Die Nodes rufen nur die Vertragsfunktionen (über agent/backends.py) auf und schreiben
Rohdaten in den State. Fehler werden hier gefangen und als `escalation` gesetzt;
der Router entscheidet dann (sichtbar im Trace, statt den Lauf abzubrechen).

Zwei Fehlerarten, zwei Antworten:

- Datenfehler (API weg, Timeout, MCP-Fehler): Wiederholung im Node, höchstens
  MAX_VERSUCHE Versuche mit wachsender Wartezeit. Danach Eskalation. Hier kann eine
  Wiederholung helfen, weil der Fehler ausserhalb unseres Codes liegt.
- Unplausible Prognose: KEINE Wiederholung. Die Regression ist deterministisch und
  liefert bei gleichem Input dasselbe Ergebnis. Stattdessen Ersatzprognose aus dem
  Wochentagsmittel (fallback), die erneut geprüft wird. Ist auch sie unplausibel, wird
  eskaliert. Die Schleife ist damit auf genau einen Fallback begrenzt.
"""
import time

import config
from agent import backends
from agent.mcp_client import MCPToolError

DAYS = config.HORIZON_DAYS
MAX_VERSUCHE = 3        # 1 Versuch + 2 Wiederholungen
WARTEZEIT_S = 1.0       # 1 s, dann 2 s (in Tests auf 0 gesetzt)

# Fehler, bei denen eine Wiederholung helfen kann. requests-Fehler erben von OSError.
# Andere Fehler (z. B. ValueError aus einem Programmfehler) werden nicht wiederholt.
VORUEBERGEHEND = (ConnectionError, TimeoutError, OSError, MCPToolError)


def mit_wiederholung(fn, *args):
    """Ruft fn(*args) auf; wiederholt nur bei vorübergehenden Fehlern.

    Gibt (Ergebnis, Anzahl Wiederholungen) zurück. Nach MAX_VERSUCHE Versuchen wird der
    letzte Fehler weitergereicht.
    """
    for versuch in range(1, MAX_VERSUCHE + 1):
        try:
            return fn(*args), versuch - 1
        except VORUEBERGEHEND:
            if versuch == MAX_VERSUCHE:
                raise
            time.sleep(WARTEZEIT_S * versuch)


def context(state):
    try:
        weather, w1 = mit_wiederholung(backends.get_weather, state["start_date"], DAYS)
        calendar, w2 = mit_wiederholung(backends.get_calendar, state["start_date"], DAYS)
    except VORUEBERGEHEND as e:  # API weg → nie Werte erfinden (B2), an den Menschen eskalieren
        return {"escalation": f"Wetter oder Kalender nach {MAX_VERSUCHE} Versuchen "
                              f"nicht verfügbar: {e}"}
    except Exception as e:
        return {"escalation": f"Wetter oder Kalender nicht verfügbar: {e}"}
    return {"context": {"weather": weather, "calendar": calendar}, "escalation": None,
            "retries": state.get("retries", 0) + w1 + w2}


def forecast(state):
    try:
        prognose, w = mit_wiederholung(backends.forecast_guests, state["start_date"], DAYS)
    except Exception as e:
        return {"escalation": f"Prognose fehlgeschlagen: {e}"}
    return {"forecast": prognose, "fallback_grund": None,
            "retries": state.get("retries", 0) + w}


def plausibility(state):
    return {"plausibility": backends.check_plausibility(state["forecast"], state["start_date"], DAYS)}


def fallback(state):
    """Ersatzprognose aus dem Wochentagsmittel, wenn die Regression unplausibel ist."""
    grund = "Regression unplausibel: " + "; ".join(state["plausibility"].get("issues") or ["?"])
    calendar = (state.get("context") or {}).get("calendar")
    open_dates = [c["date"] for c in calendar if c.get("is_open")] if calendar else None
    try:
        prognose = backends.weekday_mean_forecast(state["start_date"], DAYS, open_dates)
    except Exception as e:
        return {"escalation": f"{grund}. Ersatzprognose nicht möglich: {e}"}
    return {"forecast": prognose, "fallback_grund": grund, "escalation": None}


def staffing(state):
    """Einzige Stelle, an der Korrekturen gelesen werden.

    Gespeicherte Korrekturen (Langzeit-Memory, C5) plus die noch nicht freigegebenen
    Korrekturen aus diesem Lauf. Gespeichert wird erst nach der Freigabe (nodes/memory.py).
    """
    corrections = backends.get_corrections() + list(state.get("pending_corrections", []))
    plan = backends.calculate_staffing(state["forecast"], state.get("events", []), corrections)
    return {"staffing": plan, "corrections": corrections}
