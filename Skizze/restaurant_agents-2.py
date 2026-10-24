"""
Restaurant-Planung als Mehragentensystem mit LangGraph (Skizze)

Ablauf:
  START -> forecaster -> validate -> planner -> approval -> execute -> END
                ^____________|  (bei unplausibler Prognose, max. 2 Wiederholungen)

Installation:
  pip install -U langgraph langchain langchain-anthropic pandas pydantic

Tracing mit LangSmith (reine Umgebungsvariablen, kein Code nötig):
  LANGSMITH_TRACING=true  LANGSMITH_API_KEY=...  LANGSMITH_PROJECT=restaurant-agents

Datenbank: restaurant.db (erzeugt mit make_testdata.py)
  menus, sales, recipes, inventory, calendar, weather
  Mittagsgeschäft/Takeaway, Mo-Fr geöffnet, an Feiertagen geschlossen.

Hinweis: API-Namen (z. B. create_agent) beziehen sich auf langchain/langgraph 1.x.
Bitte gegen die installierte Version prüfen.
"""
import sqlite3
from typing import Literal, TypedDict

import pandas as pd
from pydantic import BaseModel
from langchain.agents import create_agent
from langchain.chat_models import init_chat_model
from langchain_core.tools import tool
from langgraph.checkpoint.memory import MemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

DB = "restaurant.db"
MODEL = "anthropic:claude-sonnet-5-5"  # Platzhalter: gewünschtes Modell eintragen


# ---------------------------------------------------------------------------
# 1) Strukturierte Ausgaben: das ist der "Vertrag" zwischen den Agenten
# ---------------------------------------------------------------------------
class ForecastItem(BaseModel):
    date: str                      # YYYY-MM-DD
    daypart: Literal["mittag", "abend"]
    menu_id: str
    expected_portions: int
    low: int
    high: int


class Forecast(BaseModel):
    items: list[ForecastItem]
    assumptions: str               # z. B. "Basis: letzte 8 Wochen, keine Events berücksichtigt"


class Shift(BaseModel):
    date: str
    daypart: Literal["mittag", "abend"]
    role: Literal["Küche", "Service", "Abwasch"]
    headcount: int


class PurchaseLine(BaseModel):
    ingredient: str
    quantity: float
    unit: str
    supplier: str
    order_by: str                  # spätestes Bestelldatum (Lieferzeit berücksichtigt)


class Plan(BaseModel):
    shifts: list[Shift]
    purchases: list[PurchaseLine]
    notes: str


# ---------------------------------------------------------------------------
# 2) Gemeinsamer Zustand des Graphen
# ---------------------------------------------------------------------------
class PlanningState(TypedDict, total=False):
    start_date: str
    horizon_days: int
    forecast: Forecast
    forecast_issues: list[str]
    plan: Plan
    approved: bool
    retries: int


# ---------------------------------------------------------------------------
# 3) Tools: Rechnen und Datenzugriff sind deterministisch, nicht im LLM
# ---------------------------------------------------------------------------
def _con():
    return sqlite3.connect(f"file:{DB}?mode=ro", uri=True)  # nur lesend


def _load_sales(weeks_back: int) -> pd.DataFrame:
    q = """
    SELECT date(sold_at) AS d,
           CASE WHEN CAST(strftime('%H', sold_at) AS INT) < 16
                THEN 'mittag' ELSE 'abend' END AS dp,
           menu_id, SUM(qty) AS qty
    FROM sales
    WHERE sold_at >= date((SELECT MAX(sold_at) FROM sales), ?)
    GROUP BY d, dp, menu_id
    """
    return pd.read_sql(q, _con(), params=(f"-{weeks_back * 7} days",))


MAIN_MENUS = ("vegi_menu", "fleisch_menu")   # 1 Hauptmenü = 1 Kunde


def _open_days(start_date: str, horizon_days: int) -> list[str]:
    """Geöffnete Tage im Prognosezeitraum (Wochenenden/Feiertage fallen weg)."""
    q = """SELECT date FROM calendar
           WHERE date >= ? AND date < date(?, ?) AND is_open = 1 ORDER BY date"""
    return pd.read_sql(q, _con(), params=(start_date, start_date, f"+{horizon_days} days"))["date"].tolist()


@tool
def calendar_and_weather(start_date: str, horizon_days: int) -> list[dict]:
    """Kalender (Wochentag, geöffnet, Feiertag, Schulferien, Brückentag) und
    Wetter bzw. Wetterprognose (Mittags-, Minimal- und Maximaltemperatur, Niederschlag) je Tag."""
    q = """SELECT c.date, c.weekday_name, c.is_open, c.holiday, c.school_holiday,
                  c.bridge_day, w.temp_c, w.temp_min_c, w.temp_max_c, w.precip_mm, w.is_forecast
           FROM calendar c LEFT JOIN weather w ON w.date = c.date
           WHERE c.date >= ? AND c.date < date(?, ?) ORDER BY c.date"""
    df = pd.read_sql(q, _con(), params=(start_date, start_date, f"+{horizon_days} days"))
    return df.where(df.notna(), None).to_dict("records")


@tool
def sales_summary(weeks_back: int = 8) -> dict:
    """Überblick über die Verkaufsdaten: Zeitraum, Anzahl Menüs, Lücken."""
    df = _load_sales(weeks_back)
    return {
        "first_day": df["d"].min(),
        "last_day": df["d"].max(),
        "days_with_sales": int(df["d"].nunique()),
        "menus": sorted(df["menu_id"].unique().tolist()),
    }


@tool
def statistical_forecast(start_date: str, horizon_days: int, weeks_back: int = 8) -> list[dict]:
    """Basisprognose je geöffnetem Datum, Tagesabschnitt und Menü: Mittelwert und
    Streuung pro Wochentag über die letzten Wochen. Berücksichtigt weder Wetter noch
    Ferien, das ist Aufgabe der Anpassung (siehe calendar_and_weather)."""
    df = _load_sales(weeks_back)
    df["weekday"] = pd.to_datetime(df["d"]).dt.weekday
    stats = (df.groupby(["weekday", "dp", "menu_id"])["qty"]
               .agg(["mean", "std"]).fillna(0).reset_index())
    out = []
    for d in _open_days(start_date, horizon_days):          # nur geöffnete Tage
        day = pd.Timestamp(d)
        for r in stats[stats["weekday"] == day.weekday()].itertuples():
            out.append({
                "date": day.strftime("%Y-%m-%d"),
                "daypart": r.dp,
                "menu_id": r.menu_id,
                "expected_portions": round(r.mean),
                "low": max(0, round(r.mean - r.std)),
                "high": round(r.mean + r.std),
            })
    return out


@tool
def ingredient_demand(items: list[dict]) -> list[dict]:
    """Rechnet Menüportionen (Felder: date, menu_id, expected_portions)
    über die Rezepte in Zutatenbedarf pro Datum um."""
    portions = pd.DataFrame(items)[["date", "menu_id", "expected_portions"]]
    recipes = pd.read_sql("SELECT menu_id, ingredient, qty_per_portion, unit FROM recipes", _con())
    m = portions.merge(recipes, on="menu_id")
    m["needed"] = m["expected_portions"] * m["qty_per_portion"]
    return (m.groupby(["date", "ingredient", "unit"])["needed"].sum()
             .reset_index().to_dict("records"))


@tool
def inventory_and_lead_times(ingredients: list[str]) -> list[dict]:
    """Lagerbestand, Lieferant, Lieferzeit und Haltbarkeit (Tage) je Zutat."""
    marks = ",".join("?" * len(ingredients))
    q = f"""SELECT ingredient, on_hand, unit, supplier, lead_time_days, shelf_life_days
            FROM inventory WHERE ingredient IN ({marks})"""
    return pd.read_sql(q, _con(), params=ingredients).to_dict("records")


@tool
def staffing_requirements(items: list[dict]) -> list[dict]:
    """Mindestbesetzung je Datum und Tagesabschnitt aus den erwarteten Portionen.
    Regeln hier fest verdrahtet; später aus Konfiguration oder DB laden."""
    PORTIONS_PER_COOK = 30
    PORTIONS_PER_SERVER = 40
    df = pd.DataFrame(items)
    df = df[df["menu_id"].isin(MAIN_MENUS)]          # Beilagen/Getränke zählen nicht
    df = df.groupby(["date", "daypart"])["expected_portions"].sum().reset_index()
    rows = []
    for r in df.itertuples():
        rows.append({
            "date": r.date, "daypart": r.daypart,
            "Küche": -(-r.expected_portions // PORTIONS_PER_COOK),      # aufrunden
            "Service": -(-r.expected_portions // PORTIONS_PER_SERVER),
            "Abwasch": 1,
        })
    return rows


# ---------------------------------------------------------------------------
# 4) Die beiden Agenten (je ein eigener ReAct-Agent mit eigenen Tools)
# ---------------------------------------------------------------------------
llm = init_chat_model(MODEL, temperature=0)

forecast_agent = create_agent(
    llm,
    tools=[sales_summary, statistical_forecast, calendar_and_weather],
    system_prompt=(
        "Du bist Prognose-Analyst eines Restaurants. Prüfe zuerst mit sales_summary die "
        "Datenlage, nutze dann statistical_forecast als Basis. Hole mit calendar_and_weather "
        "Ferien, Feiertage und Wetter(-prognose) und passe die Basis nur mit klarer "
        "Begründung an (z. B. Ferien, starker Regen, Hitze; Suppe/Salat folgen der "
        "Temperatur). Halte jede Anpassung in 'assumptions' fest. Erfinde keine Zahlen. "
        "Prognostiziere alle fünf Menü-IDs (inkl. Beilagen und Getränk)."
    ),
    response_format=Forecast,
)

planning_agent = create_agent(
    llm,
    tools=[ingredient_demand, inventory_and_lead_times, staffing_requirements],
    system_prompt=(
        "Du bist Betriebsplaner eines Restaurants. Erstelle aus der Prognose einen Personal- "
        "und Einkaufsplan. Zutatenbedarf und Mindestbesetzung kommen aus den Tools, rechne "
        "nicht selbst. Einkauf = Bedarf minus Lagerbestand, bestellt bis spätestens "
        "(Bedarfsdatum minus Lieferzeit). Plane für unsichere Menüs eher Richtung 'high'."
    ),
    response_format=Plan,
)


# ---------------------------------------------------------------------------
# 5) Knoten des Graphen
# ---------------------------------------------------------------------------
def forecaster(state: PlanningState) -> dict:
    hint = ""
    if state.get("forecast_issues"):
        hint = " Korrigiere diese Probleme: " + "; ".join(state["forecast_issues"])
    msg = (f"Erstelle die Prognose ab {state['start_date']} "
           f"für {state['horizon_days']} Tage.{hint}")
    res = forecast_agent.invoke({"messages": [("user", msg)]})
    return {"forecast": res["structured_response"]}


def validate(state: PlanningState) -> Command[Literal["planner", "forecaster", "__end__"]]:
    """Deterministische Plausibilitätsprüfung, kein LLM."""
    fc, issues = state["forecast"], []
    days = {i.date for i in fc.items}
    open_days = set(_open_days(state["start_date"], state["horizon_days"]))
    if days != open_days:
        issues.append(f"Prognose deckt {sorted(days)} ab, erwartet {sorted(open_days)}")
    for i in fc.items:
        if not (0 <= i.low <= i.expected_portions <= i.high):
            issues.append(f"Unplausibler Bereich: {i.date} {i.daypart} {i.menu_id}")
    if not issues:
        return Command(goto="planner", update={"forecast_issues": []})
    if state.get("retries", 0) < 2:
        return Command(goto="forecaster",
                       update={"forecast_issues": issues, "retries": state.get("retries", 0) + 1})
    return Command(goto=END, update={"forecast_issues": issues})


def planner(state: PlanningState) -> dict:
    msg = "Erstelle den Plan auf Basis dieser Prognose:\n" + state["forecast"].model_dump_json()
    res = planning_agent.invoke({"messages": [("user", msg)]})
    return {"plan": res["structured_response"]}


def approval(state: PlanningState) -> Command[Literal["execute", "__end__"]]:
    """Human-in-the-loop: Graph pausiert, bis jemand freigibt."""
    ok = interrupt({"frage": "Plan freigeben?", "plan": state["plan"].model_dump()})
    return Command(goto="execute" if ok else END, update={"approved": bool(ok)})


def execute(state: PlanningState) -> dict:
    """Stub: hier später Bestellungen an Lieferanten senden, Schichtplan ins Tool schreiben."""
    print("Plan umgesetzt:", len(state["plan"].shifts), "Schichten,",
          len(state["plan"].purchases), "Bestellpositionen")
    return {}


# ---------------------------------------------------------------------------
# 6) Graph zusammenbauen
# ---------------------------------------------------------------------------
builder = StateGraph(PlanningState)
builder.add_node("forecaster", forecaster)
builder.add_node("validate", validate)
builder.add_node("planner", planner)
builder.add_node("approval", approval)
builder.add_node("execute", execute)

builder.add_edge(START, "forecaster")
builder.add_edge("forecaster", "validate")   # validate routet selbst per Command
builder.add_edge("planner", "approval")      # approval routet selbst per Command
builder.add_edge("execute", END)

# MemorySaver für Tests; für den Betrieb z. B. SqliteSaver/PostgresSaver
app = builder.compile(checkpointer=MemorySaver())


# ---------------------------------------------------------------------------
# 7) Erweiterung um weitere Agenten (Idee, nicht ausgeführt)
# ---------------------------------------------------------------------------
# Jeder Agent wird ein eigener Subgraph mit eigenem State und eigenen Tools.
# Der Eltern-Graph bekommt einen "supervisor"-Knoten, der per Command(goto=...)
# an "planning", "marketing", "finance" usw. verteilt. Gemeinsame Daten laufen
# über das Elternschema, interne Details bleiben im Subgraph.
#
#   planning_graph  = (dieser Graph)
#   marketing_graph = StateGraph(MarketingState)...compile()
#   finance_graph   = StateGraph(FinanceState)...compile()
#   parent.add_node("planning", planning_graph)
#   parent.add_node("marketing", marketing_graph)
#   parent.add_node("finance", finance_graph)


if __name__ == "__main__":
    cfg = {"configurable": {"thread_id": "woche-42"}}
    out = app.invoke({"start_date": "2026-10-13", "horizon_days": 7, "retries": 0}, cfg)
    print(out.get("__interrupt__"))                  # Plan zur Freigabe
    out = app.invoke(Command(resume=True), cfg)      # Freigabe -> execute
