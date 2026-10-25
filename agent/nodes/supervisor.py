"""Supervisor: Absicht erkennen und Startdatum extrahieren. Owner: Person B (B4)."""
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


def datum_kontext() -> dict:
    t = heute()
    return {"heute": t.isoformat(), "wochentag": WOCHENTAGE[t.weekday()]}


def supervisor(state):
    router = llm.get_llm().with_structured_output(Route)
    route = router.invoke([
        SystemMessage(SUPERVISOR_PROMPT.format(**datum_kontext())),
        *state["messages"][-6:],
    ])
    # Das Standarddatum rechnet Python, nicht das LLM (Grundprinzip «LLM rechnet nie»)
    return {"intent": route.intent, "start_date": route.start_date or naechster_montag()}
