"""Bestehende Reservationen ansehen, ändern und stornieren."""
import uuid
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import backends
from agent import routing as r
from agent.graph import build_graph
from agent.schemas import Guard, ReservationAenderung, Route
from agent.state import initial_state
from tools import reservations as res

HEUTE = date(2026, 10, 25)
OK = Guard(erlaubt=True, grund="Reservation")
AENDERN = Route(intent="reservation_aendern")


@pytest.fixture
def run():
    def start(text):
        graph = build_graph(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
        return graph, cfg, graph.invoke(initial_state(text), cfg)
    return start


@pytest.fixture
def keller():
    """Kommende Reservation Nr. 1 (Fr 30.10. 19:00, 20 Personen) und eine vergangene."""
    rid = res.save_reservation("Keller", "0622123456", 20, "2026-10-30", "nachmittag", "19:00", "Geburtstag")
    res.save_reservation("Alt", "0791234567", 15, "2026-10-01", "morgen", occasion="Firma")
    return rid


def interrupt_value(result):
    return result["__interrupt__"][0].value


# --- tools/reservations.py ------------------------------------------------------------
def test_kommende_und_vergangene(keller):
    assert [x["name"] for x in res.list_reservations(HEUTE, kommend=True)] == ["Keller"]
    assert [x["name"] for x in res.list_reservations(HEUTE, kommend=False)] == ["Alt"]


def test_update_und_delete(keller):
    res.update_reservation(keller, "Keller", "062 212 34 56", 25, "2026-10-29", "morgen", "12:00", "Geburtstag")
    x = res.get_reservation(keller)
    assert (x["persons"], x["date"], x["shift"], x["time"]) == (25, "2026-10-29", "morgen", "12:00")
    with pytest.raises(ValueError, match="ab 10 Personen"):
        res.update_reservation(keller, "Keller", "0622123456", 5, "2026-10-29", "morgen")
    res.delete_reservation(keller)
    assert res.get_reservation(keller) is None
    with pytest.raises(ValueError, match="gibt es nicht"):
        res.delete_reservation(keller)


# --- Routing ------------------------------------------------------------------------------
def test_routing():
    assert r.route_intent({"intent": "reservation_aendern"}) == "reservation_aendern"
    assert r.route_after_reservation_aendern({"pending_aenderung": None}) == "end"
    assert r.route_after_reservation_aendern({"pending_aenderung": {"vollstaendig": True}}) \
        == "reservation_aendern_bestaetigung"
    assert r.route_after_reservation_aendern({"pending_aenderung": {"vollstaendig": False}}) \
        == "reservation_aendern_rueckfrage"


# --- Graph --------------------------------------------------------------------------------
def test_personenzahl_aendern_erst_nach_bestaetigung(fake_llm, run, keller):
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=ReservationAenderung(reservation_nr=keller, aktion="aendern", personen=25))
    graph, cfg, result = run(f"Reservation Nr. {keller}: es kommen 25 statt 20")

    p = interrupt_value(result)
    assert p["typ"] == "reservation_aenderung" and p["aktion"] == "aendern"
    assert p["vorher"]["personen"] == 20 and p["nachher"]["personen"] == 25
    assert res.get_reservation(keller)["persons"] == 20                    # noch unverändert

    result = graph.invoke(Command(resume={"decision": "speichern"}), cfg)
    assert res.get_reservation(keller)["persons"] == 25
    assert "geändert" in result["messages"][-1].content


def test_bearbeiten_ohne_angabe_fragt_was(fake_llm, run, keller):
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=[ReservationAenderung(reservation_nr=keller),
                                   ReservationAenderung(uhrzeit="12:00", datum="2026-10-29")])
    graph, cfg, result = run(f"Ich möchte die Reservation Nr. {keller} bearbeiten.")

    frage = interrupt_value(result)["frage"]
    assert "Was möchten Sie" in frage and "Keller" in frage
    result = graph.invoke(Command(resume="Donnerstag 12 Uhr"), cfg)
    p = interrupt_value(result)
    assert p["nachher"]["datum"] == "2026-10-29"
    assert p["nachher"]["schicht"] == "morgen"                              # aus Uhrzeit (Python)


def test_stornieren(fake_llm, run, keller):
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=ReservationAenderung(suchname="Keller", aktion="stornieren"))
    graph, cfg, result = run("Storniere die Reservation Keller")

    p = interrupt_value(result)
    assert p["aktion"] == "stornieren" and p["nachher"] is None
    result = graph.invoke(Command(resume={"decision": "speichern"}), cfg)
    assert res.get_reservation(keller) is None
    assert "storniert" in result["messages"][-1].content


def test_abbrechen_aendert_nichts(fake_llm, run, keller):
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=ReservationAenderung(reservation_nr=keller, aktion="stornieren"))
    graph, cfg, _ = run("Storniere Nr. 1")
    result = graph.invoke(Command(resume={"decision": "verwerfen"}), cfg)
    assert res.get_reservation(keller) is not None
    assert "unverändert" in result["messages"][-1].content


def test_unter_zehn_personen_wird_neu_gefragt(fake_llm, run, keller):
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=[ReservationAenderung(reservation_nr=keller, personen=6),
                                   ReservationAenderung(personen=12)])
    graph, cfg, result = run("Keller kommt nur noch zu sechst")
    assert "ab 10 Personen" in interrupt_value(result)["frage"]
    result = graph.invoke(Command(resume="dann 12"), cfg)
    assert interrupt_value(result)["nachher"]["personen"] == 12


def test_unbekannte_nummer_und_vergangene_reservation(fake_llm, run, keller):
    alt_id = res.list_reservations(HEUTE, kommend=False)[0]["id"]
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=ReservationAenderung(reservation_nr=alt_id, personen=30))
    graph, cfg, result = run(f"Reservation Nr. {alt_id} auf 30 Personen")
    assert "gibt es nicht" in interrupt_value(result)["frage"]             # vergangene: nicht änderbar
    for _ in range(5):
        if "__interrupt__" not in result:
            break
        result = graph.invoke(Command(resume="weiss nicht"), cfg)
    assert "nichts geändert" in result["messages"][-1].content
    assert res.get_reservation(alt_id)["persons"] == 15


def test_mehrdeutiger_name_fragt_nach_nummer(fake_llm, run, keller):
    zweite = res.save_reservation("Keller AG", "0629999999", 30, "2026-10-31", "morgen")
    fake_llm(Guard=OK, Route=AENDERN,
             ReservationAenderung=[ReservationAenderung(suchname="Keller", personen=22),
                                   ReservationAenderung(reservation_nr=zweite)])
    graph, cfg, result = run("Keller kommt mit 22 Personen")
    assert "mehrere" in interrupt_value(result)["frage"]
    result = graph.invoke(Command(resume=f"Nr. {zweite}"), cfg)
    p = interrupt_value(result)
    assert p["nr"] == zweite and p["nachher"]["personen"] == 22
