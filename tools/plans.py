"""Freigegebene Pläne speichern (Tabelle approved_plans). Aufgabe B5.

Simuliert «Schichtplan übermitteln». Wird ausschliesslich vom commit-Node aufgerufen,
damit nachweisbar nichts ohne menschliche Freigabe gespeichert wird.

Neu freigeben: Kommt nach der Freigabe eine neue Reservation für die Woche dazu, wird der
Plan als «muss neu freigegeben werden» markiert (plan_ungueltig_machen). Er bleibt sichtbar,
blockiert die Planung der Woche aber nicht mehr. Wird der neue Plan freigegeben, ersetzt er
den alten (save_approved_plan löscht markierte Pläne mit überlappenden Tagen).
"""
import sqlite3
import uuid
from contextlib import closing
from datetime import date, datetime, timedelta
from pathlib import Path

import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS approved_plans (
    plan_id TEXT, created_at TEXT, date TEXT, shift TEXT,
    kueche INT, service INT, abwasch INT, guests_planned INT
)
"""


def save_approved_plan(staffing: list[dict], db_path: Path | str | None = None) -> str:
    """Schreibt alle Zeilen eines Plans unter einer neuen plan_id und gibt diese zurück."""
    db_path = Path(db_path or config.DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    plan_id = uuid.uuid4().hex[:8]
    created_at = datetime.now().isoformat(timespec="seconds")
    rows = [(plan_id, created_at, r["date"], r["shift"], r["kueche"], r["service"],
             r["abwasch"], r["guests_planned"]) for r in staffing]
    # closing: «with con» committet nur; ohne close bleibt die Datei unter Windows gesperrt
    tage = sorted(r["date"] for r in staffing)
    with closing(sqlite3.connect(db_path)) as con, con:
        _schema(con)
        if tage:                                   # ersetzt alte, ungültig markierte Pläne
            con.execute("DELETE FROM approved_plans WHERE needs_reapproval = 1 AND plan_id IN "
                        "(SELECT plan_id FROM approved_plans WHERE date BETWEEN ? AND ?)",
                        (tage[0], tage[-1]))
        con.executemany("INSERT INTO approved_plans (plan_id, created_at, date, shift, kueche, "
                        "service, abwasch, guests_planned) VALUES (?,?,?,?,?,?,?,?)", rows)
    return plan_id


def _schema(con) -> None:
    con.execute(SCHEMA)
    spalten = {row[1] for row in con.execute("PRAGMA table_info(approved_plans)")}
    if "needs_reapproval" not in spalten:          # Datenbank von vor «neu freigeben»
        con.execute("ALTER TABLE approved_plans ADD COLUMN needs_reapproval INT DEFAULT 0")
        con.execute("ALTER TABLE approved_plans ADD COLUMN reapproval_reason TEXT")


def plan_ungueltig_machen(datum: str, grund: str, db_path: Path | str | None = None) -> list[dict]:
    """Markiert gültige freigegebene Pläne, deren Woche datum enthält. Gibt sie zurück."""
    db_path = Path(db_path or config.DB_PATH)
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as con, con:
        _schema(con)
        ids = [r[0] for r in con.execute(
            "SELECT plan_id FROM approved_plans GROUP BY plan_id "
            "HAVING MIN(date) <= ? AND MAX(date) >= ? AND MAX(needs_reapproval) = 0",
            (datum, datum))]
        con.executemany("UPDATE approved_plans SET needs_reapproval = 1, reapproval_reason = ? "
                        "WHERE plan_id = ?", [(grund, i) for i in ids])
    return [p for p in list_approved_plans(db_path) if p["plan_id"] in ids]


def count_approved_rows(db_path: Path | str | None = None) -> int:
    """Hilfsfunktion für Tests: Anzahl gespeicherter Planzeilen."""
    db_path = Path(db_path or config.DB_PATH)
    if not db_path.exists():
        return 0
    with closing(sqlite3.connect(db_path)) as con, con:
        _schema(con)
        return con.execute("SELECT COUNT(*) FROM approved_plans").fetchone()[0]


def _lesen(sql: str, args: tuple = (), db_path: Path | str | None = None) -> list[tuple]:
    db_path = Path(db_path or config.DB_PATH)
    if not db_path.exists():
        return []
    with closing(sqlite3.connect(db_path)) as con, con:
        _schema(con)
        return con.execute(sql, args).fetchall()


def list_approved_plans(db_path: Path | str | None = None) -> list[dict]:
    """Ein Eintrag pro freigegebenem Plan (Woche), neueste Woche zuerst."""
    rows = _lesen("SELECT plan_id, MIN(date), MAX(date), MAX(created_at), MAX(needs_reapproval), "
                  "MAX(reapproval_reason) FROM approved_plans GROUP BY plan_id "
                  "ORDER BY MIN(date) DESC, MAX(created_at) DESC", db_path=db_path)
    return [{"plan_id": i, "von": v, "bis": b, "created_at": c, "neu_freigeben": bool(n),
             "grund": g} for i, v, b, c, n, g in rows]


def get_approved_plan(plan_id: str, db_path: Path | str | None = None) -> list[dict]:
    """Alle Zeilen eines freigegebenen Plans, sortiert nach Tag und Schicht."""
    rows = _lesen("SELECT date, shift, guests_planned, kueche, service, abwasch FROM approved_plans "
                  "WHERE plan_id = ?", (plan_id,), db_path=db_path)
    reihenfolge = {s: i for i, s in enumerate(config.SHIFTS)}
    return sorted(({"date": d, "shift": s, "guests_planned": g, "kueche": k, "service": se,
                    "abwasch": a} for d, s, g, k, se, a in rows),
                  key=lambda r: (r["date"], reihenfolge.get(r["shift"], 99)))


def approved_plan_overlapping(start_date: str, days: int,
                              db_path: Path | str | None = None) -> dict | None:
    """Gültiger freigegebener Plan mit Tagen im Zeitraum [start_date, start_date + days).

    Pläne, die neu freigegeben werden müssen, zählen nicht: Die Woche darf neu geplant werden.
    """
    ende = (date.fromisoformat(start_date) + timedelta(days=days)).isoformat()
    ids = {r[0] for r in _lesen("SELECT DISTINCT plan_id FROM approved_plans "
                                "WHERE date >= ? AND date < ?", (start_date, ende), db_path)}
    return next((p for p in list_approved_plans(db_path)
                 if p["plan_id"] in ids and not p["neu_freigeben"]), None)
