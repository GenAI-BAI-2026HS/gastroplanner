"""Testdaten-Generator: synthetische Gästezahlen pro Tag und Schicht. Owner: Person A (A2).

    python data/generate.py            # schreibt die Tabelle history in data/restaurant.db
    python data/generate.py --plot     # zusätzlich Kontrollplot nach docs/testdaten.png

Zeitraum 01.10.2024 bis 18.10.2026, nur offene Tage (config.OPEN_WEEKDAYS, Mo–Sa),
pro Tag zwei Zeilen (morgen, nachmittag). Seed fix, also bei jedem Lauf dieselben Daten.
Nur die Tabelle history wird ersetzt; approved_plans und corrections bleiben unberührt.

Eingebaute Effekte (Projektplan A2, Schritt 5–6). Diese Faktoren soll die Regression in A3
wiederfinden; sie sind Annahmen und gehören in die Limitationen:

    Basis            Morgen Mo–Fr 45, Sa 30 · Nachmittag Mo–Fr 15, Sa 25
    Regen            Morgen ×0.90, Nachmittag ×0.75
    Hitze (≥ 25 °C)  Nachmittag ×1.30
    Kälte (< 5 °C)   Morgen ×1.10
    Schulferien      ×0.85
    Brückentag       ×0.75
    Feiertag         ×0.80
    Dezember         ×1.10
    Zufall           ×N(1, 0.10), danach gerundet, nie unter 0

Kalender: Feiertage aus holidays.Switzerland(subdiv="SO"), Schulferien aus
data/school_holidays.csv, Brückentag = Werktag zwischen Feiertag und Wochenende
(Freitag nach einem Donnerstag-Feiertag oder Montag vor einem Dienstag-Feiertag).
get_calendar (B2) muss dieselben Definitionen verwenden, sonst passen Training und Prognose
nicht zusammen: am einfachsten die Funktionen is_bridge_day und load_school_holidays
von hier übernehmen.
"""
import argparse
import csv
import sqlite3
import sys
from datetime import date, timedelta
from math import cos, pi
from pathlib import Path

import holidays
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import config  # noqa: E402

START, END = date(2024, 10, 1), date(2026, 10, 18)
SEED = 42
SCHOOL_HOLIDAYS_CSV = config.ROOT / "data" / "school_holidays.csv"

BASE = {"morgen": {"werktag": 45, "samstag": 30},
        "nachmittag": {"werktag": 15, "samstag": 25}}
FACTOR_RAIN = {"morgen": 0.90, "nachmittag": 0.75}
HOT_TEMP, FACTOR_HOT = 25, 1.30          # nur Nachmittag
COLD_TEMP, FACTOR_COLD = 5, 1.10         # nur Morgen
FACTOR_SCHOOL_HOLIDAY = 0.85
FACTOR_BRIDGE_DAY = 0.75
FACTOR_HOLIDAY = 0.80
FACTOR_DECEMBER = 1.10
NOISE_SD = 0.10

SCHEMA = """
CREATE TABLE history (
    date TEXT NOT NULL, weekday INT NOT NULL, shift TEXT NOT NULL, guests INT NOT NULL,
    temp_max REAL NOT NULL, rain_mm REAL NOT NULL, is_holiday INT NOT NULL,
    is_bridge_day INT NOT NULL, is_school_holiday INT NOT NULL, month INT NOT NULL,
    PRIMARY KEY (date, shift)
)
"""
COLUMNS = ("date", "weekday", "shift", "guests", "temp_max", "rain_mm", "is_holiday",
           "is_bridge_day", "is_school_holiday", "month")


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


def simulate_weather(d: date, rng: np.random.Generator) -> tuple[float, float]:
    """Höchsttemperatur (Saisonkurve ca. 3 °C Mitte Januar bis 26 °C Mitte Juli) und Regen."""
    tag = d.timetuple().tm_yday
    temp = 14.5 - 11.5 * cos(2 * pi * (tag - 15) / 365.25) + rng.normal(0, 3)
    p_regen = 0.38 + 0.07 * cos(2 * pi * (tag - 196) / 365.25)   # im Sommer etwas häufiger
    rain_mm = round(float(rng.uniform(1, 15)), 1) if rng.random() < p_regen else 0.0
    return round(float(temp), 1), rain_mm


def guests_for(shift: str, d: date, temp: float, rain_mm: float, holiday: bool,
               bridge: bool, school: bool, rng: np.random.Generator) -> int:
    g = BASE[shift]["samstag" if d.weekday() == 5 else "werktag"]
    if rain_mm > 0:
        g *= FACTOR_RAIN[shift]
    if shift == "nachmittag" and temp >= HOT_TEMP:
        g *= FACTOR_HOT
    if shift == "morgen" and temp < COLD_TEMP:
        g *= FACTOR_COLD
    if school:
        g *= FACTOR_SCHOOL_HOLIDAY
    if bridge:
        g *= FACTOR_BRIDGE_DAY
    if holiday:
        g *= FACTOR_HOLIDAY
    if d.month == 12:
        g *= FACTOR_DECEMBER
    g *= rng.normal(1, NOISE_SD)
    return max(0, round(g))


def generate_rows(start: date = START, end: date = END, seed: int = SEED,
                  ferien_csv: Path | str = SCHOOL_HOLIDAYS_CSV) -> list[dict]:
    rng = np.random.default_rng(seed)
    feiertage = holidays.Switzerland(subdiv=config.CANTON, years=range(start.year, end.year + 2))
    ferien = load_school_holidays(ferien_csv)
    rows = []
    d = start
    while d <= end:
        if d.weekday() in config.OPEN_WEEKDAYS:
            temp, rain_mm = simulate_weather(d, rng)
            holiday = d in feiertage
            bridge = is_bridge_day(d, feiertage)
            school = is_school_holiday(d, ferien)
            for shift in config.SHIFTS:
                rows.append({
                    "date": d.isoformat(), "weekday": d.weekday(), "shift": shift,
                    "guests": guests_for(shift, d, temp, rain_mm, holiday, bridge, school, rng),
                    "temp_max": temp, "rain_mm": rain_mm, "is_holiday": int(holiday),
                    "is_bridge_day": int(bridge), "is_school_holiday": int(school),
                    "month": d.month,
                })
        d += timedelta(days=1)
    return rows


def write_history(rows: list[dict], db_path: Path | str = config.DB_PATH) -> None:
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as con:
        con.execute("DROP TABLE IF EXISTS history")
        con.execute(SCHEMA)
        con.executemany(f"INSERT INTO history VALUES ({', '.join('?' * len(COLUMNS))})",
                        [tuple(r[c] for c in COLUMNS) for r in rows])


def plot(rows: list[dict], out: Path | str) -> None:
    """Kontrollplot: Gäste pro Schicht im Wochenmittel über die ganze Zeit."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import pandas as pd

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["date"])
    fig, ax = plt.subplots(figsize=(11, 4))
    for shift in config.SHIFTS:
        woche = df[df["shift"] == shift].set_index("date")["guests"].resample("W").mean()
        ax.plot(woche.index, woche.values, label=shift)
    ax.set_title("Synthetische Gästezahlen (Wochenmittel pro Schicht)")
    ax.set_ylabel("Gäste")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out, dpi=120)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--plot", action="store_true", help="Kontrollplot nach docs/testdaten.png")
    p.add_argument("--db", default=str(config.DB_PATH))
    args = p.parse_args()

    rows = generate_rows()
    write_history(rows, args.db)
    print(f"{len(rows)} Zeilen ({len(rows) // 2} offene Tage) nach {args.db} geschrieben")
    if args.plot:
        plot(rows, config.ROOT / "docs" / "testdaten.png")
        print("Kontrollplot nach docs/testdaten.png geschrieben")


if __name__ == "__main__":
    main()
