"""Gästeprognose. Aufgabe A3. Vertrag: Projektplan Abschnitt 5.

Ablauf: Wetter (get_weather) und Kalender (get_calendar) für den Horizont holen, für jeden
offenen Tag dieselben Merkmale bauen wie im Training (forecast.train.prepare) und pro
Schicht mit dem OLS-Modell vorhersagen.

Spanne = 80 %-Prognoseintervall (obs_ci, alpha=0.2): In etwa 8 von 10 Fällen liegt die
tatsächliche Gästezahl darin. Es ist breiter als das Konfidenzintervall des Mittelwerts,
weil es auch die Streuung einzelner Tage enthält. Geplant wird mit dem oberen Wert
(Unterbesetzung ist teurer als eine Person zu viel), das macht calculate_staffing.

Das LLM rechnet hier nichts: Die Zahlen kommen nur aus dem Modell.
"""
import pandas as pd

import config
from forecast.train import load_models, prepare

ALPHA = 0.2                     # 80 %-Intervall
_MODELS = None                  # einmal laden, dann wiederverwenden


def _models() -> dict:
    global _MODELS
    if _MODELS is None:
        _MODELS = load_models()
    return _MODELS


def predict_from(weather: list[dict], calendar: list[dict], models: dict | None = None) -> list[dict]:
    """Prognose aus bereits geholtem Wetter und Kalender (testbar ohne Netzwerk).

    Nur offene Tage. Fehlt für einen offenen Tag das Wetter, gibt es einen ValueError,
    statt Werte zu erfinden.
    """
    models = models or _models()
    wetter = {w["date"]: w for w in weather}
    offen = [c for c in sorted(calendar, key=lambda c: c["date"]) if c["is_open"]]
    if not offen:
        return []
    fehlend = [c["date"] for c in offen if c["date"] not in wetter]
    if fehlend:
        raise ValueError(f"Wetter fehlt für {', '.join(fehlend)}")

    X = prepare(pd.DataFrame([{
        "date": c["date"], "weekday": c["weekday"], "month": c["month"],
        "temp_max": wetter[c["date"]]["temp_max"], "rain_mm": wetter[c["date"]]["rain_mm"],
        "is_holiday": c["is_holiday"], "is_bridge_day": c["is_bridge_day"],
        "is_school_holiday": c["is_school_holiday"],
    } for c in offen]))

    spannen = {s: models[s].get_prediction(X).summary_frame(alpha=ALPHA) for s in config.SHIFTS}

    prognose = []
    for i, c in enumerate(offen):
        for shift in config.SHIFTS:
            p = spannen[shift].iloc[i]
            guests = max(0, round(float(p["mean"])))
            lower = max(0, min(round(float(p["obs_ci_lower"])), guests))
            upper = max(round(float(p["obs_ci_upper"])), guests)
            prognose.append({
                "date": c["date"], "shift": shift,
                "guests": guests, "lower": lower, "upper": upper,
                "assumptions": {
                    "temp_max": float(wetter[c["date"]]["temp_max"]),
                    "rain_mm": float(wetter[c["date"]]["rain_mm"]),
                    "is_holiday": bool(c["is_holiday"]),
                    "holiday_name": c.get("holiday_name"),
                    "is_bridge_day": bool(c["is_bridge_day"]),
                    "is_school_holiday": bool(c["is_school_holiday"]),
                    "weekday": int(c["weekday"]),
                },
            })
    return prognose


def forecast_guests(start_date: str, days: int = 7) -> list[dict]:
    """Gäste pro offenem Tag und Schicht mit Prognosespanne.

    Ruft get_weather + get_calendar intern auf; liefert nur offene Tage.
    Beispiel: tests/fixtures/forecast_example.json
    [{"date": "2026-10-26", "shift": "morgen", "guests": 41, "lower": 34, "upper": 48,
      "assumptions": {"temp_max": 14.2, "rain_mm": 3.1, "is_holiday": False, ...}}, ...]
    """
    from tools.calendar_ch import get_calendar
    from tools.weather import get_weather

    return predict_from(get_weather(start_date, days), get_calendar(start_date, days))
