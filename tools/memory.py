"""Langzeit-Memory: Korrekturen der Betriebsleitung (Tabelle corrections). Aufgabe C5.

Kurzzeit- vs. Langzeit-Memory:
- Kurzzeit = Checkpointer von LangGraph. Gilt nur innerhalb eines Gesprächs (thread_id).
- Langzeit = diese Tabelle. Gilt über alle Gespräche und Wochen hinweg.

Wer liest und schreibt (siehe agent/nodes/memory.py):
- get_corrections wird nur im Node staffing aufgerufen, vor jeder Berechnung.
- save_correction wird nur im Node memory aufgerufen, also erst nach «freigeben».
  Abgelehnte Korrekturen landen so nie im Gedächtnis.

Jede Korrektur ist eine eigene Zeile mit Notiz und Zeitstempel (nachvollziehbar, wer
wann was wollte). Mehrere Korrekturen für denselben Wochentag, dieselbe Schicht und
Rolle addieren sich in calculate_staffing, z. B. +1 und nochmals +1 = +2.

Datenschutz: Gespeichert werden nur Rollen und Anzahlen, keine Namen von Mitarbeitenden.
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS corrections (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    weekday INT NOT NULL, shift TEXT NOT NULL, role TEXT NOT NULL,
    delta INT NOT NULL, note TEXT, created_at TEXT NOT NULL
)
"""


def save_correction(weekday: int, shift: str, role: str, delta: int, note: str,
                    db_path: Path | str | None = None) -> None:
    """Speichert eine Korrektur, z. B. Freitag Nachmittag immer einen Service mehr.

    Prüft die Werte, bevor etwas gespeichert wird. Ungültige Angaben (Ruhetag, unbekannte
    Schicht oder Rolle, Delta 0) lösen einen ValueError aus, statt still falsche Daten
    ins Gedächtnis zu schreiben.
    """
    _pruefen(weekday, shift, role, delta)
    with _verbinden(db_path) as con:
        con.execute(
            "INSERT INTO corrections (weekday, shift, role, delta, note, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(weekday), shift, role, int(delta), (note or "").strip(),
             datetime.now().isoformat(timespec="seconds")),
        )


def get_corrections(db_path: Path | str | None = None) -> list[dict]:
    """Alle gespeicherten Korrekturen, älteste zuerst.

    Rückgabe: [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1, "note": "..."}]
    """
    with _verbinden(db_path) as con:
        rows = con.execute(
            "SELECT weekday, shift, role, delta, note FROM corrections ORDER BY id"
        ).fetchall()
    return [{"weekday": w, "shift": s, "role": r, "delta": d, "note": n or ""}
            for w, s, r, d, n in rows]


def _pruefen(weekday, shift, role, delta) -> None:
    if weekday not in config.OPEN_WEEKDAYS:
        raise ValueError(f"Wochentag {weekday} ist kein Öffnungstag {config.OPEN_WEEKDAYS}")
    if shift not in config.SHIFTS:
        raise ValueError(f"Unbekannte Schicht: {shift}")
    if role not in config.ROLES:
        raise ValueError(f"Unbekannte Rolle: {role}")
    if not isinstance(delta, int) or delta == 0:
        raise ValueError("delta muss eine ganze Zahl ungleich 0 sein")


@contextmanager
def _verbinden(db_path):
    """Verbindung mit Commit und Schliessen. «with sqlite3.connect()» allein committet nur
    und lässt die Datei offen; unter Windows bleibt sie dann gesperrt."""
    db_path = Path(db_path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    try:
        with con:
            con.execute(SCHEMA)
            yield con
    finally:
        con.close()
