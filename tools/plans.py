"""Freigegebene Pläne speichern (Tabelle approved_plans). Owner: Person B (B5).

Simuliert «Schichtplan übermitteln». Wird ausschliesslich vom commit-Node aufgerufen,
damit nachweisbar nichts ohne menschliche Freigabe gespeichert wird.
"""
import sqlite3
import uuid
from datetime import datetime
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
    with sqlite3.connect(db_path) as con:
        con.execute(SCHEMA)
        con.executemany("INSERT INTO approved_plans VALUES (?,?,?,?,?,?,?,?)", rows)
    return plan_id


def count_approved_rows(db_path: Path | str | None = None) -> int:
    """Hilfsfunktion für Tests: Anzahl gespeicherter Planzeilen."""
    db_path = Path(db_path or config.DB_PATH)
    if not db_path.exists():
        return 0
    with sqlite3.connect(db_path) as con:
        con.execute(SCHEMA)
        return con.execute("SELECT COUNT(*) FROM approved_plans").fetchone()[0]
