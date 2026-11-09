"""Tests für Tool-Calling in regelfrage (C3, Review-Punkt 4). Fake-LLM, keine API."""
from langchain_core.messages import AIMessage, ToolMessage
from langgraph.types import Command  # noqa: F401  (gleiche Imports wie test_graph)

from agent.graph import build_graph
from agent.nodes.regelfrage import MAX_SUCHEN, NICHTS_GEFUNDEN, regeln_suchen
from agent.routing import route_after_regelfrage
from agent.schemas import Route
from agent.state import initial_state
from tests.conftest import tool_call
from tests.test_graph import OK, run  # noqa: F401  (run ist eine Fixture)

REGEL = Route(intent="regelfrage")


def tool_aufrufe(fake):
    return [m for n, m in fake.calls if n == "tools"]


# --- Das LLM wählt das Tool ------------------------------------------------------------
def test_llm_sucht_und_antwortet_mit_quelle(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    _, _, result = run("Wie lang darf eine Schicht höchstens sein?")

    erster, zweiter = tool_aufrufe(fake)
    assert not any(isinstance(m, ToolMessage) for m in erster)   # 1. Aufruf: noch keine Treffer
    assert isinstance(zweiter[-1], ToolMessage)                  # 2. Aufruf: mit Suchtreffern
    assert any(h["section"] == "P-05 Schichtdauer" for h in result["rule_sources"])
    assert result["messages"][-1].content == fake.text


def test_llm_waehlt_suchanfrage_selbst(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    fake.tool_script = [tool_call("Vorlaufzeit Anlass")]
    graph, cfg, _ = run("Bis wann muss ich den Firmenlunch durchgeben?")

    suche = graph.get_state(cfg).values["regel_messages"]
    tool_msg = next(m for m in suche if isinstance(m, ToolMessage))
    assert tool_msg.artifact[0]["section"] == "A-01 Vorlaufzeit"   # Stichworte des LLM zählen


def test_mehrere_themen_mehrere_suchen(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    fake.tool_script = [tool_call("Pause Schicht Dauer", "Vorlaufzeit Anlass melden")]
    _, _, result = run("Wie lange dauert eine Schicht und wann muss ich einen Anlass melden?")

    abschnitte = {h["section"] for h in result["rule_sources"]}
    assert {"P-05 Schichtdauer", "A-01 Vorlaufzeit"} <= abschnitte
    assert len(abschnitte) == len(result["rule_sources"])           # keine Doppelten


def test_llm_darf_ohne_suche_antworten(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    fake.tool_script = [AIMessage(NICHTS_GEFUNDEN)]
    _, _, result = run("Was steht im Mietvertrag?")
    assert result["messages"][-1].content == NICHTS_GEFUNDEN
    assert result["rule_sources"] == []
    assert len(tool_aufrufe(fake)) == 1


# --- Grenze der Schleife -----------------------------------------------------------------
def test_nach_max_suchen_muss_das_llm_antworten(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    fake.tool_script = [tool_call(f"Suche {i}", nr=i) for i in range(MAX_SUCHEN)]
    graph, cfg, result = run("Eine schwierige Frage")

    suche = graph.get_state(cfg).values["regel_messages"]
    assert sum(isinstance(m, ToolMessage) for m in suche) == MAX_SUCHEN
    assert fake.tool_choices[-1] == "none"                          # Tool gesperrt
    assert result["messages"][-1].content == fake.text


def test_llm_ignoriert_sperre_endet_trotzdem(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    fake.tool_script = [tool_call(f"Suche {i}", nr=i) for i in range(MAX_SUCHEN + 5)]
    _, _, result = run("Eine schwierige Frage")
    assert result["messages"][-1].content == NICHTS_GEFUNDEN
    assert len(tool_aufrufe(fake)) == MAX_SUCHEN + 1                # kein Endloslauf


# --- State sauber halten ------------------------------------------------------------------
def test_messages_enthalten_keine_tool_aufrufe(fake_llm, run):
    fake_llm(Guard=OK, Route=REGEL)
    _, _, result = run("Wie lange ist die Pause?")
    for m in result["messages"]:
        assert not isinstance(m, ToolMessage)
        assert not getattr(m, "tool_calls", None)


def test_neue_anfrage_startet_mit_leerer_suche(fake_llm, run):
    fake = fake_llm(Guard=OK, Route=REGEL)
    graph, cfg, _ = run("Wie lange ist die Pause?")
    vorher = len(tool_aufrufe(fake))
    graph.invoke(initial_state("Wann muss ich einen Anlass melden?"), cfg)   # gleicher Thread

    erster_neuer_aufruf = tool_aufrufe(fake)[vorher]
    assert not any(isinstance(m, ToolMessage) for m in erster_neuer_aufruf)
    assert "Anlass melden" in erster_neuer_aufruf[-1].content


# --- Bausteine einzeln ---------------------------------------------------------------------
def test_tool_liefert_text_fuers_llm_und_treffer_als_daten():
    msg = regeln_suchen.invoke({"name": "regeln_suchen", "args": {"suchanfrage": "Abwasch"},
                                "id": "1", "type": "tool_call"})
    assert "[personalregeln.md · P-04 Abwasch]" in msg.content
    assert msg.artifact[0] == {"text": msg.artifact[0]["text"], "source": "personalregeln.md",
                               "section": "P-04 Abwasch"}


def test_tool_beschreibung_fuer_das_llm():
    schema = regeln_suchen.tool_call_schema.model_json_schema()
    assert list(schema["properties"]) == ["suchanfrage"]
    assert "Hausregeln" in regeln_suchen.description


def test_router():
    mit_tool = {"regel_messages": [tool_call("Pause")]}
    ohne_tool = {"regel_messages": [AIMessage("Antwort")]}
    assert route_after_regelfrage(mit_tool) == "regel_tools"
    assert route_after_regelfrage(ohne_tool) == "end"


def test_schleife_im_graphen_sichtbar():
    kanten = {(e.source, e.target) for e in build_graph().get_graph().edges}
    assert ("regelfrage", "regel_tools") in kanten
    assert ("regel_tools", "regelfrage") in kanten
    assert ("regelfrage", "__end__") in kanten
