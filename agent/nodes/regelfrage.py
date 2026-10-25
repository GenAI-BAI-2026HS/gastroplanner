"""Regelfrage mit RAG und Quellenangabe. Owner: Helin (C3)."""
from langchain_core.messages import AIMessage, SystemMessage

from agent import backends, llm
from agent.prompts import REGELFRAGE_PROMPT


def format_rules(hits: list[dict]) -> str:
    return "\n\n".join(f"[{h['source']} · {h['section']}]\n{h['text']}" for h in hits)


def regelfrage(state):
    frage = state["messages"][-1].content
    hits = backends.search_rules(frage, k=3)
    antwort = llm.get_llm().invoke([
        SystemMessage(REGELFRAGE_PROMPT.format(kontext=format_rules(hits) or "(keine Treffer)")),
        state["messages"][-1],
    ])
    return {"messages": [AIMessage(antwort.content)], "rule_sources": hits}
