"""Tests für Prognose (A3) und Plausibilitätsprüfung (A5)."""
import importlib.util
import json
from copy import deepcopy

import pytest

import config
from forecast import checks, predict

FIX = config.FIXTURES_DIR
WEATHER = json.loads((FIX / "weather_example.json").read_text(encoding="utf-8"))
CALENDAR = json.loads((FIX / "calendar_example.json").read_text(encoding="utf-8"))
FORECAST = json.loads((FIX / "forecast_example.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def models(tmp_path_factory):
    """Modelle auf den Testdaten trainieren, ohne das Repo anzufassen."""
    from forecast.train import load_models

    spec = importlib.util.spec_from_file_location("generate", config.ROOT / "data" / "generate.py")
    generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generate)
    tmp = tmp_path_factory.mktemp("prognose")
    generate.write_history(generate.generate_rows(), tmp / "restaurant.db")
    return load_models(tmp / "restaurant.db", tmp / "models")


# --- A3 Prognose ----------------------------------------------------------------------
def test_zwoelf_eintraege_fuer_die_woche(models):
    p = predict.predict_from(WEATHER, CALENDAR, models)
    assert len(p) == 12                                         # 6 offene Tage × 2 Schichten
    assert "2026-11-01" not in {r["date"] for r in p}           # Sonntag fehlt
    assert set(p[0]) == {"date", "shift", "guests", "lower", "upper", "assumptions"}
    assert all(0 <= r["lower"] <= r["guests"] <= r["upper"] for r in p)
    assert all(r["upper"] > r["lower"] for r in p)              # echte Spanne


def test_effekte_kommen_in_der_prognose_an(models):
    p = {(r["date"], r["shift"]): r["guests"] for r in predict.predict_from(WEATHER, CALENDAR, models)}
    assert p[("2026-10-31", "morgen")] < p[("2026-10-29", "morgen")]          # Samstagmorgen ruhiger
    assert p[("2026-10-31", "nachmittag")] > p[("2026-10-29", "nachmittag")]  # Samstagnachmittag voller

    trocken = deepcopy(WEATHER)
    nass = deepcopy(WEATHER)
    for w in trocken:
        w["rain_mm"] = 0.0
    for w in nass:
        w["rain_mm"] = 8.0
    t = predict.predict_from(trocken, CALENDAR, models)
    n = predict.predict_from(nass, CALENDAR, models)
    assert all(a["guests"] >= b["guests"] for a, b in zip(t, n))              # Regen = weniger


def test_ausgabe_ist_json_tauglich(models):
    """Muss in den State (Checkpointer) und über MCP passen: keine numpy-Typen."""
    json.dumps(predict.predict_from(WEATHER, CALENDAR, models))


def test_fehlendes_wetter_wird_nicht_erfunden(models):
    with pytest.raises(ValueError, match="2026-10-28"):
        predict.predict_from([w for w in WEATHER if w["date"] != "2026-10-28"], CALENDAR, models)


def test_forecast_guests_holt_wetter_und_kalender(models, monkeypatch):
    import tools.calendar_ch
    import tools.weather

    monkeypatch.setattr(predict, "_MODELS", models)
    monkeypatch.setattr(tools.weather, "get_weather", lambda s, d: WEATHER)
    p = predict.forecast_guests("2026-10-26")                    # Kalender echt gerechnet
    assert len(p) == 12
    assert checks.check_plausibility(p, "2026-10-26")["ok"]


# --- A5 Plausibilität -------------------------------------------------------------------
def test_beispielprognose_ist_plausibel():
    assert checks.check_plausibility(FORECAST, "2026-10-26") == {"ok": True, "issues": []}


def test_fehlender_tag_wird_gemeldet():
    p = [r for r in FORECAST if not (r["date"] == "2026-10-28" and r["shift"] == "nachmittag")]
    result = checks.check_plausibility(p, "2026-10-26")
    assert not result["ok"]
    assert result["issues"] == ["2026-10-28 nachmittag fehlt"]


def test_ausreisser_ueber_kapazitaet():
    p = deepcopy(FORECAST)
    p[0].update(guests=900, upper=950)
    result = checks.check_plausibility(p, "2026-10-26")
    assert not result["ok"]
    assert result["issues"] == ["2026-10-26 morgen: 900 Gäste über Kapazität (150)"]


def test_spanne_und_wetter_werden_geprueft():
    p = deepcopy(FORECAST)
    p[1]["lower"] = p[1]["guests"] + 5
    p[2]["assumptions"]["temp_max"] = None
    issues = checks.check_plausibility(p, "2026-10-26")["issues"]
    assert any("Spanne" in i for i in issues)
    assert any("Wetterwerte fehlen" in i for i in issues)


def test_ersatzprognose_braucht_kein_wetter():
    """Sonst würde der Fallback im Graphen immer scheitern und sofort eskalieren."""
    from forecast.baseline import weekday_mean_forecast

    history = json.loads((FIX / "history_example.json").read_text(encoding="utf-8"))
    ersatz = weekday_mean_forecast(history, "2026-10-26", 7)
    assert checks.check_plausibility(ersatz, "2026-10-26")["ok"]


def test_leere_prognose_und_doppelte_eintraege():
    assert checks.check_plausibility([], "2026-10-26") == {"ok": False, "issues": ["Prognose ist leer"]}
    issues = checks.check_plausibility(FORECAST + FORECAST[:1], "2026-10-26")["issues"]
    assert issues == ["2026-10-26 morgen ist doppelt"]
