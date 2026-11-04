"""Ersatzprognose aus dem Wochentagsmittel (forecast/baseline.py)."""
from datetime import date, timedelta

import pytest

from forecast.baseline import weekday_mean_forecast

START = "2026-10-26"   # Montag


def history(wochen=8, gaeste=lambda d, s: 40 if s == "morgen" else 20):
    start = date.fromisoformat(START)
    rows = []
    for i in range(1, wochen * 7 + 1):
        d = start - timedelta(days=i)
        if d.weekday() <= 5:
            rows += [{"date": d.isoformat(), "shift": s, "guests": gaeste(d, s)}
                     for s in ("morgen", "nachmittag")]
    return rows


def test_mittel_pro_wochentag_und_schicht():
    h = history(gaeste=lambda d, s: (50 if d.weekday() == 4 else 30) + (0 if s == "morgen" else -10))
    prognose = weekday_mean_forecast(h, START, 7)
    assert len(prognose) == 12                                         # Mo–Sa, So Ruhetag
    freitag = {f["shift"]: f["guests"] for f in prognose if f["date"] == "2026-10-30"}
    assert freitag == {"morgen": 50, "nachmittag": 40}
    assert all(f["assumptions"]["fallback"] == "wochentagsmittel" for f in prognose)


def test_spanne_umschliesst_mittel():
    h = history(gaeste=lambda d, s: 30 + (d.toordinal() % 7) * 3)
    for f in weekday_mean_forecast(h, START, 7):
        assert f["lower"] <= f["guests"] <= f["upper"]


def test_nur_letzte_acht_wochen_zaehlen():
    alt = [{"date": "2026-01-05", "shift": "morgen", "guests": 999}]  # weit vor dem Fenster
    prognose = weekday_mean_forecast(history() + alt, START, 7)
    assert max(f["guests"] for f in prognose) == 40


def test_geschlossene_tage_aus_dem_kalender():
    offen = ["2026-10-26", "2026-10-27"]
    prognose = weekday_mean_forecast(history(), START, 7, open_dates=offen)
    assert {f["date"] for f in prognose} == set(offen)


def test_zu_wenig_historie():
    with pytest.raises(ValueError, match="Zu wenig Historie"):
        weekday_mean_forecast(history(wochen=1), START, 7)
