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


def test_ablehnen_speichert_nichts(app):
    app.chat_input[0].set_value("Plane die nächste Woche").run()
    _button(app, "Ablehnen").click().run()
    assert not app.exception
    assert count_approved_rows() == 0
    assert "nichts gespeichert" in app.session_state.verlauf[-1]["content"]
