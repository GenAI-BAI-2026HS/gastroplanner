"""Tests für das Langzeit-Memory (C5): tools/memory.py und der Node korrektur.

Die Datenbank ist pro Test eine eigene temporäre Datei (conftest.py setzt config.DB_PATH).
"""
import pytest
from langgraph.types import Command

from agent import backends
from agent.schemas import Korrektur
from planning.staffing import calculate_staffing
from tools import memory
from tests.test_graph import OK, WOCHE, interrupt_value, run, service_freitag_nachmittag  # noqa: F401  (run ist eine Fixture)


# --- Speichern und Lesen --------------------------------------------------------
def test_leer_am_anfang():
    assert memory.get_corrections() == []


def test_speichern_und_lesen():
    memory.save_correction(4, "nachmittag", "service", 1, "Freitag Nachmittag ein Service mehr")
    assert memory.get_corrections() == [{"weekday": 4, "shift": "nachmittag", "role": "service",
                                         "delta": 1, "note": "Freitag Nachmittag ein Service mehr"}]


def test_reihenfolge_und_mehrere_eintraege():
    memory.save_correction(4, "nachmittag", "service", 1, "erste")
    memory.save_correction(0, "morgen", "kueche", -1, "zweite")
    assert [c["note"] for c in memory.get_corrections()] == ["erste", "zweite"]


def test_bleibt_ueber_verbindungen_erhalten(tmp_path):
    db = tmp_path / "anderer_lauf.db"
    memory.save_correction(5, "morgen", "abwasch", 1, "Samstag Markt", db_path=db)
    # neue Verbindung = wie ein späterer Lauf des Agenten
    assert memory.get_corrections(db_path=db)[0]["note"] == "Samstag Markt"


@pytest.mark.parametrize("weekday, shift, role, delta", [
    (6, "morgen", "service", 1),          # Sonntag = Ruhetag
    (4, "abend", "service", 1),           # keine Schicht
    (4, "nachmittag", "bar", 1),          # keine Rolle
    (4, "nachmittag", "service", 0),      # keine Änderung
])
def test_ungueltige_korrektur_wird_nicht_gespeichert(weekday, shift, role, delta):
    with pytest.raises(ValueError):
        memory.save_correction(weekday, shift, role, delta, "")
    assert memory.get_corrections() == []


def test_gespeicherte_korrekturen_wirken_in_staffing():
    memory.save_correction(4, "nachmittag", "service", 1, "")
    memory.save_correction(4, "nachmittag", "service", 1, "nochmals")
    prognose = [{"date": "2026-11-13", "shift": "nachmittag", "guests": 40, "upper": 40}]  # Freitag
    ohne = calculate_staffing(prognose)[0]["service"]
    mit = calculate_staffing(prognose, corrections=memory.get_corrections())[0]["service"]
    assert mit == ohne + 2                                     # +1 und +1 addieren sich


# --- Ganzer Ablauf mit echter Tabelle statt Fixture-Speicher ----------------------
@pytest.fixture
def echtes_memory(monkeypatch):
    monkeypatch.setattr(backends, "get_corrections", memory.get_corrections)
    monkeypatch.setattr(backends, "save_correction", memory.save_correction)


FREITAG = Korrektur(eindeutig=True, weekday=4, shift="nachmittag", role="service", delta=1,
                    note="Freitag Nachmittag ein Service mehr")


def test_graph_speichert_erst_nach_freigabe_in_tabelle(fake_llm, run, echtes_memory):
    fake_llm(Guard=OK, Route=WOCHE, Korrektur=FREITAG)
    graph, cfg, result = run("Plane die Woche")
    vorher = service_freitag_nachmittag(interrupt_value(result)["plan"])

    graph.invoke(Command(resume={"decision": "anpassen", "feedback": "Freitag +1 Service"}), cfg)
    assert memory.get_corrections() == []                      # vor Freigabe leer
    graph.invoke(Command(resume={"decision": "freigeben"}), cfg)
    assert len(memory.get_corrections()) == 1                  # nach Freigabe gespeichert

    _, _, result = run("Plane die Woche")                      # neues Gespräch
    assert service_freitag_nachmittag(interrupt_value(result)["plan"]) == vorher + 1


def test_graph_ablehnen_laesst_tabelle_leer(fake_llm, run, echtes_memory):
    fake_llm(Guard=OK, Route=WOCHE, Korrektur=FREITAG)
    graph, cfg, _ = run("Plane die Woche")
    graph.invoke(Command(resume={"decision": "anpassen", "feedback": "Freitag +1 Service"}), cfg)
    graph.invoke(Command(resume={"decision": "ablehnen"}), cfg)
    assert memory.get_corrections() == []


# --- Node korrektur: ungültige Angaben führen zur Rückfrage -------------------------
@pytest.mark.parametrize("k", [
    Korrektur(eindeutig=True, weekday=6, shift="morgen", role="service", delta=1),   # Ruhetag
    Korrektur(eindeutig=True, weekday=4, shift="morgen", role="service", delta=0),   # keine Änderung
])
def test_korrektur_ungueltig_fuehrt_zu_rueckfrage(fake_llm, run, echtes_memory, k):
    fake_llm(Guard=OK, Route=WOCHE, Korrektur=k)
    graph, cfg, _ = run("Plane die Woche")
    result = graph.invoke(Command(resume={"decision": "anpassen", "feedback": "Sonntag mehr"}), cfg)

    payload = interrupt_value(result)
    assert payload["hinweis"]                                  # Rückfrage statt Fehler
    assert payload["korrekturen_offen"] == []
    graph.invoke(Command(resume={"decision": "freigeben"}), cfg)
    assert memory.get_corrections() == []
