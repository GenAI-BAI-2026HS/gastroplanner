"""Anlass aus Freitext erfassen, bei Lücken nachfragen. Owner: Person B (B6).

Zwei Nodes, weil LangGraph einen unterbrochenen Node beim Fortsetzen von vorne
ausführt: Stünde der LLM-Aufruf im selben Node wie der interrupt, liefe er doppelt.
  anlass:            LLM extrahiert die Angaben (strukturiert) und führt sie zusammen
  anlass_rueckfrage: nur der interrupt mit der Frage nach dem ersten fehlenden Feld
"""
from datetime import date, timedelta

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

import config
from agent import llm
from agent.nodes.supervisor import datum_kontext, heute
from agent.prompts import ANLASS_PROMPT
from agent.routing import MAX_RUECKFRAGEN
from agent.schemas import Anlass

PFLICHT = ("datum", "schicht", "personen")
FRAGEN = {
    "datum": "An welchem Datum findet der Anlass statt?",
    "schicht": "Für welche Schicht ist der Anlass geplant: morgen (08–14) oder nachmittag (14–20)?",
    "personen": "Mit wie vielen Personen rechnen Sie für den Anlass?",
}


def fehlende_felder(event: dict) -> list[str]:
    return [f for f in PFLICHT if event.get(f) is None]


def planungsstart(event_datum: str, start_date: str | None) -> str:
    """Startdatum so wählen, dass der Anlass im 7-Tage-Horizont liegt.

    Liegt er schon im Horizont, bleibt das Startdatum. Sonst beginnt die Planung am
    Montag der Woche des Anlasses (frühestens heute).
    """
    d = date.fromisoformat(event_datum)
    if start_date:
        s = date.fromisoformat(start_date)
        if s <= d < s + timedelta(days=config.HORIZON_DAYS):
            return start_date
    montag = d - timedelta(days=d.weekday())
    return max(montag, heute()).isoformat()


def anlass(state):
    bekannt = state.get("pending_event") or {}
    extraktor = llm.get_llm().with_structured_output(Anlass)
    neu = extraktor.invoke([
        SystemMessage(ANLASS_PROMPT.format(bekannt=bekannt or "keine", **datum_kontext())),
        *state["messages"][-6:],
    ])
    event = {**bekannt, **{k: v for k, v in neu.model_dump().items() if v is not None}}

    if fehlende_felder(event):
        if state.get("anlass_versuche", 0) >= MAX_RUECKFRAGEN:
            return {"pending_event": None,
                    "escalation": "Anlass nach mehreren Rückfragen unvollständig: "
                                  + ", ".join(fehlende_felder(event))}
        return {"pending_event": event}

    vertrag = {"date": event["datum"], "shift": event["schicht"],
               "persons": event["personen"], "type": event.get("art") or "Anlass"}
    return {
        "events": state.get("events", []) + [vertrag],
        "pending_event": None,
        "start_date": planungsstart(event["datum"], state.get("start_date")),
    }


def anlass_rueckfrage(state):
    frage = FRAGEN[fehlende_felder(state["pending_event"])[0]]
    antwort = interrupt({"typ": "rueckfrage", "frage": frage})
    return {"messages": [AIMessage(frage), HumanMessage(str(antwort))],
            "anlass_versuche": state.get("anlass_versuche", 0) + 1}
