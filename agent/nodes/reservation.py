"""Reservationsagent: Reservation für einen Anlass erfassen, nachfragen, bestätigen, speichern.

    reservation ─unvollständig/ungültig─▶ reservation_rueckfrage ─▶ reservation
        │ vollständig                    └ unter 10 Personen / schon im System ─▶ Ende
        ▼
    reservation_bestaetigung (interrupt) ─speichern─▶ reservation_speichern ─▶ Ende
                                         └verwerfen─▶ Ende (nichts gespeichert)

Ende = END bei einer neuen Anfrage. Kommt die Reservation aus «anpassen» in der Freigabe
(reservation_aus_anpassung), geht es danach zurück: gespeichert → staffing (neu rechnen),
sonst → approval mit einem Hinweis. Siehe agent/routing.py.

- reservation: LLM extrahiert Personen, Datum, Uhrzeit/Schicht, Grund, Name, Telefonnummer
  (strukturiert). Python prüft die Werte (tools/reservations.pruefen), leitet die Schicht
  aus der Uhrzeit ab und lehnt Gruppen unter 10 Personen ab, bevor nach Name und Telefon
  gefragt wird (keine unnötigen Personendaten).
- reservation_rueckfrage: nur der interrupt (wie anlass_rueckfrage, siehe dort warum).
- reservation_bestaetigung: zeigt die erfassten Angaben; erst «speichern» schreibt.
- reservation_speichern: einzige Stelle, an der eine Reservation gespeichert wird.

In der Wochenplanung addiert der Node staffing die reservierten Personen pro Tag und
Schicht zur Gästeprognose (agent/nodes/planung.py).
"""
from datetime import date

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

import config
from agent import backends, llm
from agent.nodes import supervisor
from agent.prompts import RESERVATION_PROMPT
from agent.routing import MAX_RUECKFRAGEN
from agent.schemas import Reservation
from tools.reservations import (finde_bestehende, pruefen, reservierbar, schicht_aus_uhrzeit,
                                telefon_normalisieren)

# Reihenfolge der Rückfragen: erst prüfen, ob reserviert werden kann, dann Personendaten.
PFLICHT = ("personen", "datum", "schicht", "grund", "name", "telefon")
FRAGEN = {
    "personen": "Für wie viele Personen ist die Reservation?",
    "datum": "Für welches Datum ist die Reservation?",
    "schicht": "Um welche Uhrzeit kommen die Gäste (geöffnet 08–20 Uhr)?",
    "grund": "Was ist der Grund der Reservation (z. B. Firmenessen, Geburtstag, Verein)?",
    "name": "Auf welchen Namen soll ich reservieren?",
    "telefon": "Unter welcher Telefonnummer ist die Person erreichbar?",
}
WOCHENTAGE = supervisor.WOCHENTAGE


def fehlende_felder(r: dict) -> list[str]:
    return [f for f in PFLICHT if r.get(f) in (None, "")]


def _ende(state, text: str, **extra) -> dict:
    """Reservation endet ohne Speichern. Aus «anpassen»: Text als Hinweis in die Freigabe."""
    update = {"pending_reservation": None, "messages": [AIMessage(text)], **extra}
    if state.get("reservation_aus_anpassung"):
        update["hinweis"] = text
    return update


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

    # Reservationen nur für Anlässe ab 10 Personen
    if r.get("personen") is not None and not reservierbar(r["personen"]):
        return _ende(state, (
            f"Reservationen sind nur für Anlässe ab {config.RESERVATION_MIN_PERSONEN} Personen "
            f"möglich. Gruppen mit {r['personen']} Personen kommen ohne Reservation; sie sind "
            "in der Gästeprognose bereits enthalten. Es wurde nichts erfasst."),
            reservation_abgelehnt="unter_minimum")

    # Schon im System? Gleicher Tag und Schicht mit gleichem Name oder gleicher Telefonnummer.
    if r.get("datum") and r.get("schicht"):
        treffer, kandidaten = finde_bestehende(r, backends.get_reservations(r["datum"], 1))
        if treffer:
            return _ende(state, f"Diese Reservation ist bereits im System: "
                                f"{beschreibung_db(treffer)}. Es wurde nichts neu erfasst.",
                         reservation_vorhanden=treffer)
        if kandidaten and not r.get("name"):
            k = kandidaten[0]
            fehler["hinweis"] = (f"Für diese Schicht gibt es bereits eine Reservation für "
                                 f"{k['persons']} Personen auf den Namen {k['name']}. Falls es "
                                 "eine neue Reservation ist, bitte die Angaben ergänzen.")

    if fehlende_felder(r):
        if state.get("reservation_versuche", 0) >= MAX_RUECKFRAGEN * 2:   # 6 Pflichtfelder
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
    grund = f" ({r['grund']})" if r.get("grund") else ""
    return (f"{r['name']}{grund}, {r['personen']} Personen, {WOCHENTAGE[d.weekday()]} "
            f"{d:%d.%m.%Y} {r['schicht']}{zeit}, Tel. {r['telefon']}")


def beschreibung_db(x: dict) -> str:
    """Wie beschreibung, für eine Zeile aus der Tabelle reservations."""
    return beschreibung({"name": x["name"], "personen": x["persons"], "datum": x["date"],
                         "schicht": x["shift"], "uhrzeit": x.get("time"), "telefon": x["phone"],
                         "grund": x.get("occasion")})


def reservation_bestaetigung(state):
    r = state["pending_reservation"]
    antwort = interrupt({
        "typ": "reservation",
        "reservation": {k: r.get(k) for k in ("name", "telefon", "personen", "datum",
                                              "uhrzeit", "schicht", "grund")},
        "frage": f"Soll ich diese Reservation speichern? {beschreibung(r)}",
        "hinweis": "Die reservierten Personen werden bei der Wochenplanung zusätzlich zur "
                   "Gästeprognose eingeplant.",
    })
    decision = antwort.get("decision") if isinstance(antwort, dict) else str(antwort)
    if str(decision).strip().lower() in {"speichern", "ja", "ok"}:
        return {"decision": "speichern"}
    return {**_ende(state, "Reservation verworfen. Es wurde nichts gespeichert."),
            "decision": "verwerfen"}                     # im Zweifel nichts speichern


def reservation_speichern(state):
    r = state["pending_reservation"]
    rid = backends.save_reservation(r["name"], r["telefon"], r["personen"], r["datum"],
                                    r["schicht"], r.get("uhrzeit"), r.get("grund"))
    total = sum(x["persons"] for x in backends.get_reservations(r["datum"], 1)
                if x["shift"] == r["schicht"])
    text = (f"Reservation gespeichert: {beschreibung(r)}. "
            f"Reserviert in dieser Schicht total: {total} Personen. Sie werden bei der "
            "Wochenplanung zusätzlich zur Gästeprognose eingeplant.")
    return {"reservation_id": rid, "pending_reservation": None, "hinweis": None,
            "messages": [AIMessage(text)]}
