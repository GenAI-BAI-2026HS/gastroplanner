"""Wetterprognose über Open-Meteo. Owner: Person B (B2). Vertrag: Projektplan Abschnitt 5."""


def get_weather(start_date: str, days: int = 7) -> list[dict]:
    """Höchsttemperatur und Regen pro Tag am Restaurantstandort (config.LATITUDE/LONGITUDE).

    Rückgabe: [{"date": "2026-10-26", "temp_max": 14.2, "rain_mm": 3.1}, ...]
    Fehlerfall: Exception mit klarer Meldung, niemals Werte erfinden.
    """
    raise NotImplementedError("B2: get_weather ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
