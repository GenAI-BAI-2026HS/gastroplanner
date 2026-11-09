"""Gemeinsame Test-Hilfen: Fake-LLM, feste Daten, temporäre Datenbank."""
from datetime import date

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

import config
from agent import backends, llm
from agent.nodes import anlass, planung, supervisor
from tools import rag

HEUTE = date(2026, 10, 25)   # Sonntag → nächster Montag = 2026-10-26 (Woche der Fixtures)


class _Structured:
    def __init__(self, fake, schema):
        self.fake, self.schema = fake, schema

    def invoke(self, messages):
        self.fake.calls.append((self.schema.__name__, messages))
        queue = self.fake.structured[self.schema.__name__]
        return queue.pop(0) if len(queue) > 1 else queue[0]


class _ToolBound:
    """Wie ein Modell mit bind_tools: liefert entweder einen Tool-Aufruf oder Text.

    Ohne Drehbuch (fake.tool_script leer): Beim ersten Aufruf ruft es das erste Tool mit der
    Frage als Suchanfrage auf, sobald ein Tool-Ergebnis vorliegt, antwortet es mit fake.text.
    """

    def __init__(self, fake, tools, kwargs):
        self.fake, self.tools, self.kwargs = fake, tools, kwargs

    def invoke(self, messages):
        self.fake.calls.append(("tools", messages))
        self.fake.tool_choices.append(self.kwargs.get("tool_choice"))
        if self.fake.tool_script:
            return self.fake.tool_script.pop(0)
        if self.kwargs.get("tool_choice") == "none" or any(isinstance(m, ToolMessage) for m in messages):
            return AIMessage(self.fake.text)
        frage = next(m.content for m in reversed(messages) if isinstance(m, HumanMessage))
        return tool_call(frage, nr=len(self.fake.calls))


def tool_call(*suchanfragen: str, nr: int = 1) -> AIMessage:
    """AIMessage, mit der das LLM regeln_suchen aufruft (eine oder mehrere Suchen)."""
    return AIMessage("", tool_calls=[{"name": "regeln_suchen", "args": {"suchanfrage": s},
                                      "id": f"call_{nr}_{i}", "type": "tool_call"}
                                     for i, s in enumerate(suchanfragen)])


class FakeLLM:
    """Ersetzt ChatOpenAI. Antworten pro Schema als Warteschlange (letzte wird wiederholt)."""

    def __init__(self, structured: dict | None = None, text: str = "Erklärung [personalregeln.md · P-01 Service]"):
        self.structured = {k: list(v) if isinstance(v, list) else [v]
                           for k, v in (structured or {}).items()}
        self.text = text
        self.calls: list = []
        self.tool_script: list[AIMessage] = []     # feste Antworten für bind_tools (Tests C3)
        self.tool_choices: list = []

    def with_structured_output(self, schema):
        return _Structured(self, schema)

    def bind_tools(self, tools, **kwargs):
        return _ToolBound(self, tools, kwargs)

    def invoke(self, messages):
        self.calls.append(("text", messages))
        return AIMessage(self.text)

    def count(self, name: str) -> int:
        return sum(1 for n, _ in self.calls if n == name)


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    """Jeder Test: Fixture-Modus, festes Datum, eigene DB, leeres Memory, kein Warten."""
    monkeypatch.setenv("USE_FIXTURES", "1")
    monkeypatch.setattr(config, "DB_PATH", tmp_path / "restaurant.db")
    monkeypatch.setattr(supervisor, "heute", lambda: HEUTE)
    monkeypatch.setattr(anlass, "heute", lambda: HEUTE)
    monkeypatch.setattr(planung, "WARTEZEIT_S", 0)          # Wiederholungen ohne Warten
    backends._fixture_corrections.clear()
    rag.reset_index()
    yield
    llm.set_llm(None)


@pytest.fixture
def fake_llm():
    def install(**structured):
        fake = FakeLLM(structured)
        llm.set_llm(fake)
        return fake
    return install
