"""Eskalation an den Menschen. Owner: Person B (B4)."""
from langchain_core.messages import AIMessage


def escalate(state):
    grund = state.get("escalation")
    if not grund and state.get("plausibility") and not state["plausibility"]["ok"]:
        grund = "Prognose auch nach Wiederholung unplausibel: " + "; ".join(
            state["plausibility"]["issues"])
    if not grund and state.get("decision") == "anpassen":
        grund = "Zu viele Anpassungsrunden ohne Freigabe."
    text = ("Ich kann keinen verlässlichen Plan erstellen und übergebe an die Betriebsleitung. "
            f"Grund: {grund or 'unbekannt'}")
    return {"escalation": grund, "messages": [AIMessage(text)]}
