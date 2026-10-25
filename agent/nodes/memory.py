"""Korrektur der Betriebsleitung merken (Langzeit-Memory). Owner: Helin (C5).

Bei «anpassen» wird das Feedback strukturiert extrahiert und gespeichert; danach
rechnet staffing neu. Ist das Feedback unklar, geht eine Rückfrage über `hinweis`
zurück an approval (kein zweiter interrupt hier, siehe agent/nodes/anlass.py).

Kurzzeit-Memory = Checkpointer (gilt pro Thread).
Langzeit-Memory = Tabelle corrections (gilt über alle Läufe).
"""
import json

from langchain_core.messages import SystemMessage

from agent import backends, llm
from agent.prompts import KORREKTUR_PROMPT
from agent.schemas import Korrektur


def memory(state):
    extraktor = llm.get_llm().with_structured_output(Korrektur)
    k = extraktor.invoke([SystemMessage(KORREKTUR_PROMPT.format(
        plan=json.dumps(state["staffing"], ensure_ascii=False),
        feedback=state.get("feedback") or "",
    ))])
    vollstaendig = None not in (k.weekday, k.shift, k.role, k.delta)
    if not (k.eindeutig and vollstaendig):
        return {"hinweis": k.rueckfrage or "Bitte präzisieren Sie: Wochentag, Schicht, Rolle "
                                           "und wie viele Personen mehr oder weniger?",
                "revisions": state.get("revisions", 0) + 1}
    backends.save_correction(k.weekday, k.shift, k.role, k.delta,
                             k.note or state.get("feedback") or "")
    return {"hinweis": None, "revisions": state.get("revisions", 0) + 1}
