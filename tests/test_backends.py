"""Tests für die Schalter in agent/backends.py."""
from agent import backends


def test_ohne_mcp_direkter_aufruf(monkeypatch):
    monkeypatch.setenv("USE_FIXTURES", "0")
    monkeypatch.setenv("USE_MCP", "0")
    aufrufe = []
    monkeypatch.setattr("tools.weather.get_weather", lambda s, d: aufrufe.append("wetter") or [])
    monkeypatch.setattr("tools.calendar_ch.get_calendar", lambda s, d: aufrufe.append("kalender") or [])

    def kein_mcp(*_):
        raise AssertionError("MCP darf mit USE_MCP=0 nicht aufgerufen werden")
    monkeypatch.setattr("agent.mcp_client.call_mcp_tool", kein_mcp)

    backends.get_weather("2026-11-16", 7)
    backends.get_calendar("2026-11-16", 7)
    assert aufrufe == ["wetter", "kalender"]


def test_mcp_ist_standard(monkeypatch):
    monkeypatch.delenv("USE_MCP", raising=False)
    assert backends.use_mcp()
