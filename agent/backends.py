"""Einzige Stelle, an der der Agent die Funktionen der anderen Teammitglieder aufruft.

USE_FIXTURES=1 (in .env): Statt der echten Funktionen werden die Beispieldateien in
tests/fixtures/ verwendet. So läuft der Graph end-to-end, bevor A3/A5 (Prognose),
C2 (Besetzung), C3 (RAG) und C5 (Memory) fertig sind. Die Fixtures gelten für die
Woche ab 2026-10-26; das Startdatum wird im Fixture-Modus ignoriert.

Sobald eine Funktion fertig ist: USE_FIXTURES=0, sonst nichts ändern. Die Nodes
importieren nur dieses Modul, nie direkt forecast/, planning/ oder tools/.
"""
import json
import os
from functools import lru_cache

import config


def use_fixtures() -> bool:
    return os.getenv("USE_FIXTURES", "1") == "1"


def use_mcp() -> bool:
    """USE_MCP=0: Wetter und Kalender direkt aufrufen statt über den MCP-Server (A7).

    Nur für ein Deployment gedacht, in dem der MCP-Subprozess nicht startet. Lokal und in
    der Demo bleibt MCP an (Standard).
    """
    return os.getenv("USE_MCP", "1") == "1"


@lru_cache
def _fixture(name: str):
    return json.loads((config.FIXTURES_DIR / f"{name}.json").read_text(encoding="utf-8"))


# --- Kontext (B2/B3, über MCP) ------------------------------------------------
def get_weather(start_date: str, days: int) -> list[dict]:
    if use_fixtures():
        return _fixture("weather_example")
    if not use_mcp():
        from tools.weather import get_weather as direkt
        return direkt(start_date, days)
    from agent.mcp_client import call_mcp_tool
    return call_mcp_tool("get_weather", {"start_date": start_date, "days": days})


def get_calendar(start_date: str, days: int) -> list[dict]:
    if use_fixtures():
        return _fixture("calendar_example")
    if not use_mcp():
        from tools.calendar_ch import get_calendar as direkt
        return direkt(start_date, days)
    from agent.mcp_client import call_mcp_tool
    return call_mcp_tool("get_calendar", {"start_date": start_date, "days": days})


# --- Prognose (A3, A5) ----------------------------------------------------------
def forecast_guests(start_date: str, days: int) -> list[dict]:
    if use_fixtures():
        return _fixture("forecast_example")
    from forecast.predict import forecast_guests as real
    return real(start_date, days)


def get_history(start_date: str) -> list[dict]:
    """Gäste pro Tag und Schicht vor dem Startdatum (Tabelle history, A2)."""
    if use_fixtures():
        return _fixture("history_example")
    import sqlite3
    from contextlib import closing
    with closing(sqlite3.connect(config.DB_PATH)) as con:
        rows = con.execute("SELECT date, shift, guests FROM history WHERE date < ?",
                           (start_date,)).fetchall()
    return [{"date": d, "shift": s, "guests": g} for d, s, g in rows]


def weekday_mean_forecast(start_date: str, days: int,
                          open_dates: list[str] | None = None) -> list[dict]:
    """Ersatzprognose aus dem Wochentagsmittel (Fallback bei unplausibler Regression)."""
    from forecast.baseline import weekday_mean_forecast as baseline
    start = "2026-10-26" if use_fixtures() else start_date      # Fixtures gelten ab 26.10.
    return baseline(get_history(start), start, days, open_dates)


def check_plausibility(forecast: list[dict], start_date: str, days: int) -> dict:
    if use_fixtures():
        return {"ok": bool(forecast), "issues": [] if forecast else ["Prognose ist leer"]}
    from forecast.checks import check_plausibility as real
    return real(forecast, start_date, days)


# --- Besetzung (C2) -------------------------------------------------------------
def calculate_staffing(forecast: list[dict], events: list[dict],
                       corrections: list[dict]) -> list[dict]:
    if use_fixtures():
        # Fixture berücksichtigt keine Anlässe; das macht erst C2. Korrekturen werden
        # vereinfacht angewendet (nie unter die Mindestbesetzung), damit die Memory-Schleife
        # im Fixture-Modus sichtbar wirkt.
        return _apply_corrections([dict(row) for row in _fixture("staffing_example")],
                                  corrections)
    from planning.staffing import calculate_staffing as real
    return real(forecast, events, corrections)


def _apply_corrections(plan: list[dict], corrections: list[dict]) -> list[dict]:
    from datetime import date
    minimum = {"kueche": lambda s: config.MIN_KUECHE[s], "service": lambda s: config.MIN_SERVICE,
               "abwasch": lambda s: config.MIN_ABWASCH}
    for row in plan:
        weekday = date.fromisoformat(row["date"]).weekday()
        for c in corrections:
            if c["weekday"] == weekday and c["shift"] == row["shift"] and c["role"] in minimum:
                row[c["role"]] = max(minimum[c["role"]](row["shift"]), row[c["role"]] + c["delta"])
    return plan


# --- Wissen (C3) ----------------------------------------------------------------
def search_rules(question: str, k: int = 3) -> list[dict]:
    if use_fixtures():
        # Einfache Stichwortsuche als Ersatz für das Hybrid Retrieval von C3
        words = {w.strip("?.,!«»").lower() for w in question.split() if len(w) > 2}
        rules = _fixture("rules_example")

        def score(rule):
            text = (rule["section"] + " " + rule["text"]).lower()
            return sum(w in text for w in words)

        return sorted(rules, key=score, reverse=True)[:k]
    from tools.rag import search_rules as real
    return real(question, k)


# --- Memory (C5) ----------------------------------------------------------------
_fixture_corrections: list[dict] = []


def get_corrections() -> list[dict]:
    if use_fixtures():
        return list(_fixture_corrections)
    from tools.memory import get_corrections as real
    return real()


def save_correction(weekday: int, shift: str, role: str, delta: int, note: str) -> None:
    if use_fixtures():
        _fixture_corrections.append({"weekday": weekday, "shift": shift, "role": role,
                                     "delta": delta, "note": note})
        return
    from tools.memory import save_correction as real
    real(weekday, shift, role, delta, note)


# --- Freigegebene Pläne (B5) ------------------------------------------------------
def save_approved_plan(staffing: list[dict]) -> str:
    from tools.plans import save_approved_plan as real
    return real(staffing)
