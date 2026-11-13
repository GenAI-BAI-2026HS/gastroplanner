"""Kalender: Öffnungstage, Feiertage SO, Brückentage, Schulferien. Owner: Person B (B2).

Dieselben Definitionen nutzt auch der Testdaten-Generator (data/generate.py). Das ist
wichtig: Das Modell wurde mit diesen Merkmalen trainiert, also muss die Prognose sie
für die Zukunft genau gleich berechnen.

- Feiertage:   holidays.Switzerland(subdiv="SO"). Das Restaurant ist an Feiertagen offen,
               hat aber weniger Gäste.
- Brückentag:  Werktag zwischen Feiertag und Wochenende, also Freitag nach einem
               Donnerstag-Feiertag oder Montag vor einem Dienstag-Feiertag.
- Schulferien: data/school_holidays.csv (Volksschule Olten, Quellen in data/readme.md).
- Geöffnet:    config.OPEN_WEEKDAYS (Mo–Sa).

Kein Netzwerk: Die Funktion rechnet alles lokal.
"""
import csv
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path

import holidays

import config

SCHOOL_HOLIDAYS_CSV = config.ROOT / "data" / "school_holidays.csv"


@lru_cache
def public_holidays(year_from: int, year_to: int) -> holidays.HolidayBase:
    return holidays.Switzerland(subdiv=config.CANTON, years=range(year_from, year_to + 1))


def load_school_holidays(path: Path | str = SCHOOL_HOLIDAYS_CSV) -> list[tuple[date, date, str]]:
    """Schulferien als (start, end, name); end ist der letzte Ferientag."""
    with open(path, encoding="utf-8") as f:
        return [(date.fromisoformat(r["start"]), date.fromisoformat(r["end"]), r["name"])
                for r in csv.DictReader(f)]


def is_school_holiday(d: date, ferien: list[tuple[date, date, str]]) -> bool:
    return any(start <= d <= end for start, end, _ in ferien)


def is_bridge_day(d: date, feiertage) -> bool:
    """Freitag nach einem Donnerstag-Feiertag oder Montag vor einem Dienstag-Feiertag."""
    if d in feiertage:
        return False
    return ((d.weekday() == 4 and d - timedelta(days=1) in feiertage) or
            (d.weekday() == 0 and d + timedelta(days=1) in feiertage))


def get_calendar(start_date: str, days: int = 7) -> list[dict]:
    """Kalenderinformationen pro Tag (Vertrag Projektplan Abschnitt 5).

    Rückgabe: [{"date": "2026-10-26", "weekday": 0, "is_open": True, "is_holiday": False,
                "holiday_name": None, "is_bridge_day": False, "is_school_holiday": False,
                "month": 10}, ...]
    Liefert alle Tage, auch geschlossene (is_open=False). Wirft ValueError bei ungültigem
    Datum oder wenn für ein Jahr keine Schulferien hinterlegt sind.
    """
    start = date.fromisoformat(start_date)
    if days < 1:
        raise ValueError(f"days muss mindestens 1 sein, nicht {days}")
    tage = [start + timedelta(days=i) for i in range(days)]

    ferien = load_school_holidays()
    letzter_ferientag = max(end for _, end, _ in ferien)
    if tage[-1] > letzter_ferientag:
        raise ValueError(f"Schulferien nur bis {letzter_ferientag} hinterlegt; "
                         "data/school_holidays.csv ergänzen")

    feiertage = public_holidays(tage[0].year - 1, tage[-1].year + 1)
    return [{
        "date": d.isoformat(),
        "weekday": d.weekday(),
        "is_open": d.weekday() in config.OPEN_WEEKDAYS,
        "is_holiday": d in feiertage,
        "holiday_name": feiertage.get(d),
        "is_bridge_day": is_bridge_day(d, feiertage),
        "is_school_holiday": is_school_holiday(d, ferien),
        "month": d.month,
    } for d in tage]
