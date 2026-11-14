"""Korrekturen der Betriebsleitung (Langzeit-Memory). Aufgabe C5.

Lesen und Schreiben sind getrennt, damit nur freigegebene Korrekturen gespeichert werden:

    approval ─anpassen─▶ korrektur ─klar─▶ staffing ─▶ explain ─▶ approval
                             │                 ▲ liest gespeicherte + offene Korrekturen
                             └─unklar─▶ approval (Rückfrage über `hinweis`, nichts gespeichert)
    approval ─freigeben─▶ commit ─▶ memory ─▶ END   (erst hier wird gespeichert)
    approval ─ablehnen──▶ END                        (offene Korrekturen verfallen)

- korrektur: wandelt das Feedback mit with_structured_output(Korrektur) um und legt es
  in `pending_corrections` ab. Schreibt nichts in die Datenbank.
- memory: läuft nach commit und speichert die offenen Korrekturen dauerhaft.

Die Rückfrage bei unklarem Feedback geht an approval zurück, weil dort der einzige
interrupt sitzt: Die Person sieht den Plan und die Frage und antwortet mit «anpassen»
und präziserem Feedback (kein zweiter interrupt hier, siehe agent/nodes/anlass.py).

Kurzzeit-Memory = Checkpointer (gilt pro Thread).
Langzeit-Memory = Tabelle corrections (gilt über alle Läufe).
"""
import json

from langchain_core.messages import SystemMessage

import config
from agent import backends, llm
from agent.prompts import KORREKTUR_PROMPT
from agent.schemas import Korrektur

STANDARD_RUECKFRAGE = ("Bitte präzisieren Sie: Wochentag, Schicht, Rolle und wie viele "
                       "Personen mehr oder weniger?")


def korrektur(state):
    """Feedback → strukturierte Korrektur. Nur im State, noch nicht gespeichert."""
    extraktor = llm.get_llm().with_structured_output(Korrektur)
    k = extraktor.invoke([SystemMessage(KORREKTUR_PROMPT.format(
        plan=json.dumps(state["staffing"], ensure_ascii=False),
        feedback=state.get("feedback") or "",
    ))])
    revisions = state.get("revisions", 0) + 1
    vollstaendig = None not in (k.weekday, k.shift, k.role, k.delta)
    # Ruhetag oder «0 Personen» würde beim Speichern nach der Freigabe scheitern
    # (tools/memory.py prüft das). Deshalb schon hier als unklar behandeln und nachfragen.
    gueltig = vollstaendig and k.weekday in config.OPEN_WEEKDAYS and k.delta != 0
    if not (k.eindeutig and gueltig):
        return {"hinweis": k.rueckfrage or STANDARD_RUECKFRAGE, "revisions": revisions}
    neu = {"weekday": k.weekday, "shift": k.shift, "role": k.role, "delta": k.delta,
           "note": k.note or state.get("feedback") or ""}
    return {"pending_corrections": [*state.get("pending_corrections", []), neu],
            "hinweis": None, "revisions": revisions}


def memory(state):
    """Nach der Freigabe: offene Korrekturen dauerhaft speichern."""
    for c in state.get("pending_corrections", []):
        backends.save_correction(c["weekday"], c["shift"], c["role"], c["delta"], c["note"])
    return {"pending_corrections": []}
