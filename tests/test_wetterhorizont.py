"""Woche hinter dem Wetterhorizont: Ersatzprognose statt Fehlermeldung."""
from agent import backends
from agent.nodes import explain, planung


def test_woche_hinter_wetterhorizont_nutzt_wochentagsmittel(monkeypatch):
    # HEUTE = 2026-10-25 → Wetter bis 2026-11-09; Woche ab 2026-11-09 endet am 15.11.
    monkeypatch.setattr(backends, "use_fixtures", lambda: False)
    wetter_aufrufe = []
    monkeypatch.setattr(backends, "get_weather", lambda *a: wetter_aufrufe.append(a) or [])
    monkeypatch.setattr(backends, "get_calendar", lambda s, d: [
        {"date": f"2026-11-{9 + i:02d}", "is_open": i < 6} for i in range(d)])
    monkeypatch.setattr(backends, "forecast_guests", lambda *a: (_ for _ in ()).throw(
        AssertionError("Regression darf ohne Wetter nicht laufen")))
    monkeypatch.setattr(backends, "weekday_mean_forecast", lambda s, d, open_dates: [
        {"date": x, "shift": "morgen", "guests": 40, "lower": 30, "upper": 50,
         "assumptions": {"fallback": "wochentagsmittel"}} for x in open_dates])

    state = {"start_date": "2026-11-09", "retries": 0}
    state |= planung.context(state)
    assert wetter_aufrufe == [] and state["escalation"] is None
    assert state["context"]["weather"] is None

    state |= planung.forecast(state)
    assert len(state["forecast"]) == 6
    assert "09.11.2026" in state["fallback_grund"]


def test_woche_im_wetterhorizont_fragt_wetter_ab(monkeypatch):
    monkeypatch.setattr(backends, "use_fixtures", lambda: False)
    monkeypatch.setattr(backends, "get_weather", lambda *a: ["wetter"])
    monkeypatch.setattr(backends, "get_calendar", lambda *a: ["kalender"])
    out = planung.context({"start_date": "2026-10-26", "retries": 0})
    assert out["context"] == {"weather": ["wetter"], "calendar": ["kalender"]}


def test_erklaerung_erfindet_keine_ersatzprognose():
    assert "keine Ersatzprognose" in explain._prognose_anweisung(None)
    assert "Wetterprognose" in explain._prognose_anweisung("Wetterprognose reicht erst bis …")
