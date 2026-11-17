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
    assert "Zukunft" in app.dataframe[0].value["Name"].tolist()

    _button(app, "Vergangene Reservationen anzeigen").click().run()
    assert not app.exception
    assert app.dataframe[0].value["Name"].tolist() == ["Vorbei"]

    _button(app, "Schliessen").click().run()
    assert not app.session_state.res_ansicht


def test_ablehnen_speichert_nichts(app):
    app.chat_input[0].set_value("Plane die nächste Woche").run()
    _button(app, "Ablehnen").click().run()
    assert not app.exception
    assert count_approved_rows() == 0
    assert "nichts gespeichert" in app.session_state.verlauf[-1]["content"]
