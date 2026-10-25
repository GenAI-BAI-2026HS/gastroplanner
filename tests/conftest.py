"""Gemeinsame Test-Hilfen: Fake-LLM, feste Daten, temporäre Datenbank."""
from datetime import date

import pytest
from langchain_core.messages import AIMessage

import config
from agent import backends, llm
from agent.nodes import anlass, supervisor

HEUTE = date(2026, 10, 25)   # Sonntag → nächster Montag = 2026-10-26 (Woche der Fixtures)


class _Structured:
    def __init__(self, fake, schema):
        self.fake, self.schema = fake, schema

    def invoke(self, messages):
        self.fake.calls.append((self.schema.__name__, messages))
        queue = self.fake.structured[self.schema.__name__]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class FakeLLM:
    """Ersetzt ChatOpenAI. Antworten pro Schema als Warteschlange (letzte wird wiederholt)."""

    def __init__(self, structured: dict | None = None, text: str = "Erklärung [personalregeln.md · P-01 Service]"):
        self.structured = {k: list(v) if isinstance(v, list) else [v]
                           for k, v in (structured or {}).items()}
        self.text = text
        self.calls: list = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    def invoke(self, messages):
        self.calls.append(("text", messages))
        return AIMessage(self.text)

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Jeder Test: Fixture-Modus, festes Datum, eigene DB, leeres Memory."""
    monkeypatch.setenv("USE_FIXTURES", "1")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restaurant.db")
    monkeypatch.setattr(supervisor, "heute", lambda: HEUTE)
    monkeypatch.setattr(anlass, "heute", lambda: HEUTE)
    backends._fixture_corrections.clear()
    yield
    llm.set_llm(None)


@pytest.fixture
def fake_llm():
    def install(**structured):
        fake = FakeLLM(structured)
        llm.set_llm(fake)
        return fake
    return install
