"""Synchroner Zugriff auf den MCP-Server (stdio). Owner: Person B (B3).

Die Tools aus langchain-mcp-adapters lassen sich nur asynchron aufrufen. Der Graph
bleibt trotzdem synchron (einfacher für Streamlit, SqliteSaver und pytest): Dieser
Wrapper kapselt den asynchronen Aufruf mit asyncio.run. Pro Aufruf startet der
Server kurz als Subprozess; bei zwei Aufrufen pro Lauf ist das vertretbar.

Geprüftes Verhalten (mcp 1.30, langchain-mcp-adapters 0.3):
- Ein Tool mit Rückgabe list[dict] liefert einen Text-Block pro Listenelement (JSON).
- Ein Fehler im Tool wirft KEINE Exception, sondern liefert einen Text-Block
  «Error executing tool …». Deshalb prüft _as_records das und wirft selbst einen Fehler,
  damit der Graph eskaliert statt mit einer Fehlermeldung weiterzurechnen.
"""
import asyncio
import json
import sys

import config


class MCPToolError(RuntimeError):
    """Der MCP-Server hat statt Daten eine Fehlermeldung geliefert."""


def _client():
    from langchain_mcp_adapters.client import MultiServerMCPClient

    return MultiServerMCPClient({
        "restaurant-kontext": {
            "command": sys.executable,
            "args": ["-m", "mcp_server.server"],
            "cwd": str(config.ROOT),
            "transport": "stdio",
        }
    })


async def _call(name: str, args: dict):
    tools = {t.name: t for t in await _client().get_tools()}
    if name not in tools:
        raise MCPToolError(f"MCP-Tool '{name}' nicht gefunden. Vorhanden: {sorted(tools)}")
    return await tools[name].ainvoke(args)


def call_mcp_tool(name: str, args: dict) -> list[dict]:
    """Ruft ein Tool des MCP-Servers auf und gibt die Datensätze als list[dict] zurück."""
    return _as_records(asyncio.run(_call(name, args)), name)


def _as_records(raw, name: str = "?") -> list[dict]:
    blocks = [raw] if isinstance(raw, str) else list(raw)
    records: list[dict] = []
    for block in blocks:
        text = block if isinstance(block, str) else (
            block.get("text") if isinstance(block, dict) else getattr(block, "text", None))
        if text is None:
            continue
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            raise MCPToolError(f"{name}: {text}") from None
        records.extend(data if isinstance(data, list) else [data])
    return records
