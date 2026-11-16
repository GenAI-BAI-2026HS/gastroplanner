"""Reservationsagent: Tischreservation erfassen, nachfragen, bestätigen, speichern.

    reservation ─unvollständig/ungültig─▶ reservation_rueckfrage ─▶ reservation
        │ vollständig
        ▼
    reservation_bestaetigung (interrupt) ─speichern─▶ reservation_speichern ─▶ END
                                         └verwerfen─▶ END (nichts gespeichert)

- reservation: LLM extrahiert Name, Telefonnummer, Personen, Datum, Uhrzeit/Schicht
  (strukturiert). Python prüft die Werte (tools/reservations.pruefen) und leitet die
  Schicht aus der Uhrzeit ab. Ungültige Felder werden verworfen und neu erfragt.
- reservation_rueckfrage: nur der interrupt (wie anlass_rueckfrage, siehe dort warum).
- reservation_bestaetigung: zeigt die erfassten Angaben; erst «speichern» schreibt.
- reservation_speichern: einzige Stelle, an der eine Reservation gespeichert wird.

In der Wochenplanung addiert der Node staffing die reservierten Personen pro Tag und
Schicht zur Gästeprognose (agent/nodes/planung.py).
"""
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

from agent import backends, llm
from agent.nodes import supervisor
from agent.prompts import RESERVATION_PROMPT
from agent.routing import MAX_RUECKFRAGEN
from agent.schemas import Reservation
from tools.reservations import pruefen, schicht_aus_uhrzeit, telefon_normalisieren

PFLICHT = ("name", "telefon", "personen", "datum", "schicht")
FRAGEN = {
    "name": "Auf welchen Namen soll ich reservieren?",
    "telefon": "Unter welcher Telefonnummer ist die Person erreichbar?",
    "personen": "Für wie viele Personen ist die Reservation?",
    "datum": "Für welches Datum ist die Reservation?",
    "schicht": "Um welche Uhrzeit kommen die Gäste (geöffnet 08–20 Uhr)?",
}
WOCHENTAGE = supervisor.WOCHENTAGE


def fehlende_felder(r: dict) -> list[str]:
    return [f for f in PFLICHT if r.get(f) in (None, "")]


def reservation(state):
    bekannt = {k: v for k, v in (state.get("pending_reservation") or {}).items()
               if k in Reservation.model_fields}
    extraktor = llm.get_llm().with_structured_output(Reservation)
    neu = extraktor.invoke([
        SystemMessage(RESERVATION_PROMPT.format(bekannt=bekannt or "keine",
                                                **supervisor.datum_kontext())),
        *state["messages"][-6:],
    ])
    r = {**bekannt, **{k: v for k, v in neu.model_dump().items() if v not in (None, "")}}

    # Die Schicht folgt aus der Uhrzeit (Python, nicht LLM)
    if schicht := schicht_aus_uhrzeit(r.get("uhrzeit")):
        r["schicht"] = schicht
    fehler = pruefen(r, supervisor.heute())
    for feld in fehler:
        r[feld] = None
    if "uhrzeit" in fehler:
        r["schicht"] = None

    if fehlende_felder(r):
        if state.get("reservation_versuche", 0) >= MAX_RUECKFRAGEN:
            return {"pending_reservation": None,
                    "escalation": "Reservation nach mehreren Rückfragen unvollständig: "
                                  + ", ".join(fehlende_felder(r))}
        return {"pending_reservation": {**r, "fehler": fehler, "vollstaendig": False}}

    r["telefon"] = telefon_normalisieren(r["telefon"])
    return {"pending_reservation": {**r, "fehler": {}, "vollstaendig": True}}


def reservation_rueckfrage(state):
    r = state["pending_reservation"]
    feld = fehlende_felder(r)[0]
    hinweis = " ".join(r.get("fehler", {}).values())
    frage = f"{hinweis} {FRAGEN[feld]}".strip()
    antwort = interrupt({"typ": "rueckfrage", "frage": frage})
    return {"messages": [AIMessage(frage), HumanMessage(str(antwort))],
            "reservation_versuche": state.get("reservation_versuche", 0) + 1}


def beschreibung(r: dict) -> str:
    d = date.fromisoformat(r["datum"])
    zeit = f", {r['uhrzeit']} Uhr" if r.get("uhrzeit") else ""
    return (f"{r['name']}, {r['personen']} Personen, {WOCHENTAGE[d.weekday()]} "
            f"{d:%d.%m.%Y} {r['schicht']}{zeit}, Tel. {r['telefon']}")


def reservation_bestaetigung(state):
    r = state["pending_reservation"]
    antwort = interrupt({
        "typ": "reservation",
        "reservation": {k: r.get(k) for k in ("name", "telefon", "personen", "datum",
                                              "uhrzeit", "schicht")},
        "frage": f"Soll ich diese Reservation speichern? {beschreibung(r)}",
    })
    decision = antwort.get("decision") if isinstance(antwort, dict) else str(antwort)
    if str(decision).strip().lower() in {"speichern", "ja", "ok"}:
        return {"decision": "speichern"}
    return {"decision": "verwerfen", "pending_reservation": None,   # im Zweifel nichts speichern
            "messages": [AIMessage("Reservation verworfen. Es wurde nichts gespeichert.")]}


def reservation_speichern(state):
    r = state["pending_reservation"]
    rid = backends.save_reservation(r["name"], r["telefon"], r["personen"], r["datum"],
                                    r["schicht"], r.get("uhrzeit"))
    total = sum(x["persons"] for x in backends.get_reservations(r["datum"], 1)
                if x["shift"] == r["schicht"])
    text = (f"Reservation gespeichert: {beschreibung(r)}. "
            f"Reserviert in dieser Schicht total: {total} Personen. Die reservierten Gäste "
            "werden bei der Wochenplanung zur Gästeprognose addiert.")
    return {"reservation_id": rid, "pending_reservation": None, "messages": [AIMessage(text)]}
