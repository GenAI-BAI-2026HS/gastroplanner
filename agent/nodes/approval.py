"""Human-in-the-Loop: Freigabe und Übermittlung. Aufgabe B5.

approval enthält nur den interrupt und die Prüfung der Antwort. Gespeichert wird
ausschliesslich nach «freigeben»: der Plan in commit, offene Korrekturen danach in memory.
So wird ohne Freigabe technisch nichts übernommen.

Fortsetzen: graph.invoke(Command(resume={"decision": "freigeben" | "anpassen" | "ablehnen",
                                         "feedback": "..."}), config)
"""
from langchain_core.messages import AIMessage
from langgraph.types import interrupt

from agent import backends

ENTSCHEIDE = {"freigeben", "anpassen", "ablehnen"}


def approval(state):
    antwort = interrupt({
        "typ": "freigabe",
        "plan": state["staffing"],
        "erklaerung": state["explanation"],
        "hinweis": state.get("hinweis"),                          # Rückfrage aus korrektur
        "korrekturen_offen": state.get("pending_corrections", []),  # werden bei Freigabe gespeichert
        "fallback_grund": state.get("fallback_grund"),            # gesetzt = Wochentagsmittel
    })
    antwort = antwort if isinstance(antwort, dict) else {"decision": str(antwort)}
    decision = antwort.get("decision")
    if decision not in ENTSCHEIDE:
        decision = "ablehnen"                      # im Zweifel nichts übernehmen
    update = {"decision": decision, "feedback": antwort.get("feedback"), "hinweis": None}
    if decision == "ablehnen":
        update["messages"] = [AIMessage("Plan verworfen. Es wurde nichts gespeichert.")]
    return update


def commit(state):
    plan_id = backends.save_approved_plan(state["staffing"])
    return {"plan_id": plan_id,
            "messages": [AIMessage(f"Plan freigegeben und übermittelt (Plan-ID {plan_id}).")]}
