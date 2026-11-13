"""Ende-zu-Ende ohne Fixtures: echter Kalender über MCP, echte Prognose, Prüfung und Besetzung.

Nachgebaut werden das LLM (FakeLLM) und die Antwort von Open-Meteo, damit der Test
ohne API-Key und ohne Netzwerk läuft, sowie vorerst die Regelsuche (C3 fehlt noch).
"""
import importlib.util
import json
import uuid

import pytest
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command

import config
import tools.weather
from agent import backends
from agent.graph import build_graph
from agent.state import initial_state
from forecast import predict
from tools.plans import count_approved_rows

from tests.test_graph import OK, WOCHE

WEATHER = json.loads((config.FIXTURES_DIR / "weather_example.json").read_text(encoding="utf-8"))


@pytest.fixture
def echt(monkeypatch, tmp_path):
    spec = importlib.util.spec_from_file_location("generate", config.ROOT / "data" / "generate.py")
    generate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generate)
    generate.write_history(generate.generate_rows(), config.DB_PATH)   # tmp-DB aus conftest

    from forecast.train import load_models
    monkeypatch.setattr(predict, "_MODELS", load_models(config.DB_PATH, tmp_path / "models"))
    monkeypatch.setenv("USE_FIXTURES", "0")
    monkeypatch.setattr(tools.weather, "get_weather", lambda s, d: WEATHER)   # für forecast_guests
    monkeypatch.setattr(backends, "get_weather", lambda s, d: WEATHER)        # für den context-Node
    # TODO C3: entfernen, sobald search_rules umgesetzt ist (explain-Node braucht die Regeln)
    regeln = json.loads((config.FIXTURES_DIR / "rules_example.json").read_text(encoding="utf-8"))
    monkeypatch.setattr(backends, "search_rules", lambda q, k=3: regeln[:k])


@pytest.mark.mcp
def test_wochenplanung_mit_echten_funktionen(fake_llm, echt):
    fake_llm(Guard=OK, Route=WOCHE)
    graph = build_graph(checkpointer=InMemorySaver())
    cfg = {"configurable": {"thread_id": str(uuid.uuid4())}}
    result = graph.invoke(initial_state("Plane die Woche ab 26.10."), cfg)

    payload = result["__interrupt__"][0].value
    assert payload["typ"] == "freigabe"
    assert payload["fallback_grund"] is None                   # Regression war plausibel
    plan = payload["plan"]
    assert len(plan) == 12
    assert all(r["kueche"] >= config.MIN_KUECHE[r["shift"]] for r in plan)

    values = graph.get_state(cfg).values
    assert len(values["context"]["calendar"]) == 7              # Kalender kam über MCP
    assert all("lower" in f and "upper" in f for f in values["forecast"])

    result = graph.invoke(Command(resume={"decision": "freigeben"}), cfg)
    assert "freigegeben" in result["messages"][-1].content
    assert count_approved_rows() == 12
