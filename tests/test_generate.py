"""Tests für den Testdaten-Generator (A2) und das automatische Training (A3)."""
import importlib.util
import sqlite3
from datetime import date

import holidays

import config

_spec = importlib.util.spec_from_file_location("generate", config.ROOT / "data" / "generate.py")
generate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(generate)

FEIERTAGE = holidays.Switzerland(subdiv="SO", years=range(2024, 2028))


def test_zwei_schichten_pro_offenem_tag_und_kein_sonntag():
    rows = generate.generate_rows(date(2025, 3, 3), date(2025, 3, 16))   # zwei Wochen
    assert len(rows) == 12 * 2
    assert {r["weekday"] for r in rows} == set(config.OPEN_WEEKDAYS)
    assert {r["shift"] for r in rows} == set(config.SHIFTS)
    assert all(r["guests"] >= 0 for r in rows)


def test_gleicher_seed_gleiche_daten():
    a = generate.generate_rows(date(2025, 1, 6), date(2025, 1, 11))
    b = generate.generate_rows(date(2025, 1, 6), date(2025, 1, 11))
    assert a == b


def test_spalten_wie_im_vertrag():
    row = generate.generate_rows(date(2025, 1, 6), date(2025, 1, 6))[0]
    assert tuple(row) == generate.COLUMNS


def test_brueckentag_nach_auffahrt():
    assert generate.is_bridge_day(date(2025, 5, 30), FEIERTAGE)       # Fr nach Auffahrt
    assert not generate.is_bridge_day(date(2025, 5, 29), FEIERTAGE)   # Auffahrt selbst
    assert not generate.is_bridge_day(date(2025, 6, 6), FEIERTAGE)    # gewöhnlicher Freitag


def test_schulferien_aus_csv():
    ferien = generate.load_school_holidays()
    assert generate.is_school_holiday(date(2025, 10, 1), ferien)       # Herbstferien
    assert generate.is_school_holiday(date(2025, 10, 17), ferien)      # letzter Ferientag
    assert not generate.is_school_holiday(date(2025, 10, 20), ferien)  # Schulbeginn


def test_history_wird_ersetzt_andere_tabellen_bleiben(tmp_path):
    db = tmp_path / "restaurant.db"
    with sqlite3.connect(db) as con:
        con.execute("CREATE TABLE corrections (id INTEGER)")
        con.execute("INSERT INTO corrections VALUES (1)")
    rows = generate.generate_rows(date(2025, 1, 6), date(2025, 1, 11))
    generate.write_history(rows, db)
    generate.write_history(rows, db)                                    # zweimal: keine Duplikate
    with sqlite3.connect(db) as con:
        assert con.execute("SELECT COUNT(*) FROM history").fetchone()[0] == len(rows)
        assert con.execute("SELECT COUNT(*) FROM corrections").fetchone()[0] == 1


def test_modelle_werden_trainiert_wenn_pkl_fehlt(tmp_path):
    from forecast.train import load_models

    db = tmp_path / "restaurant.db"
    generate.write_history(generate.generate_rows(), db)
    models_dir = tmp_path / "models"
    models = load_models(db, models_dir)
    assert set(models) == set(config.SHIFTS)
    assert (models_dir / "morgen.pkl").exists()
    assert models["nachmittag"].params["rain"] < 0                     # Regen-Effekt erkannt
    assert models["morgen"].params["C(weekday)[T.5]"] < 0              # Samstagmorgen ruhiger
    assert set(load_models(db, models_dir)) == set(config.SHIFTS)      # zweiter Aufruf lädt
