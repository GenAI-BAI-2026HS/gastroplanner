"""Bestehende Reservation ändern oder stornieren.

    reservation_aendern ─unklar/ungültig─▶ reservation_aendern_rueckfrage ─▶ reservation_aendern
        │ klar                            └ zu viele Rückfragen ─▶ END (nichts geändert)
        ▼
    reservation_aendern_bestaetigung (interrupt, zeigt vorher/nachher)
        ├ speichern ─▶ reservation_aendern_speichern ─▶ END
        └ verwerfen ─▶ END (nichts geändert)

- reservation_aendern: LLM bestimmt, welche Reservation gemeint ist (Nummer oder Name) und
  welche Angaben neu sind (strukturiert). Python sucht die Reservation, rechnet den neuen
  Stand und prüft ihn mit denselben Regeln wie beim Erfassen (ab 10 Personen, kein
  Ruhetag, gültige Telefonnummer, Schicht aus der Uhrzeit).
- Nur kommende Reservationen lassen sich ändern; vergangene sind abgeschlossen.
- Gespeichert wird erst nach Bestätigung, nur in reservation_aendern_speichern.
"""
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langgraph.types import interrupt

import config
from agent import backends, llm
from agent.nodes import supervisor
from agent.nodes.reservation import beschreibung
from agent.prompts import RESERVATION_AENDERN_PROMPT
from agent.routing import MAX_RUECKFRAGEN
from agent.schemas import ReservationAenderung
from tools.reservations import pruefen, reservierbar, schicht_aus_uhrzeit, telefon_normalisieren

FELDER = ("personen", "datum", "uhrzeit", "schicht", "grund", "name", "telefon")
FRAGE_WELCHE = "Welche Reservation möchten Sie ändern? Bitte nennen Sie die Nummer oder den Namen."
FRAGE_WAS = ("Was möchten Sie an der Reservation {r} ändern (Personen, Datum, Uhrzeit, Grund, "
             "Name, Telefon) oder soll sie storniert werden?")


def _als_reservation(x: dict) -> dict:
    """Zeile aus der Datenbank → Felder wie im Reservationsagenten."""
    return {"name": x["name"], "telefon": x["phone"], "personen": x["persons"],
            "datum": x["date"], "schicht": x["shift"], "uhrzeit": x.get("time"),
            "grund": x.get("occasion")}


def _liste(kommende: list[dict]) -> str:
    return "\n".join(f"Nr. {x['id']}: {x['name']}, {x['date']}, {x['shift']}, {x['time'] or '-'}, "
                     f"{x['persons']} Personen, {x.get('occasion') or '-'}" for x in kommende) or "(keine)"


def _frage(state, p: dict, frage: str) -> dict:
    """Rückfrage stellen oder nach zu vielen Versuchen ohne Änderung beenden."""
    if state.get("aenderung_versuche", 0) >= MAX_RUECKFRAGEN:
        return {"pending_aenderung": None, "messages": [AIMessage(
            "Ich konnte die Änderung nicht eindeutig zuordnen. Es wurde nichts geändert.")]}
    return {"pending_aenderung": {**p, "frage": frage, "vollstaendig": False}}


def reservation_aendern(state):
    kommende = backends.list_reservations(supervisor.heute(), kommend=True)
    bekannt = {k: v for k, v in (state.get("pending_aenderung") or {}).items()
               if k in ReservationAenderung.model_fields}
    extraktor = llm.get_llm().with_structured_output(ReservationAenderung)
    neu = extraktor.invoke([
        SystemMessage(RESERVATION_AENDERN_PROMPT.format(
            liste=_liste(kommende), bekannt=bekannt or "keine", **supervisor.datum_kontext())),
        *state["messages"][-6:],
    ])
    p = {**bekannt, **{k: v for k, v in neu.model_dump().items() if v not in (None, "")}}

    # 1. Welche Reservation? Nummer vor Name; Python sucht, nicht das LLM.
    ziel = None
    if p.get("reservation_nr") is not None:
        ziel = next((x for x in kommende if x["id"] == p["reservation_nr"]), None)
        if ziel is None:
            nr = p.pop("reservation_nr")
            return _frage(state, p, f"Eine kommende Reservation Nr. {nr} gibt es nicht. {FRAGE_WELCHE}")
    elif p.get("suchname"):
        such = p["suchname"].strip().lower()
        treffer = [x for x in kommende if such in x["name"].lower() or x["name"].lower() in such]
        if len(treffer) == 1:
            ziel = treffer[0]
        elif len(treffer) > 1:
            auswahl = "; ".join(f"Nr. {x['id']} am {x['date']}" for x in treffer)
            return _frage(state, p, f"Es gibt mehrere Reservationen auf «{p['suchname']}» ({auswahl}). "
                                    "Welche Nummer meinen Sie?")
        else:
            p.pop("suchname")
            return _frage(state, p, f"Unter diesem Namen gibt es keine kommende Reservation. {FRAGE_WELCHE}")
    if ziel is None:
        return _frage(state, p, FRAGE_WELCHE)
    p["reservation_nr"] = ziel["id"]
    alt = _als_reservation(ziel)

    # 2. Stornieren?
    if p.get("aktion") == "stornieren":
        return {"pending_aenderung": {**p, "vollstaendig": True, "alt": alt, "neu": None}}

    # 3. Neuer Stand = alt + Änderungen (Python rechnet)
    aenderungen = {k: p[k] for k in FELDER if p.get(k) not in (None, "")}
    if not aenderungen:
        return _frage(state, p, FRAGE_WAS.format(r=beschreibung(alt)))
    stand = {**alt, **aenderungen}
    if "uhrzeit" in aenderungen:
        stand["schicht"] = schicht_aus_uhrzeit(aenderungen["uhrzeit"]) or aenderungen.get("schicht")
    elif "schicht" in aenderungen and alt.get("uhrzeit"):
        stand["uhrzeit"] = None                      # alte Uhrzeit passt nicht zur neuen Schicht

    fehler = pruefen(stand, supervisor.heute())
    if "uhrzeit" not in fehler and not stand.get("schicht"):
        fehler["uhrzeit"] = "Die Uhrzeit liegt ausserhalb der Öffnungszeiten (08–20 Uhr)."
    if stand.get("personen") is not None and "personen" not in fehler \
            and not reservierbar(stand["personen"]):
        fehler["personen"] = (f"Reservationen gibt es nur ab {config.RESERVATION_MIN_PERSONEN} "
                              "Personen; bei weniger Personen bitte stornieren.")
    if fehler:
        for feld in fehler:                          # ungültige Angabe verwerfen und neu fragen
            p.pop(feld, None)
        return _frage(state, p, " ".join(fehler.values()) + " Was soll stattdessen gelten?")
    if stand == alt:
        return _frage(state, p, "Das entspricht der bisherigen Reservation. "
                                + FRAGE_WAS.format(r=beschreibung(alt)))

    stand["telefon"] = telefon_normalisieren(stand["telefon"])
    return {"pending_aenderung": {**p, "aktion": "aendern", "vollstaendig": True,
                                  "alt": alt, "neu": stand}}


def reservation_aendern_rueckfrage(state):
    frage = state["pending_aenderung"]["frage"]
    antwort = interrupt({"typ": "rueckfrage", "frage": frage})
    return {"messages": [AIMessage(frage), HumanMessage(str(antwort))],
            "aenderung_versuche": state.get("aenderung_versuche", 0) + 1}


def reservation_aendern_bestaetigung(state):
    p = state["pending_aenderung"]
    if p["aktion"] == "stornieren":
        frage = f"Soll ich diese Reservation stornieren? Nr. {p['reservation_nr']}: {beschreibung(p['alt'])}"
    else:
        frage = (f"Soll ich die Reservation Nr. {p['reservation_nr']} ändern? "
                 f"Vorher: {beschreibung(p['alt'])}. Neu: {beschreibung(p['neu'])}")
    antwort = interrupt({"typ": "reservation_aenderung", "aktion": p["aktion"],
                         "nr": p["reservation_nr"], "vorher": p["alt"], "nachher": p["neu"],
                         "frage": frage})
    decision = antwort.get("decision") if isinstance(antwort, dict) else str(antwort)
    if str(decision).strip().lower() in {"speichern", "ja", "ok"}:
        return {"decision": "speichern"}
    return {"decision": "verwerfen", "pending_aenderung": None,       # im Zweifel nichts ändern
            "messages": [AIMessage("Änderung verworfen. Die Reservation bleibt unverändert.")]}


def reservation_aendern_speichern(state):
    p = state["pending_aenderung"]
    nr = p["reservation_nr"]
    if p["aktion"] == "stornieren":
        backends.delete_reservation(nr)
        text = f"Reservation Nr. {nr} storniert: {beschreibung(p['alt'])}."
    else:
        n = p["neu"]
        backends.update_reservation(nr, n["name"], n["telefon"], n["personen"], n["datum"],
                                    n["schicht"], n.get("uhrzeit"), n.get("grund"))
        text = f"Reservation Nr. {nr} geändert: {beschreibung(n)}."
    return {"pending_aenderung": None, "messages": [AIMessage(
        text + " Die nächste Wochenplanung berücksichtigt den neuen Stand.")]}
