"""Gästeprognose. Owner: Person A (A3). Vertrag: Projektplan Abschnitt 5."""


def forecast_guests(start_date: str, days: int = 7) -> list[dict]:
    """Gäste pro offenem Tag und Schicht mit Prognosespanne.

    Ruft get_weather + get_calendar intern auf; liefert nur offene Tage.
    Beispiel: tests/fixtures/forecast_example.json
    [{"date": "2026-10-26", "shift": "morgen", "guests": 41, "lower": 34, "upper": 48,
      "assumptions": {"temp_max": 14.2, "rain_mm": 3.1, "is_holiday": False, ...}}, ...]
    """
    raise NotImplementedError("A3: forecast_guests ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
