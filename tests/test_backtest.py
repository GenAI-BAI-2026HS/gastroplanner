"""Tests für den Backtest (A4)."""
import pytest

import config
from eval.backtest import als_markdown, backtest, kennzahlen


def test_kennzahlen_einfaches_beispiel():
    ist = {("2026-10-26", "morgen"): 40, ("2026-10-26", "nachmittag"): 60}
    prognose = [
        {"date": "2026-10-26", "shift": "morgen", "guests": 44, "lower": 38, "upper": 50},
        {"date": "2026-10-26", "shift": "nachmittag", "guests": 58, "lower": 50, "upper": 59},
    ]
    k = kennzahlen(prognose, ist)
    assert k["mae"] == pytest.approx(3.0)       # (4 + 2) / 2
    assert k["bias"] == pytest.approx(1.0)      # (+4 − 2) / 2
    assert k["abdeckung"] == pytest.approx(0.5)  # 60 liegt nicht in 50–59
    assert k["fehler_pct"] == pytest.approx(3.0 / 50)
    assert 0 <= k["unterbesetzt"] + k["ueberbesetzt"] <= 1


@pytest.mark.skipif(not config.DB_PATH.exists(), reason="data/restaurant.db fehlt")
def test_backtest_auf_historie():
    erg = backtest()
    reg, base = erg["gesamt"]["Regression (A3)"], erg["gesamt"]["Wochentagsmittel (Baseline)"]
    assert reg["n"] == base["n"] == 120          # 60 offene Tage × 2 Schichten
    assert reg["mae"] < base["mae"]              # Erfolgskriterium: besser als die Baseline
    assert erg["schicht"][("Regression (A3)", "morgen")]["n"] == 60
    assert "Regression (A3)" in als_markdown(erg)
