"""Wetterprognose über Open-Meteo. Owner: Person B (B2). Vertrag: Projektplan Abschnitt 5.

Open-Meteo ist gratis und braucht keinen API-Key. Abgefragt werden die Tageswerte
Höchsttemperatur (temperature_2m_max) und Niederschlag (precipitation_sum) am Standort
aus config.py (Olten). Die Prognose reicht höchstens 16 Tage in die Zukunft.

Fehler, zwei Arten (passt zu agent/nodes/planung.py):
- API nicht erreichbar, Timeout, Serverfehler (5xx): requests-Fehler. Diese erben von
  OSError, deshalb wiederholt der Node den Aufruf und eskaliert danach.
- Ungültige Anfrage (400, z. B. Datum zu weit in der Zukunft) oder fehlende Werte:
  ValueError. Eine Wiederholung brächte nichts; der Node eskaliert sofort.
Es werden nie Werte erfunden oder ergänzt.
"""
from datetime import date, timedelta

import requests

import config

URL = "https://api.open-meteo.com/v1/forecast"
TIMEOUT_S = 10
MAX_DAYS = 16


def get_weather(start_date: str, days: int = 7) -> list[dict]:
    """Höchsttemperatur und Regen pro Tag am Restaurantstandort (config.LATITUDE/LONGITUDE).

    Rückgabe: [{"date": "2026-10-26", "temp_max": 14.2, "rain_mm": 3.1}, ...]
    Fehlerfall: Exception mit klarer Meldung, niemals Werte erfinden.
    """
    start = date.fromisoformat(start_date)
    if not 1 <= days <= MAX_DAYS:
        raise ValueError(f"days muss zwischen 1 und {MAX_DAYS} liegen, nicht {days}")
    end = start + timedelta(days=days - 1)

    antwort = requests.get(URL, timeout=TIMEOUT_S, params={
        "latitude": config.LATITUDE,
        "longitude": config.LONGITUDE,
        "daily": "temperature_2m_max,precipitation_sum",
        "timezone": config.TIMEZONE,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
    })
    if antwort.status_code == 400:
        grund = antwort.json().get("reason", antwort.text) if antwort.text else "unbekannt"
        raise ValueError(f"Open-Meteo lehnt die Anfrage ab: {grund}")
    antwort.raise_for_status()                      # 5xx → requests.HTTPError (wird wiederholt)

    daily = antwort.json().get("daily") or {}
    tage = daily.get("time") or []
    temps = daily.get("temperature_2m_max") or []
    regen = daily.get("precipitation_sum") or []
    if len(tage) != days or len(temps) != days or len(regen) != days:
        raise ValueError(f"Open-Meteo lieferte {len(tage)} statt {days} Tage")

    wetter = []
    for d, t, r in zip(tage, temps, regen):
        if t is None or r is None:
            raise ValueError(f"Open-Meteo hat für {d} keine Wetterwerte")
        wetter.append({"date": d, "temp_max": round(float(t), 1), "rain_mm": round(float(r), 1)})
    return wetter
