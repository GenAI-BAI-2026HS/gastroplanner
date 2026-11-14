"""Backtest der Gästeprognose (A4): Regression gegen Wochentagsmittel.

    python -m eval.backtest        # schreibt eval/ergebnisse_backtest.md,
                                   # eval/backtest_results.csv und docs/backtest.png

Testfenster: die letzten 60 offenen Tage der Historie (forecast.train.BACKTEST_DAYS).
Die Regression hat diese Tage beim Training nie gesehen.

Verfahren
- Regression (A3): Modell aus dem Training, Merkmale des jeweiligen Tages
  (Wochentag, Monat, Wetter, Feiertag, Brückentag, Schulferien).
- Baseline («Bauchgefühl»): Mittelwert desselben Wochentags und derselben Schicht der
  letzten 8 Wochen vor dem jeweiligen Tag (forecast/baseline.py, dieselbe Funktion wie der
  Fallback im Agenten). Sie darf die tatsächlichen Gäste der Vorwochen nutzen, weil die im
  Betrieb bekannt wären.

Kennzahlen pro Verfahren
- MAE: mittlere absolute Abweichung in Gästen (Hauptkennzahl), gesamt und pro Schicht.
- Fehler in %: MAE geteilt durch die mittlere tatsächliche Gästezahl.
- RMSE: bestraft grosse Fehler stärker.
- Abdeckung: Anteil der Schichten, in denen die tatsächliche Gästezahl in der Spanne liegt
  (Ziel bei einem 80 %-Intervall: etwa 80 %).
- Fehlbesetzungen: Besetzung aus dem oberen Wert der Spanne (so plant calculate_staffing)
  gegen die Besetzung, die für die tatsächlichen Gäste nötig gewesen wäre.
  Unterbesetzt = mindestens eine Rolle zu wenig, überbesetzt = mindestens eine Rolle zu viel
  (und keine zu wenig). Gemessen wird beides, weil 3 Gäste Fehler je nach Lage keine oder
  eine ganze Person Unterschied machen.

Grenze: Die Regression bekommt hier das gemessene Wetter. Im Betrieb kommt eine
Wetterprognose, die selbst Fehler hat. Der echte Fehler ist deshalb etwas grösser.
"""
from __future__ import annotations

from math import sqrt
from pathlib import Path

import pandas as pd

import config
from forecast.baseline import weekday_mean_forecast
from forecast.train import load_history, load_models, prepare, split_backtest
from planning.staffing import calculate_staffing

ALPHA = 0.2
ERGEBNIS_DATEI = Path(__file__).with_name("ergebnisse_backtest.md")
CSV_DATEI = Path(__file__).with_name("backtest_results.csv")
PLOT_DATEI = config.ROOT / "docs" / "backtest.png"
VERFAHREN = ("Regression (A3)", "Wochentagsmittel (Baseline)")


def _regression(models: dict, test: pd.DataFrame) -> list[dict]:
    rows = []
    for shift in config.SHIFTS:
        teil = test[test["shift"] == shift].sort_values("date")
        frame = models[shift].get_prediction(prepare(teil)).summary_frame(alpha=ALPHA)
        for (_, t), (_, p) in zip(teil.iterrows(), frame.iterrows()):
            guests = max(0, round(float(p["mean"])))
            rows.append({"date": t["date"], "shift": shift, "guests": guests,
                         "lower": max(0, min(round(float(p["obs_ci_lower"])), guests)),
                         "upper": max(round(float(p["obs_ci_upper"])), guests)})
    return rows


def _baseline(history: pd.DataFrame, test: pd.DataFrame) -> list[dict]:
    """Pro Tag: Wochentagsmittel der 8 Wochen vor genau diesem Tag."""
    hist = history[["date", "shift", "guests"]].to_dict("records")
    rows = []
    for tag in sorted(test["date"].unique()):
        rows += weekday_mean_forecast(hist, tag, 1, open_dates=[tag])
    return rows


def _besetzung_vergleich(prognose: list[dict], ist: dict[tuple[str, str], int]) -> list[str]:
    """Pro Schicht «unter», «ueber» oder «ok»: Plan aus oberem Wert vs. Plan für Ist-Gäste."""
    geplant = calculate_staffing(prognose)
    noetig = calculate_staffing([{"date": d, "shift": s, "guests": g, "lower": g, "upper": g}
                                 for (d, s), g in ist.items()])
    noetig_map = {(r["date"], r["shift"]): r for r in noetig}
    urteil = []
    for r in geplant:
        n = noetig_map[(r["date"], r["shift"])]
        if any(r[rolle] < n[rolle] for rolle in config.ROLES):
            urteil.append("unter")
        elif any(r[rolle] > n[rolle] for rolle in config.ROLES):
            urteil.append("ueber")
        else:
            urteil.append("ok")
    return urteil


def kennzahlen(prognose: list[dict], ist: dict[tuple[str, str], int]) -> dict:
    fehler, drin, wahr_sum = [], [], 0
    for r in prognose:
        wahr = ist[(r["date"], r["shift"])]
        wahr_sum += wahr
        fehler.append(r["guests"] - wahr)
        drin.append(r["lower"] <= wahr <= r["upper"])
    urteil = _besetzung_vergleich(prognose, ist)
    n = len(fehler)
    mae = sum(abs(f) for f in fehler) / n
    return {
        "n": n,
        "mae": mae,
        "fehler_pct": mae / (wahr_sum / n),
        "rmse": sqrt(sum(f * f for f in fehler) / n),
        "bias": sum(fehler) / n,
        "abdeckung": sum(drin) / n,
        "unterbesetzt": urteil.count("unter") / n,
        "ueberbesetzt": urteil.count("ueber") / n,
    }


def backtest(db_path: Path | str = config.DB_PATH) -> dict:
    """Kennzahlen gesamt und pro Schicht, dazu die Einzelwerte für CSV und Diagramm."""
    df = load_history(db_path)
    _, test = split_backtest(df)
    ist = {(r["date"], r["shift"]): int(r["guests"]) for _, r in test.iterrows()}
    prognosen = dict(zip(VERFAHREN, (_regression(load_models(db_path), test), _baseline(df, test))))

    erg = {"fenster": (test["date"].min(), test["date"].max()), "gesamt": {}, "schicht": {},
           "prognosen": prognosen, "ist": ist}
    for name, prog in prognosen.items():
        erg["gesamt"][name] = kennzahlen(prog, ist)
        for shift in config.SHIFTS:
            teil = [r for r in prog if r["shift"] == shift]
            erg["schicht"][(name, shift)] = kennzahlen(
                teil, {k: v for k, v in ist.items() if k[1] == shift})
    return erg


def als_tabelle(erg: dict, runden: bool = True) -> pd.DataFrame:
    zeilen = []
    for name in VERFAHREN:
        for teil, k in [("gesamt", erg["gesamt"][name])] + [
                (s, erg["schicht"][(name, s)]) for s in config.SHIFTS]:
            zeilen.append({"verfahren": name, "schicht": teil, **{
                key: round(v, 3) if runden and isinstance(v, float) else v for key, v in k.items()}})
    return pd.DataFrame(zeilen)


def als_markdown(erg: dict) -> str:
    von, bis = erg["fenster"]
    reg, base = (erg["gesamt"][v] for v in VERFAHREN)
    besser = (base["mae"] - reg["mae"]) / base["mae"] * 100
    zeilen = [
        "# Backtest Gästeprognose (A4)",
        "",
        f"Testfenster: {von} bis {bis}, {reg['n']} Schichten (letzte 60 offene Tage, nicht im Training).",
        "Erzeugt mit `python -m eval.backtest` (Einzelwerte: `eval/backtest_results.csv`, "
        "Diagramm: `docs/backtest.png`).",
        "",
        "| Verfahren | Schicht | MAE (Gäste) | Fehler % | RMSE | Bias | Abdeckung Spanne | Unterbesetzt | Überbesetzt |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, r in als_tabelle(erg, runden=False).iterrows():
        zeilen.append(f"| {r['verfahren']} | {r['schicht']} | {r['mae']:.1f} | {r['fehler_pct']:.0%} | "
                      f"{r['rmse']:.1f} | {r['bias']:+.1f} | {r['abdeckung']:.0%} | "
                      f"{r['unterbesetzt']:.0%} | {r['ueberbesetzt']:.0%} |")
    zeilen += [
        "",
        f"**Ergebnis:** Die Regression hat einen um {abs(besser):.0f} % "
        f"{'kleineren' if besser > 0 else 'grösseren'} mittleren Fehler als das Wochentagsmittel "
        f"({reg['mae']:.1f} statt {base['mae']:.1f} Gäste pro Schicht, "
        f"{reg['fehler_pct']:.0%} statt {base['fehler_pct']:.0%} der Gäste).",
        "",
        "Lesehilfe:",
        "- MAE: durchschnittliche Abweichung von der tatsächlichen Gästezahl; Fehler % = MAE / mittlere Gäste.",
        "- Bias: positiv = Prognose im Mittel zu hoch, negativ = zu tief.",
        "- Abdeckung: Anteil der Schichten, in denen die tatsächliche Zahl in der Spanne lag "
        "(Ziel beim 80 %-Intervall: etwa 80 %).",
        "- Unter-/Überbesetzt: Besetzung aus dem oberen Wert der Spanne verglichen mit der Besetzung, "
        "die für die tatsächlichen Gäste nötig gewesen wäre (mindestens eine Rolle zu wenig bzw. zu viel).",
        "",
        "Grenzen: Die Regression bekommt im Backtest das gemessene Wetter. Im Betrieb kommt eine "
        "Wetterprognose, die selbst Fehler hat; der echte Fehler ist deshalb etwas grösser. "
        "Die Historie ist synthetisch (data/generate.py) und enthält genau die Effekte, die das Modell "
        "als Merkmale bekommt. Der Vorsprung gegenüber der Baseline ist deshalb optimistisch.",
    ]
    return "\n".join(zeilen) + "\n"


def plot(erg: dict, pfad: Path = PLOT_DATEI) -> Path:
    """Prognose vs. Ist mit Spanne, eine Grafik pro Schicht (für die Folien)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, achsen = plt.subplots(len(config.SHIFTS), 1, figsize=(11, 6.5), sharex=True)
    for ax, shift in zip(achsen, config.SHIFTS):
        reg = sorted((r for r in erg["prognosen"][VERFAHREN[0]] if r["shift"] == shift),
                     key=lambda r: r["date"])
        base = {r["date"]: r["guests"] for r in erg["prognosen"][VERFAHREN[1]] if r["shift"] == shift}
        x = pd.to_datetime([r["date"] for r in reg])
        ax.fill_between(x, [r["lower"] for r in reg], [r["upper"] for r in reg],
                        color="#9ec5e8", alpha=0.6, step="mid", label="Spanne 80 % (Regression)")
        ax.plot(x, [r["guests"] for r in reg], color="#1f5f99", lw=1.6, label="Regression")
        ax.plot(x, [base[r["date"]] for r in reg], color="#d08a2e", lw=1.2, ls="--",
                label="Wochentagsmittel")
        ax.scatter(x, [erg["ist"][(r["date"], shift)] for r in reg], s=10, color="#222",
                   zorder=3, label="Ist")
        ax.set_title(f"Schicht {shift}", loc="left", fontsize=11)
        ax.set_ylabel("Gäste")
        ax.grid(axis="y", alpha=0.3)
        for spine in ("top", "right"):
            ax.spines[spine].set_visible(False)
    handles, labels = achsen[0].get_legend_handles_labels()
    fig.legend(handles, labels, ncol=4, fontsize=8, loc="upper right", frameon=False)
    von, bis = erg["fenster"]
    fig.suptitle(f"Backtest {von} bis {bis}: Prognose vs. Ist", x=0.01, ha="left", fontsize=12)
    fig.tight_layout(rect=(0, 0, 1, 0.96))
    pfad.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(pfad, dpi=150)
    plt.close(fig)
    return pfad


def main() -> None:
    erg = backtest()
    text = als_markdown(erg)
    ERGEBNIS_DATEI.write_text(text, encoding="utf-8")
    als_tabelle(erg).to_csv(CSV_DATEI, index=False)
    plot(erg)
    print(text)
    print(f"{ERGEBNIS_DATEI.name}, {CSV_DATEI.name} und docs/{PLOT_DATEI.name} geschrieben")


if __name__ == "__main__":
    main()
