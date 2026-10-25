# gastroplanner

Restaurant-Personalplanungsagent · Generative KI und Agentensysteme · BSc Business Artificial Intelligence · FHNW Olten

Ein LLM-Orchestrator (LangGraph) holt Wetterprognose, Feiertage und Schulferien, lässt ein Regressionsmodell die Gästezahl der nächsten sieben Tage pro Schicht prognostizieren, leitet daraus die Besetzung für Küche, Service und Abwasch ab, begründet sie mit Quellen aus den Personalregeln und übernimmt den Plan erst nach Freigabe durch einen Menschen. Das LLM rechnet nie selbst.

Architektur und Begründungen: [docs/architektur.md](docs/architektur.md)

## Setup

```bash
git clone https://github.com/GenAI-BAI-2026HS/gastroplanner.git && cd gastroplanner
pip install -r requirements.txt
cp .env.example .env        # MODEL, BASE_URL, API_KEY, LANGSMITH_API_KEY eintragen
```

## Starten und testen

```bash
python -m agent.run              # Agent im Terminal (mit Freigabe und Rückfragen)
python -m agent.run --mermaid    # Graph-Bild nach docs/graph.mmd
pytest                           # alle Tests, ohne API-Key und ohne Netzwerk
pytest -m "not mcp"              # ohne den Test, der den MCP-Server startet
```

Solange die Funktionen von Person A und Helin noch fehlen, steht in `.env` `USE_FIXTURES=1`. Der Agent nutzt dann die Beispieldaten in `tests/fixtures/` (Woche ab 26.10.2026).

Beispielanfragen:

- «Plane die Woche ab 26.10.»
- «Donnerstag Firmenlunch, 40 Personen» (ohne Schicht → Rückfrage)
- «Wie lang darf eine Schicht höchstens sein?»

## Repository

```
gastroplanner/
├─ config.py                 # Schichten, Rollen, Schlüssel, Standort, Pfade      (A)
├─ requirements.txt, .env.example, pytest.ini                                     (A)
├─ agent/                    # LangGraph-Orchestrator                             (B)
│  ├─ graph.py               #   nur Verdrahtung
│  ├─ routing.py             #   alle Verzweigungen
│  ├─ state.py, schemas.py, prompts.py, llm.py
│  ├─ backends.py            #   Zugang zu forecast/, planning/, tools/ (USE_FIXTURES)
│  ├─ mcp_client.py          #   MCP-Server per stdio
│  ├─ run.py                 #   Kommandozeile
│  └─ nodes/                 #   ein Modul pro Owner (guard, memory, regelfrage: Helin)
├─ forecast/                 # predict.py, checks.py                              (A)
├─ planning/staffing.py      # calculate_staffing                                 (Helin)
├─ tools/
│  ├─ weather.py, calendar_ch.py                                                  (B)
│  ├─ plans.py               # approved_plans (nur vom commit-Node)               (B)
│  ├─ rag.py, memory.py                                                           (Helin)
├─ mcp_server/server.py      # FastMCP: Wetter + Kalender                         (B)
├─ docs_rag/                 # Regeldokumente für RAG                             (Helin)
├─ eval/                     # Backtest (A), Agenten-Evaluation (Helin)
├─ data/                     # restaurant.db, checkpoints.db (nicht committet)
├─ tests/                    # pytest + fixtures/*.json
├─ docs/                     # Architektur, Modellwahl, Graph-Bild
├─ daten/, Skizze/           # Material aus dem früheren Konzept (siehe unten)
└─ app.py                    # Streamlit                                          (A, folgt)
```

## Stand der Vertragsfunktionen

Die Funktionen aus Projektplan Abschnitt 5 existieren als Stubs mit Docstring und werfen `NotImplementedError`, bis die Owner sie umsetzen.

| Funktion | Datei | Owner | Stand |
|---|---|---|---|
| `get_weather`, `get_calendar` | `tools/weather.py`, `tools/calendar_ch.py` | B | Stub |
| `forecast_guests` | `forecast/predict.py` | A | Stub |
| `check_plausibility` | `forecast/checks.py` | A | Stub |
| `calculate_staffing` | `planning/staffing.py` | Helin | Stub |
| `search_rules` | `tools/rag.py` | Helin | Stub |
| `save_correction`, `get_corrections` | `tools/memory.py` | Helin | Stub |
| `save_approved_plan` | `tools/plans.py` | B | fertig |
| MCP-Server | `mcp_server/server.py` | B | fertig (ruft die Stubs auf) |
| LangGraph-Orchestrator | `agent/` | B | Gerüst fertig, läuft mit Fixtures |

## Früheres Konzept

`daten/` (Testdaten-Generator mit Mittagsgeschäft, Mo–Fr, Kanton Zürich, Einkauf) und `Skizze/` (Mehragentensystem mit Einkaufsplanung) stammen aus dem Konzept vor dem Projektplan vom 19.10.2026. Der Projektplan legt zwei Schichten (morgen, nachmittag), Mo–Sa, Olten (Kanton SO) und nur Personalplanung fest. Person A entscheidet in A2, was aus `daten/make_testdata.py` übernommen wird; `config.DB_PATH` zeigt auf `data/restaurant.db`.
