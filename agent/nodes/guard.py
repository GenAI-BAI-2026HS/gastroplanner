"""Safeguarding. Aufgabe C4.

guard:  LLM mit strukturierter Ausgabe (Guard) prüft, ob die Anfrage zum Thema gehört.
reject: gemeinsames Ende für guard und intent «themenfremd»; höfliche Ablehnung.

Zwei Schichten: Vor unserem guard-Prompt prüft schon der Anbieter (Azure OpenAI über das
LiteLLM-Gateway) mit einem eigenen Inhaltsfilter. Schlägt dieser an (z. B. bei «Ignoriere
deine Regeln …»), kommt statt einer Antwort ein Fehler 400. Das werten wir als Ablehnung,
damit der Agent höflich ablehnt statt abzustürzen. Andere Fehler werden weitergereicht.
"""
from langchain_core.messages import AIMessage, SystemMessage
from openai import BadRequestError

from agent import llm
from agent.prompts import GUARD_PROMPT, REJECT_TEXT
from agent.schemas import Guard


FILTER_HINWEISE = ("content management policy", "content_filter", "content filter")


def guard(state):
    pruefer = llm.get_llm().with_structured_output(Guard)
    try:
        ergebnis = pruefer.invoke([SystemMessage(GUARD_PROMPT), *state["messages"][-4:]])
    except BadRequestError as e:
        if ist_inhaltsfilter(e):                     # Anbieter-Filter hat blockiert
            return {"allowed": False}
        raise
    return {"allowed": ergebnis.erlaubt}


def ist_inhaltsfilter(fehler: Exception) -> bool:
    text = str(fehler).lower()
    return any(h in text for h in FILTER_HINWEISE)


def reject(state):
    return {"messages": [AIMessage(REJECT_TEXT)]}
