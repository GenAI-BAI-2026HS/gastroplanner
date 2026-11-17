"""Tests für die Streamlit-Oberfläche (A6). Fake-LLM, InMemorySaver, kein Netzwerk."""
import pytest

pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

import config  # noqa: E402
from agent.schemas import Guard, Route  # noqa: E402
from tools.plans import count_approved_rows  # noqa: E402

OK = Guard(erlaubt=True, grund="Personalplanung")
WOCHE = Route(intent="wochenplanung", start_date=None)


@pytest.fixture
def app(monkeypatch, fake_llm):
    monkeypatch.setenv("CHECKPOINTER", "memory")
    fake_llm(Guard=OK, Route=WOCHE)
    at = AppTest.from_file(str(config.ROOT / "app.py"), default_timeout=30)
    at.run()
    return at


def _button(at, label):
    return next(b for b in at.button if b.label == label)


def test_startseite_zeigt_beispiele(app):
    assert not app.exception
    assert "Plane die nächste Woche" in [b.label for b in app.button]


def test_plan_erst_nach_freigabe_gespeichert(app):
    app.chat_input[0].set_value("Plane die nächste Woche").run()
    assert not app.exception
    assert app.session_state.offen["typ"] == "freigabe"
    assert len(app.dataframe) >= 1                       # Plantabelle sichtbar
    assert count_approved_rows() == 0                    # noch nichts gespeichert

    _button(app, "Freigeben").click().run()
    assert not app.exception
    assert app.session_state.offen is None
    assert count_approved_rows() > 0
    assert "freigegeben" in app.session_state.verlauf[-1]["content"]


def test_reservation_erst_nach_bestaetigung_gespeichert(monkeypatch, fake_llm):
    from agent import backends
    from agent.schemas import Reservation
    monkeypatch.setenv("CHECKPOINTER", "memory")
    fake_llm(Guard=OK, Route=Route(intent="reservation"),
             Reservation=Reservation(name="Meier", telefon="079 123 45 67", personen=25,
                                     datum="2026-10-30", uhrzeit="19:00", grund="Firmenessen"))
    at = AppTest.from_file(str(config.ROOT / "app.py"), default_timeout=30)
    at.run()
    at.chat_input[0].set_value("Firmenessen Meier, 25 Personen, Freitag 19 Uhr").run()
    assert not at.exception
    assert at.session_state.offen["typ"] == "reservation"
    assert backends.get_reservations() == []

    _button(at, "Reservation speichern").click().run()
    assert not at.exception
    assert len(backends.get_reservations()) == 1
    assert "Reservation gespeichert" in at.session_state.verlauf[-1]["content"]


def test_reservationsansicht_kommend_und_vergangen(app):
    from datetime import date, timedelta
    from tools import reservations as res
    morgen = date.today() + timedelta(days=1)
    while morgen.weekday() == 6:                         # kein Sonntag
        morgen += timedelta(days=1)
    res.save_reservation("Zukunft", "0791234567", 20, morgen.isoformat(), "morgen", occasion="Firma")
    res.save_reservation("Vorbei", "0791234567", 12, "2025-01-10", "morgen", occasion="Geburtstag")
    app.run()

    _button(app, "Alle Reservationen anzeigen (1 kommende)").click().run()
    assert not app.exception
    assert app.session_state.res_ansicht
    assert any(m.value == "Zukunft" for m in app.markdown)

    _button(app, "Vergangene Reservationen anzeigen").click().run()
    assert not app.exception
    assert app.dataframe[0].value["Name"].tolist() == ["Vorbei"]

    _button(app, "Schliessen").click().run()
    assert not app.session_state.res_ansicht


def test_reservationsansicht_ohne_chat_und_hinzufuegen(app):
    _button(app, "Alle Reservationen anzeigen (0 kommende)").click().run()
    assert not app.exception
    assert len(app.chat_input) == 0
    assert "Plane die nächste Woche" not in [b.label for b in app.button]

    _button(app, "Reservation hinzufügen").click().run()
    assert not app.exception
    assert not app.session_state.res_ansicht
    assert len(app.chat_input) == 1
    assert "Plane die nächste Woche" in [b.label for b in app.button]   # wie «Neues Gespräch»
    assert app.session_state.verlauf == []


def test_neues_gespraech_schliesst_reservationsansicht(app):
    _button(app, "Alle Reservationen anzeigen (0 kommende)").click().run()
    _button(app, "Neues Gespräch").click().run()
    assert not app.exception
    assert not app.session_state.res_ansicht
    assert len(app.chat_input) == 1


def test_reservation_ueber_stift_bearbeiten(app):
    from datetime import date, timedelta
    from tools import reservations as res
    tag = date.today() + timedelta(days=2)
    while tag.weekday() not in config.OPEN_WEEKDAYS:
        tag += timedelta(days=1)
    rid = res.save_reservation("Meier AG", "0791234567", 20, tag.isoformat(), "nachmittag",
                               time="18:00", occasion="Firmenessen")
    app.run()
    _button(app, "Alle Reservationen anzeigen (1 kommende)").click().run()
    next(b for b in app.button if b.key == f"res_edit_{rid}").click().run()
    assert not app.exception
    assert app.session_state.res_bearbeiten == rid

    app.text_input(key=f"res_name_{rid}").set_value("Müller GmbH")
    app.number_input(key=f"res_personen_{rid}").set_value(30)
    app.text_input(key=f"res_telefon_{rid}").set_value("079 765 43 21")
    _button(app, "Speichern").click().run()
    assert not app.exception
    x = res.get_reservation(rid)
    assert (x["name"], x["persons"], x["phone"], x["time"]) == ("Müller GmbH", 30, "0797654321", "18:00")
    assert app.session_state.res_bearbeiten is None


def test_reservation_verschieben_verlangt_neue_freigabe(app):
    from datetime import date, timedelta
    from tools import reservations as res
    from tools.plans import list_approved_plans, save_approved_plan
    tag = date.today() + timedelta(days=2)
    while tag.weekday() not in config.OPEN_WEEKDAYS:
        tag += timedelta(days=1)
    ziel = tag + timedelta(days=14)
    while ziel.weekday() not in config.OPEN_WEEKDAYS:
        ziel += timedelta(days=1)
    save_approved_plan([{"date": ziel.isoformat(), "shift": "morgen", "kueche": 2, "service": 3,
                         "abwasch": 1, "guests_planned": 80}])
    rid = res.save_reservation("Test", "0791234567", 15, tag.isoformat(), "morgen")
    app.run()
    _button(app, "Alle Reservationen anzeigen (1 kommende)").click().run()
    next(b for b in app.button if b.key == f"res_edit_{rid}").click().run()
    app.date_input(key=f"res_datum_{rid}").set_value(ziel)
    _button(app, "Speichern").click().run()
    assert not app.exception
    assert list_approved_plans()[0]["neu_freigeben"]
    assert any("muss neu freigegeben werden" in m.value for m in app.success)


def test_reservation_bearbeiten_ungueltige_nummer(app):
    from datetime import date, timedelta
    from tools import reservations as res
    tag = date.today() + timedelta(days=2)
    while tag.weekday() not in config.OPEN_WEEKDAYS:
        tag += timedelta(days=1)
    rid = res.save_reservation("Meier AG", "0791234567", 20, tag.isoformat(), "morgen")
    app.run()
    _button(app, "Alle Reservationen anzeigen (1 kommende)").click().run()
    next(b for b in app.button if b.key == f"res_edit_{rid}").click().run()
    app.text_input(key=f"res_telefon_{rid}").set_value("abc")
    _button(app, "Speichern").click().run()
    assert app.error
    assert res.get_reservation(rid)["phone"] == "0791234567"


def test_freigegebene_plaene_ansicht(app):
    from tools.plans import save_approved_plan
    plan_id = save_approved_plan([
        {"date": "2026-10-26", "shift": "morgen", "kueche": 2, "service": 3, "abwasch": 1,
         "guests_planned": 80},
        {"date": "2026-11-01", "shift": "nachmittag", "kueche": 3, "service": 4, "abwasch": 1,
         "guests_planned": 120}])
    app.run()
    _button(app, "Freigegebene Pläne anzeigen (1)").click().run()
    assert not app.exception
    assert app.session_state.plan_ansicht
    assert len(app.chat_input) == 0
    assert len(app.expander) == 1 and plan_id in app.expander[0].label
    assert app.dataframe[0].value["Geplant für"].tolist() == [80, 120]
    assert app.dataframe[0].value["Reserviert"].tolist() == [0, 0]
    assert "0 reservierte Gäste" in app.expander[0].label

    from tools import reservations as res
    from tools.plans import plan_ungueltig_machen
    res.save_reservation("Meier", "0791234567", 25, "2026-11-01", "nachmittag")
    plan_ungueltig_machen("2026-10-30", "Neue Reservation Nr. 7")
    app.run()
    assert app.dataframe[0].value["Reserviert"].tolist() == [0, 25]
    assert "25 reservierte Gäste" in app.expander[0].label
    assert "muss neu freigegeben werden" in app.expander[0].label
    assert any("Neue Reservation Nr. 7" in w.value for w in app.warning)

    warnung = next(b for b in app.button if b.key == f"plan_neu_{plan_id}")
    assert "Plan erneut freigeben" in warnung.label
    warnung.click().run()                                     # startet die Planung im Chat
    assert not app.exception
    assert not app.session_state.plan_ansicht
    assert app.session_state.verlauf[0]["content"] == "Plane die Woche ab 26.10.2026"
    assert app.session_state.offen["typ"] == "freigabe"       # neuer Plan wartet auf Freigabe


def test_neuen_plan_erstellen_fuehrt_zum_chat(app):
    _button(app, "Freigegebene Pläne anzeigen (0)").click().run()
    _button(app, "Neuen Plan erstellen").click().run()
    assert not app.session_state.plan_ansicht
    assert len(app.chat_input) == 1


def test_ablehnen_speichert_nichts(app):
    app.chat_input[0].set_value("Plane die nächste Woche").run()
    _button(app, "Ablehnen").click().run()
    assert not app.exception
    assert count_approved_rows() == 0
    assert "nichts gespeichert" in app.session_state.verlauf[-1]["content"]
