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

Fünf gleiche Anfragen mit den echten Prompts und Schemas des Agenten. Details: [`eval/ergebnisse_modellvergleich.md`](../eval/ergebnisse_modellvergleich.md).

| | Modell A | Modell B | Modell C |
|---|---|---|---|
| Name | `gpt-6-luna` | `gpt-5.4-mini-new` | `azure_ai/claude-haiku-5-5` |
| Richtig (von 5) | 5 | 5 | 5 |
| Antwortzeit Ø (s) | 1.4 | 0.9 | 1.3 |
| Tokens für 5 Anfragen | 1 540 | 1 621 | 4 682 |
| Auffälligkeiten | Reasoning-Modell, braucht `REASONING_EFFORT=none` für `temperature=0`; Manipulation schon vom Azure-Inhaltsfilter blockiert | Manipulation schon vom Azure-Inhaltsfilter blockiert | Nur `temperature=1` erlaubt (mit 0: alle Anfragen abgelehnt), dadurch weniger reproduzierbar; rund dreimal so viele Tokens; guard lehnt Manipulation selbst ab |

Alle drei Modelle lösen die fünf Kernaufgaben. Die Unterschiede liegen bei Betrieb, Reproduzierbarkeit und Tokens, nicht bei der Qualität dieser fünf Fälle.

## 4. Entscheid

**Gewählt:** `gpt-6-luna` (in `.env` als `MODEL`).

Begründung: `gpt-6-luna` löst alle fünf Kernaufgaben und hat als einziges Modell auch die vollständige Agenten-Evaluation bestanden (C6: 13/13 Fälle, Ø 3.8 s, rund 1 800 Tokens pro Fall, [Ergebnisse](../eval/ergebnisse_agent.md)). Es läuft mit `temperature=0` und braucht am wenigsten Tokens. `gpt-5.4-mini-new` ist gleich zuverlässig und etwas schneller und wäre die erste Alternative, wenn Kosten oder Wartezeit wichtiger werden; es wurde aber nicht über alle 13 Fälle getestet. `claude-haiku-5-5` scheidet aus, weil es nur `temperature=1` erlaubt (Antworten schwanken stärker) und rund dreimal so viele Tokens braucht.

Dank dem Gateway ist ein Wechsel eine Zeile in `.env` (`MODEL=`, bei Bedarf `TEMPERATURE` und `REASONING_EFFORT`); der Code bleibt gleich.

**Alternative Apertus:** Aus Sicht Datenschutz und Transparenz attraktiv (offenes Schweizer Modell). Auf dem Gateway des Moduls ist Apertus aber nur als Embedding-Modell verfügbar (`andreasmartin/apertus-v1.1-swiss-embed-0.4b`), nicht als Chat-Modell. Für den Orchestrator (strukturierte Ausgabe, Tool-Calling) kam es deshalb nicht in Frage. Für einen echten Betrieb mit Personendaten wäre ein selbst oder in der Schweiz betriebenes Chat-Modell zu prüfen.

## 5. Grenzen

- Fünf Anfragen pro Modell zeigen grobe Unterschiede, sind aber keine statistisch belastbare Messung. Die Agenten-Evaluation (C6) misst das gewählte Modell zusätzlich über 13 Fälle.
- Mit `temperature=0` sind die Antworten weitgehend, aber nicht vollständig reproduzierbar. Claude Haiku lief mit `temperature=1` und ist deshalb nicht ganz direkt vergleichbar.
- Der Fall «Manipulation ablehnen» misst bei den GPT-Modellen den Inhaltsfilter des Anbieters, nicht nur das Modell.
