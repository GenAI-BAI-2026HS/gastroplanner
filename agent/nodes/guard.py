"""Safeguarding. Owner: Helin (C4).

guard:  LLM mit strukturierter Ausgabe (Guard) prüft, ob die Anfrage zum Thema gehört.
reject: gemeinsames Ende für guard und intent «themenfremd»; höfliche Ablehnung.
"""
from langchain_core.messages import AIMessage, SystemMessage

from agent import llm
from agent.prompts import GUARD_PROMPT, REJECT_TEXT
from agent.schemas import Guard


def guard(state):
    pruefer = llm.get_llm().with_structured_output(Guard)
    ergebnis = pruefer.invoke([SystemMessage(GUARD_PROMPT), *state["messages"][-4:]])
    return {"allowed": ergebnis.erlaubt}


def reject(state):
    return {"messages": [AIMessage(REJECT_TEXT)]}
