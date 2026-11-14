# Modellwahl (B1)

Bezug: SW4, Folien 24–31 (Modellauswahl) · Vergleich: [`eval/ergebnisse_modellvergleich.md`](../eval/ergebnisse_modellvergleich.md)

## 1. Was das Modell können muss

Nach der Einteilung aus SW4 (Folie 24) ist unser Use-Case **Multi-Turn / Reasoning mit Tool-Use und Orchestrierung**, nicht reine Textgenerierung. Das Modell rechnet keine Zahlen (das machen Regression und Planungsfunktion), muss aber zuverlässig:

| Anforderung | Wo im Agenten | Warum wichtig |
|---|---|---|
| Strukturierte Ausgabe (Pydantic) | guard, supervisor, anlass, korrektur | Jeder Router hängt an einem korrekt gefüllten Schema |
| Tool-Calling | regelfrage (`bind_tools`) | Das Modell entscheidet, ob und wonach es sucht |
| Relative Daten auflösen | supervisor, anlass («Donnerstag», «ab dem 2. November») | Falsches Datum = Anlass in der falschen Schicht |
| Leitplanken befolgen | guard, alle Prompts | Safeguarding (C4), keine Urteile über Personen |
| Deutsch | alle | Nutzende schreiben Deutsch, auch Schweizer Begriffe |

## 2. Kriterien und Vorgehen

Kriterien nach SW4 (Folien 25–26):

1. **Qualität für unsere Aufgaben:** 5 gleiche Anfragen mit den echten Prompts und Schemas des Agenten (`eval/modellvergleich.py`): Wochenplanung mit Datum, Regelfrage erkennen, Anlass erfassen, Manipulation ablehnen, Tool-Aufruf.
2. **Geschwindigkeit:** mittlere Antwortzeit pro Aufruf. Ein Planungslauf hat 3–4 LLM-Aufrufe hintereinander; die Wartezeit in der App soll unter etwa 15 Sekunden bleiben.
3. **Kosten:** Tokens pro Lauf × Preis des Modells (Preis im LiteLLM-Admin bzw. in LangSmith). Das FHNW-Gateway hat ein Kostenlimit pro Key (SW4, Folie 37).
4. **Betrieb:** Verfügbarkeit über das FHNW-Gateway (LiteLLM, OpenAI-kompatibel). Durch das Gateway ist ein Modellwechsel eine Zeile in `.env` (`MODEL=`), am Code ändert sich nichts.
5. **Datenschutz:** Der Agent verarbeitet keine Personendaten (nur Anzahl Personen pro Rolle), deshalb ist ein API-Modell vertretbar. Für einen echten Betrieb mit Mitarbeitendendaten wäre ein lokal oder in der Schweiz betriebenes Modell (z. B. Apertus) zu prüfen.

## 3. Ergebnis

Lauf vom 14.11.2026. Verglichen wurden bewusst nur die günstigsten Chat-Modelle mit Tool-Calling im Gateway (Preise laut LiteLLM `/model/info`). Teurere Modelle wie `gpt-5.4-mini-new` (0.75 / 4.50 $) oder `gpt-6.1-sol` (2 / 10 $ pro Mio. Tokens) haben wir wegen des Kostenlimits pro Key nicht einbezogen.

| | Modell A | Modell B | Modell C |
|---|---|---|---|
| Name | `gpt-6-luna` | `azure_ai/claude-haiku-5-5` | `azure_ai/gpt-oss-120b` |
| Preis Input / Output (pro Mio. Tokens) | 0.10 / 0.50 $ | 0.10 / 0.50 $ | 0.15 / 0.60 $ |
| Richtig (von 5) | 4 | **5** | 1 |
| Antwortzeit Ø (s) | 1.2 | 1.2 | 1.8 |
| Tokens für 5 Anfragen | 1622 | 4810 | 2482 |
| Auffälligkeiten | Der Azure-Inhaltsfilter blockt den Manipulationsversuch mit HTTP 400, bevor unser guard entscheiden kann. In der App erschiene «Technischer Fehler» statt einer höflichen Ablehnung. | Löst alle Fälle; braucht für dieselben Anfragen rund dreimal mehr Tokens. | Füllt die Pydantic-Schemas meist falsch; nur der Tool-Aufruf klappt. Verbraucht zusätzlich Reasoning-Tokens. |

Einstellungen: `temperature=0`, `REASONING_EFFORT=none` (schaltet bei `gpt-6-luna` das Nachdenken ab, sonst ist `temperature=0` nicht erlaubt) und `drop_params` (das Gateway lässt Parameter weg, die ein Modell nicht kennt, z. B. `temperature` bei Haiku). Alles zentral in `agent/llm.py` (`make_llm`), damit Agent und Vergleich dieselben Einstellungen nutzen.

## 4. Entscheid

**Gewählt:** `azure_ai/claude-haiku-5-5` (in `.env` als `MODEL`).

Begründung: Haiku hat als einziges Modell alle fünf Fälle gelöst, insbesondere die Manipulation über unseren eigenen guard abgelehnt statt an einem Anbieterfilter zu scheitern. Bei gleichem Tokenpreis wie `gpt-6-luna` und gleicher Antwortzeit kostet es durch den höheren Tokenverbrauch zwar etwa dreimal so viel, absolut aber weniger als 0.01 $ pro Planungslauf (Agenten-Evaluation: Ø 4172 Tokens pro Fall). In der Agenten-Evaluation (C6) erreicht es 13 von 13 korrekten Ergebnissen, siehe [`eval/ergebnisse_agent.md`](../eval/ergebnisse_agent.md).

**Alternative:** Apertus (Swiss AI, offenes Modell) wäre aus Sicht Datenschutz und Transparenz attraktiv. Nicht getestet, weil das FHNW-Gateway Apertus nur als Embedding-Modell (`apertus-v1.1-swiss-embed-0.4b`) anbietet, nicht als Chat-Modell mit Tool-Calling.

## 5. Grenzen

- Fünf Anfragen pro Modell zeigen grobe Unterschiede, sind aber keine statistisch belastbare Messung. Die Agenten-Evaluation (C6) misst das gewählte Modell zusätzlich über 13 Fälle.
- Mit `temperature=0` sind die Antworten weitgehend, aber nicht vollständig reproduzierbar.
