"""Reservationsagent: Erfassen, Rückfrage, Bestätigung, Summe in der Planung."""
import uuid
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import backends
from agent import routing as r
from agent.graph import build_graph
from agent.nodes import planung
from agent.schemas import Guard, Reservation, Route
from agent.state import initial_state
from planning.staffing import calculate_staffing
from tools import reservations as res

OK = Guard(erlaubt=True, grund="Reservation")
RES = Route(intent="reservation")
VOLL = Reservation(name="Meier", telefon="079 123 45 67", personen=4,
                   datum="2026-10-30", uhrzeit="19:00")


@pytest.fixture
def run():
    def start(text):
        graph = build_graph(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
        return graph, cfg, graph.invoke(initial_state(text), cfg)
    return start


def interrupt_value(result):
    return result["__interrupt__"][0].value


# --- tools/reservations.py ------------------------------------------------------------
@pytest.mark.parametrize("roh, erwartet", [
    ("079 123 45 67", "0791234567"), ("+41 79 123 45 67", "+41791234567"),
    ("0041-79-123-45-67", "+41791234567"), ("123", None), ("keine", None)])
def test_telefon_normalisieren(roh, erwartet):
    assert res.telefon_normalisieren(roh) == erwartet


@pytest.mark.parametrize("zeit, schicht", [("08:00", "morgen"), ("12:30", "morgen"),
                                           ("14:00", "nachmittag"), ("19:30", "nachmittag"),
                                           ("21:00", None), ("abends", None)])
def test_schicht_aus_uhrzeit(zeit, schicht):
    assert res.schicht_aus_uhrzeit(zeit) == schicht


def test_pruefen_findet_ruhetag_vergangenheit_und_personen():
    heute = date(2026, 10, 25)
    assert "datum" in res.pruefen({"datum": "2026-11-01"}, heute)          # Sonntag
    assert "datum" in res.pruefen({"datum": "2026-10-20"}, heute)          # vorbei
    assert "personen" in res.pruefen({"personen": 0}, heute)
    assert res.pruefen({"datum": "2026-10-30", "personen": 4, "telefon": "0791234567"}, heute) == {}


def test_speichern_lesen_und_summe_ohne_namen():
    res.save_reservation("Meier", "079 123 45 67", 4, "2026-10-30", "nachmittag", "19:00")
    res.save_reservation("Huber", "0791112233", 6, "2026-10-30", "nachmittag")
    res.save_reservation("Keller", "0791112233", 2, "2026-11-10", "morgen")   # ausserhalb

    woche = res.get_reservations("2026-10-26", 7)
    assert {x["name"]: x["phone"] for x in woche} == {"Meier": "0791234567", "Huber": "0791112233"}
    summe = res.reserved_per_shift(woche)
    assert summe == [{"date": "2026-10-30", "shift": "nachmittag", "persons": 10,
                      "type": "Reservationen"}]
    assert "Meier" not in str(summe)                                        # keine Personendaten


def test_reservationen_werden_zur_prognose_addiert():
    forecast = [{"date": "2026-10-30", "shift": "nachmittag", "guests": 50, "lower": 40, "upper": 60}]
    ohne = calculate_staffing(forecast)[0]
    mit = calculate_staffing(forecast, [{"date": "2026-10-30", "shift": "nachmittag",
                                         "persons": 10, "type": "Reservationen"}])[0]
    assert mit["guests_planned"] == ohne["guests_planned"] + 10 == 70
    assert mit["service"] == 3                                              # 70 / 30 aufgerundet


def test_staffing_node_liest_reservationen(monkeypatch):
    res.save_reservation("Meier", "0791234567", 4, "2026-10-30", "nachmittag")
    erhalten = {}

    def fake_staffing(forecast, events, corrections):
        erhalten["events"] = events
        return []

    monkeypatch.setattr(backends, "calculate_staffing", fake_staffing)
    out = planung.staffing({"forecast": [], "start_date": "2026-10-26",
                            "events": [{"date": "2026-10-29", "shift": "morgen", "persons": 40}]})
    assert {"date": "2026-10-30", "shift": "nachmittag", "persons": 4,
            "type": "Reservationen"} in erhalten["events"]
    assert len(erhalten["events"]) == 2                                     # Anlass bleibt
    assert out["reservations"][0]["persons"] == 4


# --- Routing ------------------------------------------------------------------------------
def test_routing():
    assert r.route_intent({"intent": "reservation"}) == "reservation"
    assert r.route_after_reservation({"pending_reservation": {"vollstaendig": True}}) \
        == "reservation_bestaetigung"
    assert r.route_after_reservation({"pending_reservation": {"vollstaendig": False}}) \
        == "reservation_rueckfrage"
    assert r.route_after_reservation({"escalation": "x"}) == "escalate"


# --- Graph -----------------------------------------------------------------------------------
def test_vollstaendige_reservation_erst_nach_bestaetigung_gespeichert(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL)
    graph, cfg, result = run("Reservation Meier, 4 Personen, Freitag 19 Uhr, 079 123 45 67")

    payload = interrupt_value(result)
    assert payload["typ"] == "reservation"
    assert payload["reservation"]["schicht"] == "nachmittag"                # aus Uhrzeit (Python)
    assert payload["reservation"]["telefon"] == "0791234567"
    assert backends.get_reservations() == []                                # noch nichts gespeichert

    result = graph.invoke(Command(resume={"decision": "speichern"}), cfg)
    gespeichert = backends.get_reservations()
    assert len(gespeichert) == 1 and gespeichert[0]["persons"] == 4
    assert "total: 4 Personen" in result["messages"][-1].content


def test_verwerfen_speichert_nichts(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL)
    graph, cfg, _ = run("Reservation Meier …")
    result = graph.invoke(Command(resume={"decision": "verwerfen"}), cfg)
    assert backends.get_reservations() == []
    assert "nichts gespeichert" in result["messages"][-1].content


def test_fehlende_telefonnummer_wird_erfragt(fake_llm, run):
    fake_llm(Guard=OK, Route=RES,
             Reservation=[VOLL.model_copy(update={"telefon": None}),
                          Reservation(telefon="079 999 88 77")])
    graph, cfg, result = run("Reservation Meier, 4 Personen, Freitag 19 Uhr")

    frage = interrupt_value(result)
    assert frage["typ"] == "rueckfrage" and "Telefonnummer" in frage["frage"]
    result = graph.invoke(Command(resume="079 999 88 77"), cfg)
    payload = interrupt_value(result)
    assert payload["typ"] == "reservation"
    assert payload["reservation"]["name"] == "Meier"                       # bekannte Angaben bleiben
    assert payload["reservation"]["telefon"] == "0799998877"


def test_ruhetag_wird_abgelehnt_und_neu_erfragt(fake_llm, run):
    fake_llm(Guard=OK, Route=RES,
             Reservation=[VOLL.model_copy(update={"datum": "2026-11-01"}),
                          Reservation(datum="2026-10-31")])
    graph, cfg, result = run("Reservation Meier, Sonntag")
    frage = interrupt_value(result)["frage"]
    assert "Ruhetag" in frage and "Datum" in frage
    result = graph.invoke(Command(resume="dann Samstag"), cfg)
    assert interrupt_value(result)["reservation"]["datum"] == "2026-10-31"


def test_reservation_eskaliert_nach_zu_vielen_rueckfragen(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=Reservation(name="Meier"))
    graph, cfg, result = run("Reservation Meier")
    for _ in range(6):
        if "__interrupt__" not in result:
            break
        result = graph.invoke(Command(resume="weiss nicht"), cfg)
    assert "Betriebsleitung" in result["messages"][-1].content
    assert backends.get_reservations() == []


def test_wochenplanung_zeigt_reservationen(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 4, "2026-10-30", "nachmittag")
    fake_llm(Guard=OK, Route=Route(intent="wochenplanung"))
    graph, cfg, result = run("Plane die Woche")
    assert interrupt_value(result)["typ"] == "freigabe"
    values = graph.get_state(cfg).values
    assert values["reservations"] == [{"date": "2026-10-30", "shift": "nachmittag",
                                       "persons": 4, "type": "Reservationen"}]
