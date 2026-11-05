"""Tests für Wetter und Kalender (B2). Ohne Netzwerk: Open-Meteo wird nachgebaut."""
import importlib.util
from datetime import date

import pytest
import requests

import config
from tools import calendar_ch, weather


# --- Kalender ---------------------------------------------------------------------
def test_woche_hat_sieben_tage_und_sonntag_ist_zu():
    tage = calendar_ch.get_calendar("2026-10-26")
    assert [t["date"] for t in tage][0] == "2026-10-26" and len(tage) == 7
    assert [t["is_open"] for t in tage] == [True] * 6 + [False]          # So 01.11. Ruhetag
    assert set(tage[0]) == {"date", "weekday", "is_open", "is_holiday", "holiday_name",
                            "is_bridge_day", "is_school_holiday", "month"}


def test_feiertag_brueckentag_und_schulferien():
    tage = {t["date"]: t for t in calendar_ch.get_calendar("2026-05-11")}
    assert tage["2026-05-14"]["is_holiday"] and tage["2026-05-14"]["holiday_name"] == "Auffahrt"
    assert tage["2026-05-15"]["is_bridge_day"]                         # Freitag nach Auffahrt
    assert not tage["2026-05-15"]["is_holiday"]
    herbst = calendar_ch.get_calendar("2026-10-12")
    assert herbst[0]["is_school_holiday"] and not herbst[-1]["is_school_holiday"]


def test_kalender_ohne_hinterlegte_schulferien_wirft_fehler():
    with pytest.raises(ValueError, match="school_holidays.csv"):
        calendar_ch.get_calendar("2028-01-05", 7)


def test_kalender_und_testdaten_rechnen_gleich():
    """Training und Prognose müssen dieselben Merkmale sehen."""
    spec = importlib.util.spec_from_file_location("generate", config.ROOT / "data" / "generate.py")
    generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generate)
    rows = generate.generate_rows(date(2025, 5, 26), date(2026, 1, 10))
    kalender = {t["date"]: t for t in calendar_ch.get_calendar("2025-05-26", 230)}
    for r in rows:
        k = kalender[r["date"]]
        assert (r["is_holiday"], r["is_bridge_day"], r["is_school_holiday"]) == \
               (int(k["is_holiday"]), int(k["is_bridge_day"]), int(k["is_school_holiday"]))


# --- Wetter (Open-Meteo nachgebaut) ---------------------------------------------------
class FakeResponse:
    def __init__(self, status=200, payload=None):
        self.status_code, self._payload = status, payload or {}
        self.text = "x"

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"{self.status_code} Server Error")


def daily(n, temps=None, regen=None):
    return {"daily": {"time": [f"2026-10-{26 + i}" for i in range(n)],
                      "temperature_2m_max": temps or [12.34] * n,
                      "precipitation_sum": regen or [0.0] * n}}


@pytest.fixture
def api(monkeypatch):
    aufrufe = []

    def install(response):
        def fake_get(url, params, timeout):
            aufrufe.append(params)
            return response
        monkeypatch.setattr(weather.requests, "get", fake_get)
        return aufrufe
    return install


def test_wetter_format_und_standort(api):
    aufrufe = api(FakeResponse(payload=daily(3, regen=[0.0, 4.26, 0.1])))
    w = weather.get_weather("2026-10-26", 3)
    assert w == [{"date": "2026-10-26", "temp_max": 12.3, "rain_mm": 0.0},
                 {"date": "2026-10-27", "temp_max": 12.3, "rain_mm": 4.3},
                 {"date": "2026-10-28", "temp_max": 12.3, "rain_mm": 0.1}]
    p = aufrufe[0]
    assert (p["latitude"], p["longitude"]) == (config.LATITUDE, config.LONGITUDE)
    assert (p["start_date"], p["end_date"]) == ("2026-10-26", "2026-10-28")


def test_serverfehler_wird_als_voruebergehend_gemeldet(api):
    api(FakeResponse(status=503))
    with pytest.raises(OSError):                  # planung.py wiederholt OSError
        weather.get_weather("2026-10-26", 3)


def test_ungueltige_anfrage_ist_kein_voruebergehender_fehler(api):
    api(FakeResponse(status=400, payload={"error": True, "reason": "Date out of range"}))
    with pytest.raises(ValueError, match="Date out of range"):
        weather.get_weather("2026-10-26", 3)


def test_fehlende_werte_werden_nicht_erfunden(api):
    api(FakeResponse(payload=daily(3, temps=[10.0, None, 9.0])))
    with pytest.raises(ValueError, match="keine Wetterwerte"):
        weather.get_weather("2026-10-26", 3)


def test_zu_wenige_tage(api):
    api(FakeResponse(payload=daily(2)))
    with pytest.raises(ValueError, match="2 statt 3"):
        weather.get_weather("2026-10-26", 3)


def test_horizont_zu_lang():
    with pytest.raises(ValueError, match="zwischen 1 und 16"):
        weather.get_weather("2026-10-26", 20)
