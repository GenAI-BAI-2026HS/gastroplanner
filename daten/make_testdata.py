"""
Erzeugt restaurant.db: synthetische Testdaten für ein Mittags-/Takeaway-Geschäft.
Aufruf:  python make_testdata.py      (schreibt restaurant.db ins aktuelle Verzeichnis)

Modell (alle Konstanten unten anpassbar, Seed fix -> reproduzierbar):
- Kunden pro offenem Mittag ~ Poisson, kalibriert auf Ø AVG_CUSTOMERS (50) im letzten Jahr,
  davor schwächer wegen Wachstumstrend GROWTH (3 Jahre Historie).
  Einflussfaktoren: Wochentag, Schulferien, Brückentage, Wetter (Regen, Hitze, Kälte).
- Jeder Kunde nimmt genau ein Menü (Vegi oder Fleisch).
- 80 % nehmen zusätzlich Suppe ODER Salat sowie ein Getränk.
  Suppe vs. Salat hängt an der Mittagstemperatur, also de facto an der Jahreszeit.
- Geschlossen: Wochenende und Feiertage (Kanton Zürich).
- Schulferien-Daten sind Näherungswerte, bei Bedarf durch echte Daten ersetzen.
"""
import math
import os
import sqlite3
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd

DB = "restaurant.db"
SEED = 42

HIST_START, HIST_END = date(2023, 10, 16), date(2026, 10, 9)   # Verkaufshistorie (3 Jahre)
TODAY = date(2026, 10, 12)                                       # ab hier: Wetterprognose
CAL_END = date(2026, 12, 31)                                     # Kalender bis Jahresende
WEATHER_END = date(2026, 10, 25)

AVG_CUSTOMERS = 50           # Ø Kunden pro offenem Mittag im letzten Jahr
GROWTH = 0.04                # Wachstum pro Jahr (frühere Jahre entsprechend schwächer)
P_SIDE_AND_DRINK = 0.80      # Anteil Kunden mit Suppe/Salat UND Getränk
P_VEGI = 0.45
P_TAKEAWAY = 0.60
WEEKDAY_FACTOR = {0: 0.92, 1: 1.04, 2: 1.06, 3: 1.04, 4: 0.94}
BRIDGE_FACTOR = 0.60         # Freitag nach Auffahrt

SCHOOL_HOLIDAYS = [          # (Name, von, bis)  ungefähre Werte, bei Bedarf durch echte ersetzen
    ("Herbstferien", date(2023, 10, 2), date(2023, 10, 13)),
    ("Weihnachtsferien", date(2023, 12, 25), date(2024, 1, 5)),
    ("Sportferien", date(2024, 2, 5), date(2024, 2, 16)),
    ("Frühlingsferien", date(2024, 4, 22), date(2024, 5, 3)),
    ("Sommerferien", date(2024, 7, 15), date(2024, 8, 16)),
    ("Herbstferien", date(2024, 10, 7), date(2024, 10, 18)),
    ("Weihnachtsferien", date(2024, 12, 23), date(2025, 1, 3)),
    ("Sportferien", date(2025, 2, 10), date(2025, 2, 21)),
    ("Frühlingsferien", date(2025, 4, 21), date(2025, 5, 2)),
    ("Sommerferien", date(2025, 7, 14), date(2025, 8, 15)),
    ("Herbstferien", date(2025, 10, 6), date(2025, 10, 17)),
    ("Weihnachtsferien", date(2025, 12, 22), date(2026, 1, 2)),
    ("Sportferien", date(2026, 2, 9), date(2026, 2, 20)),
    ("Frühlingsferien", date(2026, 4, 20), date(2026, 5, 1)),
    ("Sommerferien", date(2026, 7, 13), date(2026, 8, 14)),
    ("Herbstferien", date(2026, 10, 5), date(2026, 10, 16)),
    ("Weihnachtsferien", date(2026, 12, 21), date(2027, 1, 1)),
]
SCHOOL_FACTOR = {"Herbstferien": 0.88, "Weihnachtsferien": 0.65, "Sportferien": 0.88,
                 "Frühlingsferien": 0.88, "Sommerferien": 0.80}

WEEKDAYS = ["Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag"]

MENUS = [  # menu_id, Name, Kategorie, Preis CHF
    ("vegi_menu", "Gemüse-Curry mit Reis", "menu", 17.50),
    ("fleisch_menu", "Pouletgeschnetzeltes mit Reis", "menu", 19.50),
    ("suppe", "Saisonsuppe", "beilage", 6.50),
    ("salat", "Gemischter Salat", "beilage", 6.50),
    ("getraenk", "Getränk 3.3 dl", "getraenk", 3.50),
]

RECIPES = [  # menu_id, Zutat, Menge pro Portion, Einheit
    ("vegi_menu", "Reis", 90, "g"), ("vegi_menu", "Kichererbsen", 80, "g"),
    ("vegi_menu", "Gemüse gemischt", 150, "g"), ("vegi_menu", "Kokosmilch", 80, "ml"),
    ("vegi_menu", "Currypaste", 10, "g"), ("vegi_menu", "Zwiebeln", 30, "g"),
    ("vegi_menu", "Menüschale", 1, "Stück"),
    ("fleisch_menu", "Pouletbrust", 130, "g"), ("fleisch_menu", "Rahm", 50, "ml"),
    ("fleisch_menu", "Champignons", 60, "g"), ("fleisch_menu", "Reis", 90, "g"),
    ("fleisch_menu", "Zwiebeln", 30, "g"), ("fleisch_menu", "Menüschale", 1, "Stück"),
    ("suppe", "Gemüse gemischt", 100, "g"), ("suppe", "Gemüsebouillon", 8, "g"),
    ("suppe", "Rahm", 20, "ml"), ("suppe", "Zwiebeln", 15, "g"),
    ("suppe", "Suppenbecher", 1, "Stück"),
    ("salat", "Blattsalat", 80, "g"), ("salat", "Tomaten", 50, "g"),
    ("salat", "Gurken", 40, "g"), ("salat", "Salatdressing", 30, "ml"),
    ("salat", "Salatschale", 1, "Stück"),
    ("getraenk", "Getränk 3.3 dl", 1, "Stück"),
]

# Zutat: (Einheit, Lieferant, Lieferzeit Tage, Haltbarkeit Tage, Lagerreichweite in Tagen)
INGREDIENTS = {
    "Reis": ("g", "Trockenwaren Hug", 3, 365, 3.0),
    "Kichererbsen": ("g", "Trockenwaren Hug", 3, 365, 3.0),
    "Kokosmilch": ("ml", "Trockenwaren Hug", 3, 365, 3.0),
    "Currypaste": ("g", "Trockenwaren Hug", 3, 365, 4.0),
    "Gemüsebouillon": ("g", "Trockenwaren Hug", 3, 365, 4.0),
    "Salatdressing": ("ml", "Trockenwaren Hug", 3, 60, 3.0),
    "Gemüse gemischt": ("g", "Frischgemüse Müller", 1, 4, 1.0),
    "Zwiebeln": ("g", "Frischgemüse Müller", 1, 14, 2.0),
    "Champignons": ("g", "Frischgemüse Müller", 1, 5, 1.0),
    "Blattsalat": ("g", "Frischgemüse Müller", 1, 4, 1.0),
    "Tomaten": ("g", "Frischgemüse Müller", 1, 6, 1.0),
    "Gurken": ("g", "Frischgemüse Müller", 1, 7, 1.0),
    "Pouletbrust": ("g", "Metzgerei Keller", 2, 4, 1.0),
    "Rahm": ("ml", "Molkerei Alpenrahm", 2, 10, 1.5),
    "Menüschale": ("Stück", "Verpackung Plus", 5, 1000, 6.0),
    "Suppenbecher": ("Stück", "Verpackung Plus", 5, 1000, 6.0),
    "Salatschale": ("Stück", "Verpackung Plus", 5, 1000, 6.0),
    "Getränk 3.3 dl": ("Stück", "Getränkehandel Brunner", 3, 180, 4.0),
}


def easter(y: int) -> date:
    a, b, c = y % 19, y // 100, y % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return date(y, month, day)


def holidays(year: int) -> dict:
    e = easter(year)
    return {
        date(year, 1, 1): "Neujahr", date(year, 1, 2): "Berchtoldstag",
        e - timedelta(days=2): "Karfreitag", e + timedelta(days=1): "Ostermontag",
        date(year, 5, 1): "Tag der Arbeit", e + timedelta(days=39): "Auffahrt",
        e + timedelta(days=50): "Pfingstmontag", date(year, 8, 1): "Bundesfeier",
        date(year, 12, 25): "Weihnachten", date(year, 12, 26): "Stephanstag",
    }


def seasonal_temp(d: date) -> float:
    """Tagesmitteltemperatur Zürich, grob: Jahresmittel 10 °C, Amplitude 11.5 °C."""
    return 10.0 + 11.5 * math.sin(2 * math.pi * (d.timetuple().tm_yday - 110) / 365)


def main():
    rng = np.random.default_rng(SEED)
    days = [HIST_START + timedelta(n) for n in range((CAL_END - HIST_START).days + 1)]

    # --- Kalender -----------------------------------------------------------
    hol = {}
    for y in (2023, 2024, 2025, 2026):
        hol.update(holidays(y))
    bridge = {easter(y) + timedelta(days=40) for y in (2023, 2024, 2025, 2026)}
    cal_rows = []
    for d in days:
        sh = next((n for n, s, e in SCHOOL_HOLIDAYS if s <= d <= e), None)
        cal_rows.append(dict(
            date=d.isoformat(), weekday=d.weekday(), weekday_name=WEEKDAYS[d.weekday()],
            is_open=int(d.weekday() < 5 and d not in hol),
            holiday=hol.get(d), school_holiday=sh, bridge_day=int(d in bridge)))
    cal = pd.DataFrame(cal_rows)

    # --- Wetter (Historie bis gestern, ab TODAY Prognose) ------------------------
    w_rows, anom, wet = [], 0.0, False
    for d in days:
        if d > WEATHER_END:
            break
        anom = 0.75 * anom + rng.normal(0, 2.6)
        wet = rng.random() < (0.60 if wet else 0.25)
        mean_t = seasonal_temp(d) + anom - (2.0 if wet else 0.0)       # Tagesmittel
        temp = mean_t + 4.0                                            # Mittagstemperatur
        precip = round(float(rng.exponential(6.0) + 0.3), 1) if wet else 0.0
        w_rows.append(dict(date=d.isoformat(), temp_c=round(float(temp), 1),
                           temp_min_c=round(float(mean_t - 4.0 + rng.normal(0, 1.0)), 1),
                           temp_max_c=round(float(temp + abs(rng.normal(0, 0.8))), 1),
                           precip_mm=precip, is_forecast=int(d >= TODAY)))
    weather = pd.DataFrame(w_rows)

    # --- Erwartete Kundenzahl pro offenem Tag (vor Kalibrierung) ------------------
    info = cal.merge(weather, on="date")
    info = info[(info["date"] >= HIST_START.isoformat()) & (info["date"] <= HIST_END.isoformat())
                & (info["is_open"] == 1)].copy()

    def factor(r) -> float:
        f = WEEKDAY_FACTOR[r.weekday] * SCHOOL_FACTOR.get(r.school_holiday, 1.0)
        f *= BRIDGE_FACTOR if r.bridge_day else 1.0
        f *= 0.88 if r.precip_mm >= 5 else (0.96 if r.precip_mm >= 0.5 else 1.0)
        f *= 0.92 if r.temp_c >= 30 else (0.93 if r.temp_c <= 0 else 1.0)
        if 18 <= r.temp_c <= 26 and r.precip_mm < 0.5:
            f *= 1.03
        return f

    info["mult"] = info.apply(factor, axis=1)
    info["mult"] *= info["date"].map(
        lambda x: (1 + GROWTH) ** ((date.fromisoformat(x) - HIST_END).days / 365))
    last_year = info["date"] > (HIST_END - timedelta(days=365)).isoformat()
    base = AVG_CUSTOMERS / info.loc[last_year, "mult"].mean()

    # --- Verkäufe pro Kunde erzeugen ------------------------------------------
    lines, order_id = [], 0
    for r in info.itertuples():
        d = date.fromisoformat(r.date)
        n = int(rng.poisson(base * r.mult * rng.lognormal(0, 0.05)))
        p_veg = min(0.9, P_VEGI + (0.05 if r.temp_c >= 22 else 0.0) + (0.03 if r.weekday == 4 else 0.0))
        p_soup = 1 / (1 + math.exp((r.temp_c - 14) / 3))
        p_take = min(0.9, P_TAKEAWAY + (0.10 if r.precip_mm >= 0.5 else 0.0))
        minutes = np.clip(rng.normal(740, 25, n), 675, 825)          # Peak ca. 12:20
        for i in range(n):
            order_id += 1
            ts = (datetime.combine(d, datetime.min.time())
                  + timedelta(minutes=float(minutes[i]))).replace(microsecond=0).isoformat(sep=" ")
            ch = "takeaway" if rng.random() < p_take else "vor_ort"
            lines.append((order_id, ts, "vegi_menu" if rng.random() < p_veg else "fleisch_menu", 1, ch))
            if rng.random() < P_SIDE_AND_DRINK:
                side = "suppe" if rng.random() < p_soup else "salat"
                lines.append((order_id, ts, side, 1, ch))
                lines.append((order_id, ts, "getraenk", 1, ch))
    sales = pd.DataFrame(lines, columns=["order_id", "sold_at", "menu_id", "qty", "channel"])

    # --- Lagerbestand aus durchschnittlichem Tagesbedarf ------------------------
    rec = pd.DataFrame(RECIPES, columns=["menu_id", "ingredient", "qty_per_portion", "unit"])
    cut = (HIST_END - timedelta(days=365)).isoformat()
    per_menu = sales[sales["sold_at"] > cut].groupby("menu_id")["qty"].sum().reset_index()
    dem = per_menu.merge(rec, on="menu_id")
    dem["total"] = dem["qty"] * dem["qty_per_portion"]
    per_day = dem.groupby("ingredient")["total"].sum() / int(last_year.sum())
    inv_rows = []
    for ing, (unit, sup, lead, shelf, days_cover) in INGREDIENTS.items():
        on_hand = round(per_day[ing] * days_cover * rng.uniform(0.8, 1.2))
        inv_rows.append((ing, on_hand, unit, sup, lead, shelf))

    # --- Schreiben --------------------------------------------------------------
    if os.path.exists(DB):
        os.remove(DB)
    con = sqlite3.connect(DB)
    con.executescript("""
    CREATE TABLE menus(menu_id TEXT PRIMARY KEY, name TEXT, category TEXT, price_chf REAL);
    CREATE TABLE sales(id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INT, sold_at TEXT,
                       menu_id TEXT REFERENCES menus(menu_id), qty INT, channel TEXT);
    CREATE TABLE recipes(menu_id TEXT, ingredient TEXT, qty_per_portion REAL, unit TEXT);
    CREATE TABLE inventory(ingredient TEXT PRIMARY KEY, on_hand REAL, unit TEXT, supplier TEXT,
                           lead_time_days INT, shelf_life_days INT);
    CREATE TABLE calendar(date TEXT PRIMARY KEY, weekday INT, weekday_name TEXT, is_open INT,
                          holiday TEXT, school_holiday TEXT, bridge_day INT);
    CREATE TABLE weather(date TEXT PRIMARY KEY, temp_c REAL, temp_min_c REAL, temp_max_c REAL,
                         precip_mm REAL, is_forecast INT);
    CREATE INDEX idx_sales_sold_at ON sales(sold_at);
    """)
    con.executemany("INSERT INTO menus VALUES (?,?,?,?)", MENUS)
    con.executemany("INSERT INTO sales(order_id, sold_at, menu_id, qty, channel) VALUES (?,?,?,?,?)", lines)
    con.executemany("INSERT INTO recipes VALUES (?,?,?,?)", RECIPES)
    con.executemany("INSERT INTO inventory VALUES (?,?,?,?,?,?)", inv_rows)
    cal.to_sql("calendar", con, if_exists="append", index=False)
    weather.to_sql("weather", con, if_exists="append", index=False)
    con.commit()
    con.close()

    # --- Kontrollausgabe -------------------------------------------------------
    cust = sales[sales["menu_id"].isin(["vegi_menu", "fleisch_menu"])].copy()
    cust["d"] = cust["sold_at"].str[:10]
    daily = cust.groupby("d").size().rename("kunden").reset_index().merge(
        cal, left_on="d", right_on="date").merge(weather, on="date")
    print(f"Offene Tage: {len(daily)}   Bestellungen: {order_id}   Zeilen: {len(sales)}")
    print(f"Ø Kunden/Tag: {daily['kunden'].mean():.1f}")
    print("\nØ Kunden nach Wochentag:\n", daily.groupby("weekday_name")["kunden"].mean().round(1).to_string())
    print("\nØ Kunden Ferien vs. normal:",
          round(daily[daily["school_holiday"].notna()]["kunden"].mean(), 1), "vs.",
          round(daily[daily["school_holiday"].isna()]["kunden"].mean(), 1))
    print("Ø Kunden Regen (>=5mm) vs. trocken:",
          round(daily[daily["precip_mm"] >= 5]["kunden"].mean(), 1), "vs.",
          round(daily[daily["precip_mm"] < 0.5]["kunden"].mean(), 1))
    daily["jahr"] = daily["d"].str[:4]
    print(f"Ø Kunden letztes Jahr: {daily.loc[daily['d'] > cut, 'kunden'].mean():.1f}")
    print("Ø Kunden je Kalenderjahr:", daily.groupby("jahr")["kunden"].mean().round(1).to_dict())
    print("Hitzetage (>=30°C):", int((daily["temp_c"] >= 30).sum()),
          " Frosttage (<=0°C):", int((daily["temp_c"] <= 0).sum()),
          " Brückentage:", int(daily["bridge_day"].sum()))
    m = sales.groupby("menu_id")["qty"].sum()
    print(f"\nAnteil Kunden mit Beilage+Getränk: {m['getraenk'] / m[['vegi_menu', 'fleisch_menu']].sum():.1%}")
    s = sales[sales["menu_id"].isin(["suppe", "salat"])].copy()
    s["monat"] = s["sold_at"].str[:7]
    print("\nSuppenanteil an Beilagen pro Monat:\n",
          s.groupby("monat").apply(lambda g: (g["menu_id"] == "suppe").mean(), include_groups=False)
          .round(2).to_string())


if __name__ == "__main__":
    main()
