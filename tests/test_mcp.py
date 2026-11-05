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
def test_kalender_ueber_mcp():
    """Startet mcp_server/server.py und ruft get_calendar über MCP auf (ohne Netzwerk)."""
    tage = call_mcp_tool("get_calendar", {"start_date": "2026-10-26", "days": 7})
    assert [t["date"] for t in tage] == [f"2026-{d}" for d in
                                         ("10-26", "10-27", "10-28", "10-29", "10-30", "10-31", "11-01")]
    assert tage[-1]["is_open"] is False


@pytest.mark.mcp
def test_fehler_im_tool_wird_zur_exception():
    """Ein Fehler im Server darf nicht als Daten weiterlaufen, sondern muss eskalieren."""
    with pytest.raises(MCPToolError, match="get_calendar"):
        call_mcp_tool("get_calendar", {"start_date": "kein-datum", "days": 7})
