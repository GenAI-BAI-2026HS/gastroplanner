"""MCP-Server: Wetter und Kalender als Tools. Owner: Person B (B3).

Lokal testen:   mcp dev mcp_server/server.py
Vom Agenten:    agent/mcp_client.py startet ihn per stdio (python -m mcp_server.server).
"""
from mcp.server.fastmcp import FastMCP

from tools import calendar_ch, weather

mcp = FastMCP("restaurant-kontext")


@mcp.tool()
def get_weather(start_date: str, days: int = 7) -> list[dict]:
    """Wetterprognose für den Restaurantstandort Olten: pro Tag Höchsttemperatur (°C)
    und Niederschlag (mm). start_date im Format YYYY-MM-DD."""
    return weather.get_weather(start_date, days)


@mcp.tool()
def get_calendar(start_date: str, days: int = 7) -> list[dict]:
    """Kalender pro Tag: Wochentag, geöffnet, Feiertag (Kanton SO), Brückentag,
    Schulferien. start_date im Format YYYY-MM-DD."""
    return calendar_ch.get_calendar(start_date, days)


if __name__ == "__main__":
    mcp.run()
