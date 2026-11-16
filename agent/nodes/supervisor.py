"""Supervisor: Absicht erkennen und Startdatum extrahieren. Aufgabe B4."""
from datetime import date, timedelta

from langchain_core.messages import SystemMessage

from agent import llm
from agent.prompts import SUPERVISOR_PROMPT
from agent.schemas import Route

WOCHENTAGE = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]


def heute() -> date:
    """Eigene Funktion, damit Tests das Datum festlegen können."""
    return date.today()


def naechster_montag(tag: date | None = None) -> str:
    tag = tag or heute()
    return (tag + timedelta(days=(7 - tag.weekday()) % 7 or 7)).isoformat()


def wochenstart(start_date: str) -> str:
    """Geplant wird immer eine ganze Woche ab Montag.

    Nennt die Person einen Tag mitten in der Woche (z. B. «Donnerstag Firmenlunch»), gilt
    der Montag dieser Woche, sofern er nicht in der Vergangenheit liegt. Sonst bleibt das
    Datum (die laufende Woche wird ab dem genannten Tag geplant).
    """
    tag = date.fromisoformat(start_date)
    montag = tag - timedelta(days=tag.weekday())
    return montag.isoformat() if montag > heute() else start_date


def datum_kontext() -> dict:
    t = heute()
    return {"heute": t.isoformat(), "wochentag": WOCHENTAGE[t.weekday()]}


def supervisor(state):
    router = llm.get_llm().with_structured_output(Route)
    route = router.invoke([
        SystemMessage(SUPERVISOR_PROMPT.format(**datum_kontext())),
        *state["messages"][-6:],
    ])
    # Standarddatum und Wochenstart rechnet Python, nicht das LLM (Grundprinzip «LLM rechnet nie»)
    start = wochenstart(route.start_date) if route.start_date else naechster_montag()
    return {"intent": route.intent, "start_date": start}
