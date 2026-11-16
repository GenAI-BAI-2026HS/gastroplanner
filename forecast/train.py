"""Training der Gästeprognose. Aufgabe A3.

    python -m forecast.train        # trainiert beide Modelle, zeigt die Koeffizienten

Pro Schicht ein lineares Modell (statsmodels OLS, Formel unten). Die letzten
BACKTEST_DAYS offenen Tage bleiben aus dem Training draussen; sie sind das Testfenster
für den Backtest (A4).

Die Modelle liegen in forecast/models/*.pkl und sind nicht committet (.gitignore).
load_models() trainiert deshalb automatisch, wenn eine Datei fehlt. So laufen die
Prognose und das Deployment auch auf einem frisch geklonten Repo.
"""
import sqlite3
from pathlib import Path

from contextlib import closing

import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

import config

MODELS_DIR = config.ROOT / "forecast" / "models"
BACKTEST_DAYS = 60
HOT_TEMP = 25                    # wie im Generator: ab 25 °C mehr Gäste am Nachmittag
FORMULA = ("guests ~ C(weekday) + C(month) + temp_max + rain + hot"
           " + is_holiday + is_bridge_day + is_school_holiday")
FLAG_COLUMNS = ("is_holiday", "is_bridge_day", "is_school_holiday")


def prepare(df: pd.DataFrame) -> pd.DataFrame:
    """Merkmale wie im Training: Regen und Hitze als 0/1, Kalender-Flags als int.

    predict.py muss dieselbe Funktion für die Zukunftsdaten nutzen. Booleans (True/False)
    würde die Formel sonst als Kategorie behandeln, und die Prognose bräche ab.
    """
    df = df.copy()
    df["rain"] = (df["rain_mm"] > 0).astype(int)
    df["hot"] = (df["temp_max"] >= HOT_TEMP).astype(int)  # Schwelle, nicht linear
    for c in FLAG_COLUMNS:
        df[c] = df[c].astype(int)
    df["weekday"] = df["weekday"].astype(int)
    df["month"] = df["month"].astype(int)
    return df


def load_history(db_path: Path | str = config.DB_PATH) -> pd.DataFrame:
    if not Path(db_path).exists():
        raise FileNotFoundError(f"{db_path} fehlt. Zuerst python data/generate.py ausführen.")
    with closing(sqlite3.connect(db_path)) as con:
        return pd.read_sql("SELECT * FROM history ORDER BY date, shift", con)


def split_backtest(df: pd.DataFrame, days: int = BACKTEST_DAYS) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(Training, Backtest-Fenster): die letzten `days` offenen Tage gehen ins Testfenster."""
    grenze = sorted(df["date"].unique())[-days]
    return df[df["date"] < grenze], df[df["date"] >= grenze]


def train(db_path: Path | str = config.DB_PATH, models_dir: Path | str = MODELS_DIR) -> dict:
    """Trainiert ein Modell pro Schicht, speichert es und gibt {schicht: Ergebnis} zurück."""
    train_df, _ = split_backtest(prepare(load_history(db_path)))
    models_dir = Path(models_dir)
    models_dir.mkdir(parents=True, exist_ok=True)
    models = {}
    for shift in config.SHIFTS:
        model = smf.ols(FORMULA, data=train_df[train_df["shift"] == shift]).fit()
        model.save(models_dir / f"{shift}.pkl")
        models[shift] = model
    return models


def load_models(db_path: Path | str = config.DB_PATH, models_dir: Path | str = MODELS_DIR) -> dict:
    """Gespeicherte Modelle laden; fehlt eine Datei, wird zuerst trainiert.

    Auch neu trainiert wird, wenn ein gespeichertes Modell mit einer anderen Formel
    erstellt wurde (z. B. nach einer Änderung an FORMULA). Sonst würde die Prognose
    still mit einem veralteten Modell rechnen.
    """
    models_dir = Path(models_dir)
    if not all((models_dir / f"{s}.pkl").exists() for s in config.SHIFTS):
        return train(db_path, models_dir)
    models = {s: sm.load(models_dir / f"{s}.pkl") for s in config.SHIFTS}
    if any(getattr(m.model, "formula", None) != FORMULA for m in models.values()):
        return train(db_path, models_dir)
    return models


if __name__ == "__main__":
    for shift, model in train().items():
        print(f"\n=== {shift} (R² {model.rsquared:.2f}) ===")
        print(model.params.round(2).to_string())
