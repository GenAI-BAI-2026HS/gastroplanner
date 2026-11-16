"""Reservationsagent: Erfassen, Rückfrage, Bestätigung, Summe in der Planung.

Regeln: Reservationen nur für Anlässe ab 10 Personen, mit Grund; jede Reservation wird
zusätzlich zur Prognose eingeplant. Reservationen sind auch beim «anpassen» möglich.
"""
import uuid
from datetime import date

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

from agent import backends
from agent import routing as r
from agent.graph import build_graph
from agent.nodes import planung
from agent.schemas import Guard, Korrektur, Reservation, Route
from agent.state import initial_state
from planning.staffing import calculate_staffing
from tools import reservations as res
from tools.plans import count_approved_rows

OK = Guard(erlaubt=True, grund="Reservation")
RES = Route(intent="reservation")
WOCHE = Route(intent="wochenplanung")
VOLL = Reservation(name="Meier", telefon="079 123 45 67", personen=25, datum="2026-10-30",
                   uhrzeit="19:00", grund="Firmenessen")


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


@pytest.mark.parametrize("personen, ok", [(1, False), (9, False), (10, True), (40, True)])
def test_reservierbar_erst_ab_zehn(personen, ok):
    assert res.reservierbar(personen) is ok


def test_pruefen_findet_ruhetag_vergangenheit_und_personen():
    heute = date(2026, 10, 25)
    assert "datum" in res.pruefen({"datum": "2026-11-01"}, heute)          # Sonntag
    assert "datum" in res.pruefen({"datum": "2026-10-20"}, heute)          # vorbei
    assert "personen" in res.pruefen({"personen": 0}, heute)
    assert res.pruefen({"datum": "2026-10-30", "personen": 12, "telefon": "0791234567"}, heute) == {}


def test_speichern_lesen_und_summe_ohne_namen():
    res.save_reservation("Meier", "079 123 45 67", 12, "2026-10-30", "nachmittag", "19:00", "Geburtstag")
    res.save_reservation("Huber", "0791112233", 30, "2026-10-30", "nachmittag", occasion="Firma")
    res.save_reservation("Keller", "0791112233", 10, "2026-11-10", "morgen")   # ausserhalb

    woche = res.get_reservations("2026-10-26", 7)
    assert {x["name"]: x["occasion"] for x in woche} == {"Meier": "Geburtstag", "Huber": "Firma"}
    summe = res.reserved_per_shift(woche)
    assert summe == [{"date": "2026-10-30", "shift": "nachmittag", "persons": 42,
                      "type": "Reservationen"}]
    assert "Meier" not in str(summe)                                        # keine Personendaten


def test_unter_zehn_personen_wird_nicht_gespeichert():
    with pytest.raises(ValueError, match="ab 10 Personen"):
        res.save_reservation("Meier", "0791234567", 8, "2026-10-30", "nachmittag")


def test_alte_datenbank_bekommt_spalte_grund(tmp_path):
    import sqlite3
    db = tmp_path / "alt.db"
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE reservations (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, "
                "phone TEXT NOT NULL, persons INT NOT NULL, date TEXT NOT NULL, shift TEXT NOT NULL, "
                "time TEXT, created_at TEXT NOT NULL)")
    con.execute("INSERT INTO reservations VALUES (1,'Alt','0791234567',35,'2026-10-30','morgen',NULL,'x')")
    con.commit()
    con.close()
    assert res.get_reservations(db_path=db)[0]["occasion"] is None
    res.save_reservation("Neu", "0791234567", 12, "2026-10-30", "morgen", occasion="Verein", db_path=db)
    assert [x["occasion"] for x in res.get_reservations(db_path=db)] == [None, "Verein"]


def test_reservationen_werden_zur_prognose_addiert():
    forecast = [{"date": "2026-10-30", "shift": "nachmittag", "guests": 50, "lower": 40, "upper": 60}]
    ohne = calculate_staffing(forecast)[0]
    mit = calculate_staffing(forecast, [{"date": "2026-10-30", "shift": "nachmittag",
                                         "persons": 12, "type": "Reservationen"}])[0]
    assert mit["guests_planned"] == ohne["guests_planned"] + 12 == 72
    assert mit["service"] == 3                                              # 72 / 30 aufgerundet


def test_staffing_node_addiert_reservationen(monkeypatch):
    res.save_reservation("Meier", "0791234567", 12, "2026-10-30", "nachmittag")
    res.save_reservation("Huber", "0791112233", 20, "2026-10-30", "nachmittag")
    erhalten = {}

    def fake_staffing(forecast, events, corrections):
        erhalten["events"] = events
        return []

    monkeypatch.setattr(backends, "calculate_staffing", fake_staffing)
    out = planung.staffing({"forecast": [], "start_date": "2026-10-26",
                            "events": [{"date": "2026-10-29", "shift": "morgen", "persons": 40}]})
    assert erhalten["events"] == [
        {"date": "2026-10-29", "shift": "morgen", "persons": 40},          # Anlass bleibt
        {"date": "2026-10-30", "shift": "nachmittag", "persons": 32, "type": "Reservationen"}]
    assert out["reservations"][0]["persons"] == 32


def test_finde_bestehende():
    bestehend = [{"id": 1, "name": "Meier", "phone": "0791234567", "persons": 25,
                  "date": "2026-10-30", "shift": "nachmittag", "time": None}]
    basis = {"datum": "2026-10-30", "schicht": "nachmittag", "personen": 25}
    assert res.finde_bestehende({**basis, "name": "meier"}, bestehend)[0]["id"] == 1
    assert res.finde_bestehende({**basis, "telefon": "079 123 45 67"}, bestehend)[0]["id"] == 1
    assert res.finde_bestehende({**basis, "name": "Huber"}, bestehend) == (None, bestehend)
    assert res.finde_bestehende({**basis, "personen": 30}, bestehend) == (None, [])
    assert res.finde_bestehende({**basis, "schicht": "morgen", "name": "Meier"}, bestehend) == (None, [])


# --- Routing ------------------------------------------------------------------------------
def test_routing():
    assert r.route_intent({"intent": "reservation"}) == "reservation"
    assert r.route_after_reservation({"pending_reservation": {"vollstaendig": True}}) \
        == "reservation_bestaetigung"
    assert r.route_after_reservation({"pending_reservation": {"vollstaendig": False}}) \
        == "reservation_rueckfrage"
    assert r.route_after_reservation({"escalation": "x"}) == "escalate"
    assert r.route_after_reservation({"reservation_abgelehnt": "unter_minimum"}) == "end"
    assert r.route_after_reservation({"reservation_abgelehnt": "unter_minimum",
                                      "reservation_aus_anpassung": True}) == "approval"
    assert r.route_after_reservation_speichern({"reservation_aus_anpassung": True}) == "staffing"
    assert r.route_after_reservation_speichern({}) == "end"
    assert r.route_after_korrektur({"reservation_aus_anpassung": True}) == "reservation"


# --- Graph: neue Anfrage --------------------------------------------------------------------
def test_vollstaendige_reservation_erst_nach_bestaetigung_gespeichert(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL)
    graph, cfg, result = run("Firmenessen Meier, 25 Personen, Freitag 19 Uhr, 079 123 45 67")

    payload = interrupt_value(result)
    assert payload["typ"] == "reservation"
    assert payload["reservation"]["schicht"] == "nachmittag"                # aus Uhrzeit (Python)
    assert payload["reservation"]["telefon"] == "0791234567"
    assert payload["reservation"]["grund"] == "Firmenessen"
    assert backends.get_reservations() == []                                # noch nichts gespeichert

    result = graph.invoke(Command(resume={"decision": "speichern"}), cfg)
    gespeichert = backends.get_reservations()
    assert len(gespeichert) == 1 and gespeichert[0]["persons"] == 25
    assert gespeichert[0]["occasion"] == "Firmenessen"
    assert "total: 25 Personen" in result["messages"][-1].content


def test_unter_zehn_personen_wird_abgelehnt_ohne_name_zu_fragen(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=RES,
                    Reservation=Reservation(personen=6, datum="2026-10-30", uhrzeit="19:00"))
    _, _, result = run("Freitag 19 Uhr kommen wir zu sechst")

    assert "__interrupt__" not in result                                    # keine Rückfrage
    assert "ab 10 Personen" in result["messages"][-1].content
    assert backends.get_reservations() == []
    assert fake.count("Reservation") == 1


def test_grund_wird_erfragt(fake_llm, run):
    fake_llm(Guard=OK, Route=RES,
             Reservation=[VOLL.model_copy(update={"grund": None}), Reservation(grund="Geburtstag")])
    graph, cfg, result = run("Meier, 25 Personen, Freitag 19 Uhr, 079 123 45 67")

    frage = interrupt_value(result)
    assert frage["typ"] == "rueckfrage" and "Grund" in frage["frage"]
    result = graph.invoke(Command(resume="Geburtstag"), cfg)
    assert interrupt_value(result)["reservation"]["grund"] == "Geburtstag"


def test_personen_vor_name_und_telefon_erfragt(fake_llm, run):
    fake_llm(Guard=OK, Route=RES,
             Reservation=[Reservation(datum="2026-10-30", uhrzeit="19:00", grund="Geburtstag"),
                          Reservation(personen=5)])
    graph, cfg, result = run("Freitag 19 Uhr Geburtstag")
    assert "wie viele Personen" in interrupt_value(result)["frage"]
    result = graph.invoke(Command(resume="5"), cfg)
    assert "ab 10 Personen" in result["messages"][-1].content               # nie nach Name gefragt


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
    graph, cfg, result = run("Firmenessen Meier, 25 Personen, Freitag 19 Uhr")

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
    graph, cfg, result = run("Firmenessen Meier, Sonntag")
    frage = interrupt_value(result)["frage"]
    assert "Ruhetag" in frage and "Datum" in frage
    result = graph.invoke(Command(resume="dann Samstag"), cfg)
    assert interrupt_value(result)["reservation"]["datum"] == "2026-10-31"


def test_reservation_eskaliert_nach_zu_vielen_rueckfragen(fake_llm, run):
    fake_llm(Guard=OK, Route=RES, Reservation=Reservation(name="Meier"))
    graph, cfg, result = run("Reservation Meier")
    for _ in range(10):
        if "__interrupt__" not in result:
            break
        result = graph.invoke(Command(resume="weiss nicht"), cfg)
    assert "Betriebsleitung" in result["messages"][-1].content
    assert backends.get_reservations() == []


def test_bestehende_reservation_wird_nicht_doppelt_erfasst(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 25, "2026-10-30", "nachmittag", "19:00")
    fake_llm(Guard=OK, Route=RES, Reservation=VOLL)
    _, _, result = run("Meier kommt Freitag um 19 Uhr mit 25 Personen")

    assert "__interrupt__" not in result
    assert "bereits im System" in result["messages"][-1].content
    assert len(backends.get_reservations()) == 1


def test_gleiche_personenzahl_ohne_name_fragt_nach(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 25, "2026-10-30", "nachmittag")
    fake_llm(Guard=OK, Route=RES,
             Reservation=[VOLL.model_copy(update={"name": None, "telefon": None}),
                          Reservation(name="Huber", telefon="078 555 66 77")])
    graph, cfg, result = run("Freitag 19 Uhr Firmenessen mit 25 Personen")

    frage = interrupt_value(result)["frage"]
    assert "bereits eine Reservation" in frage and "Meier" in frage and "Namen" in frage
    result = graph.invoke(Command(resume="Nein, neu: Huber, 078 555 66 77"), cfg)
    assert interrupt_value(result)["typ"] == "reservation"                  # neue Reservation


def test_wochenplanung_zeigt_reservationen(fake_llm, run):
    backends.save_reservation("Meier", "0791234567", 25, "2026-10-30", "nachmittag")
    fake_llm(Guard=OK, Route=WOCHE)
    graph, cfg, result = run("Plane die Woche")
    assert interrupt_value(result)["typ"] == "freigabe"
    assert graph.get_state(cfg).values["reservations"] == [
        {"date": "2026-10-30", "shift": "nachmittag", "persons": 25, "type": "Reservationen"}]


# --- Graph: Reservation beim «anpassen» ------------------------------------------------------
RES_FEEDBACK = Korrektur(art="reservation", eindeutig=True)


def test_reservation_beim_anpassen_wird_erfasst_und_neu_gerechnet(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=WOCHE, Korrektur=RES_FEEDBACK,
                    Reservation=[VOLL.model_copy(update={"telefon": None}),
                                 Reservation(telefon="079 123 45 67")])
    graph, cfg, result = run("Plane die Woche")
    assert interrupt_value(result)["typ"] == "freigabe"

    result = graph.invoke(Command(resume={"decision": "anpassen", "feedback":
                                          "Freitag 19 Uhr kommt Firma Meier mit 25 Personen"}), cfg)
    assert "Telefonnummer" in interrupt_value(result)["frage"]             # Rückfrage wie sonst
    result = graph.invoke(Command(resume="079 123 45 67"), cfg)
    assert interrupt_value(result)["typ"] == "reservation"
    result = graph.invoke(Command(resume={"decision": "speichern"}), cfg)

    payload = interrupt_value(result)
    assert payload["typ"] == "freigabe"                                     # zurück zur Freigabe
    assert len(backends.get_reservations()) == 1
    assert graph.get_state(cfg).values["reservations"][0]["persons"] == 25  # neu gerechnet
    assert fake.count("text") == 2                                          # explain lief erneut
    assert backends.get_corrections() == []                                 # keine Korrektur
    assert count_approved_rows() == 0                                       # Plan erst nach Freigabe

    graph.invoke(Command(resume={"decision": "freigeben"}), cfg)
    assert count_approved_rows() == 12


def test_kleine_reservation_beim_anpassen_hinweis_in_freigabe(fake_llm, run):
    fake_llm(Guard=OK, Route=WOCHE, Korrektur=RES_FEEDBACK,
             Reservation=VOLL.model_copy(update={"personen": 4}))
    graph, cfg, _ = run("Plane die Woche")
    result = graph.invoke(Command(resume={"decision": "anpassen",
                                          "feedback": "Freitag kommen noch 4 Personen"}), cfg)
    payload = interrupt_value(result)
    assert payload["typ"] == "freigabe"
    assert "ab 10 Personen" in payload["hinweis"]
    assert backends.get_reservations() == []
