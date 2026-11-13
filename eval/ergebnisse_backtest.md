# Backtest Gästeprognose (A4)

Testfenster: 2026-08-10 bis 2026-10-17, 120 Schichten (letzte 60 offene Tage, nicht im Training).
Erzeugt mit `python -m eval.backtest` (Einzelwerte: `eval/backtest_results.csv`, Diagramm: `docs/backtest.png`).

| Verfahren | Schicht | MAE (Gäste) | Fehler % | RMSE | Bias | Abdeckung Spanne | Unterbesetzt | Überbesetzt |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| Regression (A3) | gesamt | 2.2 | 8% | 3.1 | -0.2 | 89% | 1% | 7% |
| Regression (A3) | morgen | 3.1 | 8% | 4.0 | +0.1 | 90% | 0% | 13% |
| Regression (A3) | nachmittag | 1.4 | 9% | 1.9 | -0.5 | 88% | 2% | 0% |
| Wochentagsmittel (Baseline) | gesamt | 3.7 | 13% | 4.9 | +0.3 | 69% | 0% | 12% |
| Wochentagsmittel (Baseline) | morgen | 4.5 | 11% | 5.8 | -0.1 | 72% | 0% | 13% |
| Wochentagsmittel (Baseline) | nachmittag | 2.9 | 19% | 3.8 | +0.6 | 67% | 0% | 12% |

**Ergebnis:** Die Regression hat einen um 40 % kleineren mittleren Fehler als das Wochentagsmittel (2.2 statt 3.7 Gäste pro Schicht, 8% statt 13% der Gäste).

Lesehilfe:
- MAE: durchschnittliche Abweichung von der tatsächlichen Gästezahl; Fehler % = MAE / mittlere Gäste.
- Bias: positiv = Prognose im Mittel zu hoch, negativ = zu tief.
- Abdeckung: Anteil der Schichten, in denen die tatsächliche Zahl in der Spanne lag (Ziel beim 80 %-Intervall: etwa 80 %).
- Unter-/Überbesetzt: Besetzung aus dem oberen Wert der Spanne verglichen mit der Besetzung, die für die tatsächlichen Gäste nötig gewesen wäre (mindestens eine Rolle zu wenig bzw. zu viel).

Grenzen: Die Regression bekommt im Backtest das gemessene Wetter. Im Betrieb kommt eine Wetterprognose, die selbst Fehler hat; der echte Fehler ist deshalb etwas grösser. Die Historie ist synthetisch (data/generate.py) und enthält genau die Effekte, die das Modell als Merkmale bekommt. Der Vorsprung gegenüber der Baseline ist deshalb optimistisch.
