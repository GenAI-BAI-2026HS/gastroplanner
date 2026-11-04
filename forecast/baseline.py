"""Wochentagsmittel als Ersatzprognose. Owner: Person A (A4/A5), eingebaut von B.

Gleiche Logik wie die Baseline im Backtest (A4): Mittelwert desselben Wochentags und
derselben Schicht über die letzten 8 Wochen vor dem Startdatum. Der Agent nutzt sie als
Fallback, wenn die Regression eine unplausible Prognose liefert. Eine Wiederholung der
Regression würde nichts bringen, weil sie bei gleichem Input dasselbe Ergebnis liefert.

Reine Funktion ohne Datenbank: Die Historie wird übergeben (agent/backends.py liest sie).
"""
from datetime import date, timedelta
from statistics import mean, quantiles

import config

WOCHEN = 8


def weekday_mean_forecast(history: list[dict], start_date: str, days: int,
                          open_dates: list[str] | None = None, weeks: int = WOCHEN) -> list[dict]:
    """Prognose im Format von forecast_guests, berechnet aus dem Wochentagsmittel.

    history:    [{"date": "2026-10-19", "shift": "morgen", "guests": 40}, ...]
    open_dates: offene Tage im Horizont (aus dem Kalender); None = config.OPEN_WEEKDAYS.
    Spanne: 10.- bis 90.-Perzentil der Vergleichswerte (80 %-Intervall wie die Regression).
    Wirft ValueError, wenn für einen Wochentag und eine Schicht weniger als zwei Werte da sind.
    """
    start = date.fromisoformat(start_date)
    fenster_start = start - timedelta(weeks=weeks)
    werte: dict[tuple[int, str], list[int]] = {}
    for row in history:
        d = date.fromisoformat(row["date"])
        if fenster_start <= d < start:
            werte.setdefault((d.weekday(), row["shift"]), []).append(int(row["guests"]))

    tage = [start + timedelta(days=i) for i in range(days)]
    if open_dates is None:
        tage = [d for d in tage if d.weekday() in config.OPEN_WEEKDAYS]
    else:
        offen = set(open_dates)
        tage = [d for d in tage if d.isoformat() in offen]

    prognose = []
    for d in tage:
        for shift in config.SHIFTS:
            vergleich = werte.get((d.weekday(), shift), [])
            if len(vergleich) < 2:
                raise ValueError(f"Zu wenig Historie für {d.isoformat()} {shift} "
                                 f"({len(vergleich)} Werte in {weeks} Wochen)")
            guests = round(mean(vergleich))
            p = quantiles(vergleich, n=10, method="inclusive")
            prognose.append({
                "date": d.isoformat(), "shift": shift, "guests": guests,
                "lower": min(round(p[0]), guests), "upper": max(round(p[-1]), guests),
                "assumptions": {"weekday": d.weekday(), "fallback": "wochentagsmittel",
                                "vergleichswerte": len(vergleich)},
            })
    return prognose
