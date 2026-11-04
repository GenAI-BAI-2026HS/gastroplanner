"""Tests für calculate_staffing (C2). Reine Funktion: Dicts rein, Plan raus."""
import json

import pytest

import config
from planning.staffing import calculate_staffing


def zeile(datum, schicht, upper, guests=None):
    return {"date": datum, "shift": schicht, "guests": guests or upper, "lower": 0, "upper": upper}


def finde(plan, datum, schicht):
    return next(r for r in plan if r["date"] == datum and r["shift"] == schicht)


# --- Abgleich mit den Team-Fixtures --------------------------------------------
def test_entspricht_fixture():
    forecast = json.loads((config.FIXTURES_DIR / "forecast_example.json").read_text())
    erwartet = json.loads((config.FIXTURES_DIR / "staffing_example.json").read_text())
    assert calculate_staffing(forecast) == erwartet


# --- Personalschlüssel -----------------------------------------------------------
def test_plant_mit_oberem_wert():
    plan = calculate_staffing([zeile("2026-11-09", "nachmittag", upper=31, guests=25)])
    assert plan[0]["guests_planned"] == 31
    assert plan[0]["service"] == 2                       # 31 / 30 aufgerundet (P-01)


@pytest.mark.parametrize("gaeste, service", [(1, 1), (30, 1), (31, 2), (60, 2), (61, 3)])
def test_service_p01(gaeste, service):
    assert calculate_staffing([zeile("2026-11-09", "nachmittag", gaeste)])[0]["service"] == service


@pytest.mark.parametrize("gaeste, kueche", [(10, 1), (40, 1), (41, 2), (81, 3)])
def test_kueche_nachmittag_p02(gaeste, kueche):
    assert calculate_staffing([zeile("2026-11-09", "nachmittag", gaeste)])[0]["kueche"] == kueche


def test_kueche_morgen_mindestens_zwei_p03():
    plan = calculate_staffing([zeile("2026-11-09", "morgen", 10), zeile("2026-11-09", "nachmittag", 10)])
    assert finde(plan, "2026-11-09", "morgen")["kueche"] == 2


def test_kueche_morgen_rechnet_mit_tagesgaesten_p03():
    # Morgen allein bräuchte 2 (50/40), mit dem Nachmittag sind es 130 Tagesgäste → 4
    plan = calculate_staffing([zeile("2026-11-09", "morgen", 50), zeile("2026-11-09", "nachmittag", 80)])
    assert finde(plan, "2026-11-09", "morgen")["kueche"] == 4
    assert finde(plan, "2026-11-09", "nachmittag")["kueche"] == 2


@pytest.mark.parametrize("gaeste, abwasch", [(99, 1), (100, 2), (140, 2)])
def test_abwasch_p04(gaeste, abwasch):
    assert calculate_staffing([zeile("2026-11-09", "nachmittag", gaeste)])[0]["abwasch"] == abwasch


def test_regelquellen():
    plan = calculate_staffing([zeile("2026-11-09", "morgen", 20), zeile("2026-11-09", "nachmittag", 20)])
    assert finde(plan, "2026-11-09", "morgen")["rule_refs"] == ["P-01", "P-02", "P-03", "P-04"]
    assert finde(plan, "2026-11-09", "nachmittag")["rule_refs"] == ["P-01", "P-02", "P-04"]


# --- Anlässe -----------------------------------------------------------------------
def test_anlass_erhoeht_gaeste():
    events = [{"date": "2026-11-12", "shift": "morgen", "persons": 40, "type": "Firmenlunch"}]
    plan = calculate_staffing([zeile("2026-11-12", "morgen", 45)], events)
    assert plan[0]["guests_planned"] == 85
    assert plan[0]["service"] == 3


def test_anlass_ausserhalb_der_prognose_wird_ignoriert():
    events = [{"date": "2026-11-15", "shift": "morgen", "persons": 40, "type": "Sonntag"}]
    plan = calculate_staffing([zeile("2026-11-12", "morgen", 45)], events)
    assert len(plan) == 1 and plan[0]["guests_planned"] == 45


# --- Korrekturen (Memory) -------------------------------------------------------
def test_korrektur_wird_angewendet():
    # 13.11.2026 ist ein Freitag (weekday 4)
    korrektur = [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1}]
    ohne = calculate_staffing([zeile("2026-11-13", "nachmittag", 40)])
    mit = calculate_staffing([zeile("2026-11-13", "nachmittag", 40)], corrections=korrektur)
    assert mit[0]["service"] == ohne[0]["service"] + 1


def test_korrektur_nur_passender_tag_und_schicht():
    korrektur = [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1}]
    plan = calculate_staffing([zeile("2026-11-12", "nachmittag", 40),     # Donnerstag
                               zeile("2026-11-13", "morgen", 40)], corrections=korrektur)
    assert all(r["service"] == 2 for r in plan)


def test_korrektur_nie_unter_mindestbesetzung():
    korrektur = [{"weekday": 0, "shift": "morgen", "role": "kueche", "delta": -3}]
    plan = calculate_staffing([zeile("2026-11-09", "morgen", 20)], corrections=korrektur)
    assert plan[0]["kueche"] == config.MIN_KUECHE["morgen"]


def test_deterministisch():
    forecast = json.loads((config.FIXTURES_DIR / "forecast_example.json").read_text())
    assert calculate_staffing(forecast) == calculate_staffing(forecast)
