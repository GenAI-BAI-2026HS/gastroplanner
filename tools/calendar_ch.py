"""Kalender: Öffnungstage, Feiertage SO, Brückentage, Schulferien. Owner: Person B (B2)."""


def get_calendar(start_date: str, days: int = 7) -> list[dict]:
    """Kalenderinformationen pro Tag (Vertrag Projektplan Abschnitt 5).

    Rückgabe: [{"date": "2026-10-26", "weekday": 0, "is_open": True, "is_holiday": False,
                "holiday_name": None, "is_bridge_day": False, "is_school_holiday": False,
                "month": 10}, ...]
    """
    raise NotImplementedError("B2: get_calendar ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
