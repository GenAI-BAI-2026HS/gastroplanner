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
                      "persons_zusatz": 6, "type": "Reservationen"}]          # nur Huber (6) zusätzlich
    assert "Meier" not in str(summe)                                        # keine Personendaten


@pytest.mark.parametrize("personen, zusaetzlich", [(1, False), (4, False), (5, False),
                                                   (6, True), (20, True)])
def test_ueber_fuenf_personen_zusaetzlich(personen, zusaetzlich):
    assert res.ist_zusaetzlich(personen) is zusaetzlich


def test_als_anlaesse_nur_zusaetzlicher_teil():
    per_shift = [{"date": "2026-10-30", "shift": "nachmittag", "persons": 10, "persons_zusatz": 6},
                 {"date": "2026-10-31", "shift": "morgen", "persons": 4, "persons_zusatz": 0}]
    assert res.als_anlaesse(per_shift) == [{"date": "2026-10-30", "shift": "nachmittag",
                                            "persons": 6, "type": "Reservationen über 5 Personen"}]


def test_finde_bestehende():
    bestehend = [{"id": 1, "name": "Meier", "phone": "0791234567", "persons": 4,
                  "date": "2026-10-30", "shift": "nachmittag", "time": None}]
    basis = {"datum": "2026-10-30", "schicht": "nachmittag", "personen": 4}
    assert res.finde_bestehende({**basis, "name": "meier"}, bestehend)[0]["id"] == 1
    assert res.finde_bestehende({**basis, "telefon": "079 123 45 67"}, bestehend)[0]["id"] == 1
    assert res.finde_bestehende({**basis, "name": "Huber"}, bestehend) == (None, bestehend)
    assert res.finde_bestehende({**basis, "personen": 6}, bestehend) == (None, [])
    assert res.finde_bestehende({**basis, "schicht": "morgen", "name": "Meier"}, bestehend) == (None, [])


def test_reservationen_werden_zur_prognose_addiert():
    forecast = [{"date": "2026-10-30", "shift": "nachmittag", "guests": 50, "lower": 40, "upper": 60}]
    ohne = calculate_staffing(forecast)[0]
    mit = calculate_staffing(forecast, [{"date": "2026-10-30", "shift": "nachmittag",
                                         "persons": 10, "type": "Reservationen"}])[0]
    assert mit["guests_planned"] == ohne["guests_planned"] + 10 == 70
    assert mit["service"] == 3                                              # 70 / 30 aufgerundet


def test_staffing_node_addiert_nur_reservationen_ueber_fuenf(monkeypatch):
    res.save_reservation("Meier", "0791234567", 4, "2026-10-30", "nachmittag")
    res.save_reservation("Huber", "0791112233", 12, "2026-10-30", "nachmittag")
    res.save_reservation("Keller", "0792223344", 3, "2026-10-31", "morgen")
    erhalten = {}

    def fake_staffing(forecast, events, corrections):
        erhalten["events"] = events
        return []

    monkeypatch.setattr(backends, "calculate_staffing", fake_staffing)
    out = planung.staffing({"forecast": [], "start_date": "2026-10-26",
                            "events": [{"date": "2026-10-29", "shift": "morgen", "persons": 40}]})
    assert erhalten["events"] == [
        {"date": "2026-10-29", "shift": "morgen", "persons": 40},          # Anlass bleibt
        {"date": "2026-10-30", "shift": "nachmittag", "persons": 12,
         "type": "Reservationen über 5 Personen"}]                         # Meier (4) und Keller (3) nicht
    # Angezeigt werden trotzdem alle Reservationen
    assert [(x["date"], x["persons"], x["persons_zusatz"]) for x in out["reservations"]] == \
        [("2026-10-30", 16, 12), ("2026-10-31", 3, 0)]


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
                                       "persons": 4, "persons_zusatz": 0, "type": "Reservationen"}]


def test_bestehende_reservation_wird_nicht_doppelt_erfasst(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 4, "2026-10-30", "nachmittag", "19:00")
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL)
    _, _, result = run("Meier kommt Freitag um 19 Uhr zu viert")

    assert "__interrupt__" not in result                                    # keine Bestätigung nötig
    assert "bereits im System" in result["messages"][-1].content
    assert len(backends.get_reservations()) == 1


def test_gleiche_personenzahl_ohne_name_fragt_nach(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 4, "2026-10-30", "nachmittag")
    fake_llm(Guard=OK, Route=RES,
             Reservation=[VOLL.model_copy(update={"name": None, "telefon": None}),
                          Reservation(name="Huber", telefon="078 555 66 77")])
    graph, cfg, result = run("Freitag 19 Uhr kommen 4 Personen")

    frage = interrupt_value(result)["frage"]
    assert "bereits eine Reservation" in frage and "Meier" in frage and "Namen" in frage
    result = graph.invoke(Command(resume="Nein, neu: Huber, 078 555 66 77"), cfg)
    assert interrupt_value(result)["typ"] == "reservation"                  # neue Reservation
    assert "nicht zusätzlich eingeplant" in interrupt_value(result)["hinweis"]


def test_grosse_reservation_hinweis_zusaetzlich(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL.model_copy(update={"personen": 20}))
    _, _, result = run("Gruppe Meier, 20 Personen, Freitag 19 Uhr, 079 123 45 67")
    assert "zusätzlich zur Gästeprognose" in interrupt_value(result)["hinweis"]
