"""Gemeinsame Konstanten (Projektplan Abschnitt 1). Owner: Person A (A1).

Personalschlüssel stehen hier und im Regeldokument docs_rag/personalregeln.md,
nicht im Prompt: Zahlen rechnet der Code, nicht das LLM.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent

# --- Betrieb -----------------------------------------------------------------
SHIFTS = ("morgen", "nachmittag")              # 08–14, 14–20
SHIFT_TIMES = {"morgen": ("08:00", "14:00"), "nachmittag": ("14:00", "20:00")}
ROLES = ("kueche", "service", "abwasch")
OPEN_WEEKDAYS = (0, 1, 2, 3, 4, 5)             # Mo–Sa offen, So Ruhetag
HORIZON_DAYS = 7
CAPACITY_PER_SHIFT = 150                       # Gäste pro Schicht (Plausibilität)

# --- Standort (Wetter, Feiertage) -------------------------------------------
LOCATION_NAME = "Olten"
LATITUDE, LONGITUDE = 47.3505, 7.9032
CANTON = "SO"
TIMEZONE = "Europe/Zurich"

# --- Personalschlüssel (Regel-IDs wie in docs_rag/personalregeln.md) ---------
GUESTS_PER_SERVICE = 30                        # P-01
GUESTS_PER_COOK = 40                           # P-02
MIN_SERVICE = 1                                # P-01
MIN_KUECHE = {"morgen": 2, "nachmittag": 1}    # P-02 / P-03
ABWASCH_THRESHOLD = 100                        # P-04: ab 100 Gästen 2 Personen
MIN_ABWASCH = 1                                # P-04

# --- Pfade -------------------------------------------------------------------
DB_PATH = ROOT / "data" / "restaurant.db"              # history, approved_plans, corrections
CHECKPOINT_DB_PATH = ROOT / "data" / "checkpoints.db"  # LangGraph-Checkpointer (nicht committen)
DOCS_RAG_DIR = ROOT / "docs_rag"
FIXTURES_DIR = ROOT / "tests" / "fixtures"
