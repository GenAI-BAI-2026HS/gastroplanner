"""Plan erklären: Annahmen, Unsicherheit, Regelquellen. Aufgabe B4.

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


def _prognose_anweisung(fallback_grund: str | None) -> str:
    """Nur die zutreffende Anweisung ins Prompt. Eine bedingte Anweisung («falls Ersatz…»)
    hat das Modell auch bei der Regression befolgt und eine Ersatzprognose erfunden."""
    if not fallback_grund:
        return ("Die Prognose stammt aus der Regression. Erwähne keine Ersatzprognose und "
                "behaupte nicht, die Regression sei unplausibel.")
    return ("Sage im ersten Satz, dass eine Ersatzprognose aus dem Mittel derselben Wochentage "
            f"gilt, und nenne den Grund: {fallback_grund}")


def explain(state):
    regeln = _regeln_zum_plan(state["staffing"], state.get("events", []))
    prompt = EXPLAIN_PROMPT.format(
        plan=json.dumps(state["staffing"], ensure_ascii=False),
        prognosequelle=(f"Ersatzprognose Wochentagsmittel ({state['fallback_grund']})"
                        if state.get("fallback_grund") else "Regression"),
        prognose_anweisung=_prognose_anweisung(state.get("fallback_grund")),
        annahmen=json.dumps(_annahmen(state.get("forecast")), ensure_ascii=False),
        anlaesse=json.dumps(state.get("events", []), ensure_ascii=False),
        reservationen=json.dumps(state.get("reservations", []), ensure_ascii=False),
        korrekturen=json.dumps(state.get("corrections", []), ensure_ascii=False),
        regeln=format_rules(regeln) or "(keine)",
    )
    text = llm.get_llm().invoke([SystemMessage(prompt), *state["messages"][-2:]]).text
    return {"explanation": text, "rule_sources": regeln, "messages": [AIMessage(text)]}
