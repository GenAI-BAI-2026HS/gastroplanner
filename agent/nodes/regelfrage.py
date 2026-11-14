"""Regelfrage mit Tool-Calling und RAG. Aufgabe C3, Review-Punkt 4.

Hier wählt das LLM selbst ein Tool (Function Calling, SW6):

1. regelfrage: Das LLM bekommt das Tool regeln_suchen angeboten (bind_tools). Es
   entscheidet, ob es sucht, mit welchen Stichworten und wie oft, z. B. eine Suche pro
   Thema bei «Wie lange ist die Pause und wann muss ich einen Anlass melden?».
2. regel_tools (ToolNode): führt die gewählten Suchen aus und gibt die Treffer zurück.
3. Zurück zu regelfrage: Das LLM sucht weiter oder antwortet mit Quellenangabe.

Grenze der Schleife: Nach MAX_SUCHEN Suchen bekommt das LLM das Tool nur noch mit
tool_choice="none" angeboten und muss antworten. Sucht es trotzdem weiter, endet der
Node mit «Dazu steht nichts in den Unterlagen.» statt endlos zu laufen.

Warum hier ein frei gewähltes Tool, im Node context aber nicht? context braucht bei
jeder Wochenplanung dieselben Daten (Wetter, Kalender). Ein fester Aufruf ist dort
zuverlässiger und günstiger. Bei einer Regelfrage ist offen, welche Regeln gefragt sind
und wie viele Suchen es braucht. Diese Wahl ist echte Sprachverarbeitung, also Sache des LLM.

Der Verlauf der Tool-Schleife steht im eigenen State-Feld regel_messages, nicht in
messages. In messages landet nur die fertige Antwort. So sehen andere Nodes (supervisor,
explain) nie halbe Tool-Aufrufe, und initial_state() kann die Schleife pro Anfrage leeren.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.prebuilt import ToolNode

from agent import backends, llm
from agent.prompts import REGELFRAGE_PROMPT

MAX_SUCHEN = 3
NICHTS_GEFUNDEN = "Dazu steht nichts in den Unterlagen."


def format_rules(hits: list[dict]) -> str:
    return "\n\n".join(f"[{h['source']} · {h['section']}]\n{h['text']}" for h in hits)


@tool(response_format="content_and_artifact")
def regeln_suchen(suchanfrage: str) -> tuple[str, list[dict]]:
    """Durchsucht die Hausregeln des Restaurants (Personalregeln und Regeln für Anlässe)
    und gibt die drei passendsten Abschnitte mit Quelle zurück.

    Args:
        suchanfrage: Kurze Stichworte zu genau einem Thema, z. B. «Pause Schicht» oder
            «Vorlaufzeit Anlass melden». Für mehrere Themen das Tool mehrmals aufrufen.
    """
    hits = backends.search_rules(suchanfrage, k=3)
    # content geht ans LLM, artifact (die Treffer als Daten) bleibt für rule_sources
    return (format_rules(hits) or "Keine Treffer."), hits


# Führt die Tool-Aufrufe des LLM aus. Liest und schreibt regel_messages statt messages.
regel_tools = ToolNode([regeln_suchen], messages_key="regel_messages")


def regelfrage(state):
    verlauf = state.get("regel_messages") or []
    neu = []
    if not verlauf:                                   # erster Durchgang dieser Anfrage
        neu = [SystemMessage(REGELFRAGE_PROMPT.format(max_suchen=MAX_SUCHEN)),
               HumanMessage(state["messages"][-1].content)]

    suchen = sum(isinstance(m, ToolMessage) for m in verlauf)
    limit_erreicht = suchen >= MAX_SUCHEN
    if limit_erreicht:
        modell = llm.get_llm().bind_tools([regeln_suchen], tool_choice="none")
    else:
        modell = llm.get_llm().bind_tools([regeln_suchen])
    antwort = modell.invoke(verlauf + neu)

    if antwort.tool_calls and not limit_erreicht:     # LLM hat ein Tool gewählt
        return {"regel_messages": neu + [antwort]}

    text = antwort.content if not antwort.tool_calls and antwort.content else NICHTS_GEFUNDEN
    schluss = AIMessage(text)
    return {"regel_messages": neu + [schluss], "messages": [schluss],
            "rule_sources": _quellen(verlauf)}


def _quellen(verlauf: list) -> list[dict]:
    """Alle Treffer aus den Suchen dieser Anfrage, ohne Doppelte."""
    quellen, gesehen = [], set()
    for m in verlauf:
        if not isinstance(m, ToolMessage):
            continue
        for hit in m.artifact or []:
            key = (hit["source"], hit["section"])
            if key not in gesehen:
                gesehen.add(key)
                quellen.append(hit)
    return quellen
