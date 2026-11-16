"""Reservationen für Anlässe (Tabelle reservations).

Reserviert werden kann nur für Anlässe ab config.RESERVATION_MIN_PERSONEN (10) Personen,
z. B. Firmenessen oder Geburtstag. Jede Reservation wird zusätzlich zur Gästeprognose
eingeplant; kleinere Gruppen kommen ohne Reservation und sind in der Prognose enthalten.

Wer liest und schreibt:
- save_reservation nur im Node reservation_speichern, also erst nachdem die Person die
  erfassten Angaben bestätigt hat (agent/nodes/reservation.py).
- get_reservations im Node staffing: Reservierte Personen werden pro Tag und Schicht zur
  Gästeprognose addiert (wie Anlässe, planning/staffing.py).

Datenschutz: Name und Telefonnummer werden nur hier gespeichert und in der App angezeigt.
Für die Planung und an das LLM geht nur die Summe der Personen pro Tag und Schicht
(reserved_per_shift).

Die Prüfungen (pruefen, telefon_normalisieren) rechnet Python, nicht das LLM.
"""
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS reservations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, phone TEXT NOT NULL, persons INT NOT NULL,
    date TEXT NOT NULL, shift TEXT NOT NULL, time TEXT, created_at TEXT NOT NULL,
    occasion TEXT
)
"""

_TELEFON = re.compile(r"^\+?\d{9,15}$")


def telefon_normalisieren(telefon: str) -> str | None:
    """«079 123 45 67» → «0791234567». None, wenn es keine plausible Telefonnummer ist."""
    roh = re.sub(r"[\s\-/().]", "", str(telefon or ""))
    if roh.startswith("00"):
        roh = "+" + roh[2:]
    return roh if _TELEFON.match(roh) else None


def schicht_aus_uhrzeit(uhrzeit: str | None) -> str | None:
    """«12:30» → morgen, «18:00» → nachmittag. None, wenn ausserhalb der Öffnungszeiten."""
    if not uhrzeit:
        return None
    try:
        t = datetime.strptime(uhrzeit.strip(), "%H:%M").strftime("%H:%M")
    except ValueError:
        return None
    for schicht, (von, bis) in config.SHIFT_TIMES.items():
        if von <= t < bis:
            return schicht
    return None


def pruefen(r: dict, heute: date) -> dict[str, str]:
    """Prüft eine Reservation. Rückgabe: {feld: Fehlermeldung}; leer = gültig."""
    fehler = {}
    if r.get("telefon") is not None and telefon_normalisieren(r["telefon"]) is None:
        fehler["telefon"] = f"«{r['telefon']}» ist keine gültige Telefonnummer."
    if r.get("personen") is not None:
        p = r["personen"]
        if not isinstance(p, int) or not 1 <= p <= config.CAPACITY_PER_SHIFT:
            fehler["personen"] = (f"Die Anzahl Personen muss zwischen 1 und "
                                  f"{config.CAPACITY_PER_SHIFT} liegen.")
    if r.get("datum") is not None:
        try:
            d = date.fromisoformat(r["datum"])
        except ValueError:
            fehler["datum"] = f"«{r['datum']}» ist kein gültiges Datum."
        else:
            if d < heute:
                fehler["datum"] = f"Der {d:%d.%m.%Y} liegt in der Vergangenheit."
            elif d.weekday() not in config.OPEN_WEEKDAYS:
                fehler["datum"] = f"Am {d:%d.%m.%Y} ist Ruhetag."
    if r.get("uhrzeit") and schicht_aus_uhrzeit(r["uhrzeit"]) is None:
        von, bis = config.SHIFT_TIMES[config.SHIFTS[0]][0], config.SHIFT_TIMES[config.SHIFTS[-1]][1]
        fehler["uhrzeit"] = f"Um {r['uhrzeit']} ist das Restaurant geschlossen ({von}–{bis})."
    if r.get("schicht") is not None and r["schicht"] not in config.SHIFTS:
        fehler["schicht"] = f"Unbekannte Schicht: {r['schicht']}"
    return fehler


def reservierbar(persons: int) -> bool:
    """Reservationen gibt es nur für Anlässe ab config.RESERVATION_MIN_PERSONEN Personen."""
    return int(persons) >= config.RESERVATION_MIN_PERSONEN


def save_reservation(name: str, phone: str, persons: int, date_: str, shift: str,
                     time: str | None = None, occasion: str | None = None,
                     db_path: Path | str | None = None) -> int:
    """Speichert eine Reservation und gibt ihre ID zurück. Ungültige Werte → ValueError."""
    telefon = telefon_normalisieren(phone)
    if not (name or "").strip():
        raise ValueError("Name fehlt")
    if telefon is None:
        raise ValueError(f"Ungültige Telefonnummer: {phone}")
    if shift not in config.SHIFTS:
        raise ValueError(f"Unbekannte Schicht: {shift}")
    if not isinstance(persons, int) or not reservierbar(persons):
        raise ValueError(f"Reservationen erst ab {config.RESERVATION_MIN_PERSONEN} Personen")
    date.fromisoformat(date_)
    with _verbinden(db_path) as con:
        cur = con.execute(
            "INSERT INTO reservations (name, phone, persons, date, shift, time, created_at, occasion) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (name.strip(), telefon, int(persons), date_, shift, time,
             datetime.now().isoformat(timespec="seconds"), (occasion or "").strip() or None))
        return cur.lastrowid


def get_reservations(start_date: str | None = None, days: int | None = None,
                     db_path: Path | str | None = None) -> list[dict]:
    """Reservationen, optional nur im Zeitraum [start_date, start_date + days)."""
    sql = "SELECT id, name, phone, persons, date, shift, time, occasion FROM reservations"
    args = []
    if start_date:
        ende = (date.fromisoformat(start_date) + timedelta(days=days or config.HORIZON_DAYS)).isoformat()
        sql += " WHERE date >= ? AND date < ?"
        args = [start_date, ende]
    with _verbinden(db_path) as con:
        rows = con.execute(sql + " ORDER BY date, shift, time, id", args).fetchall()
    return [{"id": i, "name": n, "phone": p, "persons": pe, "date": d, "shift": s, "time": t,
             "occasion": o} for i, n, p, pe, d, s, t, o in rows]


def reserved_per_shift(reservations: list[dict]) -> list[dict]:
    """Summe der reservierten Personen pro Tag und Schicht, ohne Namen und Telefonnummern.

    Format wie ein Anlass, damit calculate_staffing sie zur Prognose addiert:
    [{"date": "2026-10-30", "shift": "nachmittag", "persons": 42, "type": "Reservationen"}]
    """
    summe: dict[tuple[str, str], int] = {}
    for r in reservations:
        key = (r["date"], r["shift"])
        summe[key] = summe.get(key, 0) + int(r["persons"])
    return [{"date": d, "shift": s, "persons": p, "type": "Reservationen"}
            for (d, s), p in sorted(summe.items())]


def finde_bestehende(r: dict, bestehende: list[dict]) -> tuple[dict | None, list[dict]]:
    """Ist die Reservation schon im System?

    Rückgabe (treffer, kandidaten):
    - treffer: gleicher Tag und gleiche Schicht und gleicher Name oder gleiche Telefonnummer
    - kandidaten: gleicher Tag, gleiche Schicht und gleiche Anzahl Personen (Name noch offen)
    """
    gleich = [x for x in bestehende if x["date"] == r.get("datum") and x["shift"] == r.get("schicht")]
    name = (r.get("name") or "").strip().lower()
    telefon = telefon_normalisieren(r.get("telefon") or "")
    for x in gleich:
        if name and (name in x["name"].lower() or x["name"].lower() in name):
            return x, []
        if telefon and telefon == x["phone"]:
            return x, []
    kandidaten = [x for x in gleich if r.get("personen") == x["persons"]]
    return None, kandidaten


@contextmanager
def _verbinden(db_path):
    """Verbindung mit Commit und Schliessen (Windows-Dateisperre, siehe tools/memory.py)."""
    db_path = Path(db_path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute(SCHEMA)
            spalten = {row[1] for row in con.execute("PRAGMA table_info(reservations)")}
            if "occasion" not in spalten:          # Datenbank von vor dem Feld «Grund»
                con.execute("ALTER TABLE reservations ADD COLUMN occasion TEXT")
            yield con
    finally:
        con.close()
