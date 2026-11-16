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
from datetime import date, timedelta

import config
from agent import backends
from agent.mcp_client import MCPToolError
from agent.nodes import supervisor
from tools.reservations import reserved_per_shift

DAYS = config.HORIZON_DAYS
WETTER_TAGE = 16        # Open-Meteo: Prognose für heute und die nächsten 15 Tage
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


def wetter_bis() -> date:
    """Letzter Tag, für den Open-Meteo eine Prognose liefert (heute + 15 Tage)."""
    return supervisor.heute() + timedelta(days=WETTER_TAGE - 1)


def context(state):
    """Wetter und Kalender holen.

    Liegt die Woche ganz oder teilweise hinter dem Wetterhorizont, wird das Wetter gar nicht
    abgefragt (Open-Meteo lehnt das ab) und kein Wetter erfunden: weather=None, forecast
    nimmt dann direkt die Ersatzprognose aus dem Wochentagsmittel, die kein Wetter braucht.
    """
    ende = date.fromisoformat(state["start_date"]) + timedelta(days=DAYS - 1)
    ohne_wetter = not backends.use_fixtures() and ende > wetter_bis()
    try:
        weather, w1 = (None, 0) if ohne_wetter else \
            mit_wiederholung(backends.get_weather, state["start_date"], DAYS)
        calendar, w2 = mit_wiederholung(backends.get_calendar, state["start_date"], DAYS)
    except VORUEBERGEHEND as e:  # API weg → nie Werte erfinden (B2), an den Menschen eskalieren
        return {"escalation": f"Wetter oder Kalender nach {MAX_VERSUCHE} Versuchen "
                              f"nicht verfügbar: {e}"}
    except Exception as e:
        return {"escalation": f"Wetter oder Kalender nicht verfügbar: {e}"}
    return {"context": {"weather": weather, "calendar": calendar}, "escalation": None,
            "retries": state.get("retries", 0) + w1 + w2}


def forecast(state):
    if (state.get("context") or {}).get("weather", []) is None:
        return _wochentagsmittel(state, f"Die Wetterprognose reicht erst bis "
                                        f"{wetter_bis():%d.%m.%Y}, die Regression braucht Wetterdaten")
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
    return _wochentagsmittel(state, grund)


def _wochentagsmittel(state, grund: str) -> dict:
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

    Reservationen (Tabelle reservations) im Planungshorizont werden pro Tag und Schicht
    summiert und wie Anlässe zur Prognose addiert (Reservationen gibt es erst ab 10 Personen).
    Ins State kommen nur die Summen, keine Namen oder Telefonnummern.
    """
    corrections = backends.get_corrections() + list(state.get("pending_corrections", []))
    reservations = reserved_per_shift(backends.get_reservations(state["start_date"], DAYS))
    plan = backends.calculate_staffing(state["forecast"],
                                       state.get("events", []) + reservations, corrections)
    return {"staffing": plan, "corrections": corrections, "reservations": reservations}
