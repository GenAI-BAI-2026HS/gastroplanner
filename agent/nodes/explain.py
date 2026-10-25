"""Plan erklären: Annahmen, Unsicherheit, Regelquellen. Owner: Person B (B4).

Das LLM bekommt den fertigen Plan als JSON und schreibt nur den Erklärtext.
Die Tabelle zeigt die App direkt aus state["staffing"], nicht aus diesem Text.
"""
import json

from langchain_core.messages import AIMessage, SystemMessage

from agent import backends, llm
from agent.nodes.regelfrage import format_rules
from agent.prompts import EXPLAIN_PROMPT


def _regeln_zum_plan(plan: list[dict], events: list[dict]) -> list[dict]:
    refs = sorted({ref for row in plan for ref in row.get("rule_refs", [])})
    hits, seen = [], set()
    for frage in refs + (["Anlass Vorlaufzeit zusätzliches Personal"] if events else []):
        for hit in backends.search_rules(frage, k=1):
            key = (hit["source"], hit["section"])
            if key not in seen:
                seen.add(key)
                hits.append(hit)
    return hits


def _annahmen(forecast: list[dict]) -> list[dict]:
    return [{"date": f["date"], "shift": f["shift"], "guests": f["guests"],
             "lower": f["lower"], "upper": f["upper"], **f.get("assumptions", {})}
            for f in forecast or []]


def explain(state):
    regeln = _regeln_zum_plan(state["staffing"], state.get("events", []))
    prompt = EXPLAIN_PROMPT.format(
        plan=json.dumps(state["staffing"], ensure_ascii=False),
        annahmen=json.dumps(_annahmen(state.get("forecast")), ensure_ascii=False),
        anlaesse=json.dumps(state.get("events", []), ensure_ascii=False),
        korrekturen=json.dumps(state.get("corrections", []), ensure_ascii=False),
        regeln=format_rules(regeln) or "(keine)",
    )
    text = llm.get_llm().invoke([SystemMessage(prompt), *state["messages"][-2:]]).content
    return {"explanation": text, "rule_sources": regeln, "messages": [AIMessage(text)]}
