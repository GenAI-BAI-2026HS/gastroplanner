"""MCP-Client: Parsing der Rückgabe und echter Aufruf des Servers per stdio."""
import pytest

from agent.mcp_client import MCPToolError, _as_records, call_mcp_tool


def test_ein_block_pro_listenelement():
    raw = [{"type": "text", "text": '{"date": "2026-10-26", "temp_max": 14.2, "rain_mm": 3.1}'},
           {"type": "text", "text": '{"date": "2026-10-27", "temp_max": 11.0, "rain_mm": 0.0}'}]
    assert [r["date"] for r in _as_records(raw)] == ["2026-10-26", "2026-10-27"]


def test_json_liste_als_string():
    assert _as_records('[{"a": 1}, {"a": 2}]') == [{"a": 1}, {"a": 2}]


def test_fehlertext_wird_zur_exception():
    raw = [{"type": "text", "text": "Error executing tool get_weather: API nicht erreichbar"}]
    with pytest.raises(MCPToolError, match="API nicht erreichbar"):
        _as_records(raw, "get_weather")


@pytest.mark.mcp
def test_server_meldet_fehlende_umsetzung_als_fehler():
    """Startet mcp_server/server.py. Solange B2 fehlt, muss ein klarer Fehler kommen."""
    with pytest.raises(MCPToolError, match="get_weather"):
        call_mcp_tool("get_weather", {"start_date": "2026-10-26", "days": 7})
