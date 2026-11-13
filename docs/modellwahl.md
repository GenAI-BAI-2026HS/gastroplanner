# Modellwahl (B1)

Bezug: SW4, Folien 24–31 (Modellauswahl) · Vergleich: [`eval/ergebnisse_modellvergleich.md`](../eval/ergebnisse_modellvergleich.md)

> **Offen:** Vergleichslauf und Entscheid. Ausführen mit
> `python -m eval.modellvergleich MODELL_A MODELL_B [MODELL_C]` (Namen: `python -m agent.check_gateway --models`),
> danach Abschnitt 3 und 4 ausfüllen und diesen Kasten löschen.

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

| | Modell A | Modell B | Modell C |
|---|---|---|---|
| Name | | | |
| Richtig (von 5) | | | |
| Antwortzeit Ø (s) | | | |
| Tokens für 5 Anfragen | | | |
| Auffälligkeiten | | | |

## 4. Entscheid

**Gewählt:** _Modellname_ (in `.env` als `MODEL`).

Begründung (2–4 Sätze): _Welche Fälle hat es zuverlässig gelöst, wo waren die anderen schwächer, wie stehen Antwortzeit und Kosten im Verhältnis?_

**Alternative:** Apertus (Swiss AI, offenes Modell) wäre aus Sicht Datenschutz und Transparenz attraktiv. _Ergebnis, falls getestet; sonst: nicht getestet, weil …_

## 5. Grenzen

- Fünf Anfragen pro Modell zeigen grobe Unterschiede, sind aber keine statistisch belastbare Messung. Die Agenten-Evaluation (C6) misst das gewählte Modell zusätzlich über 13 Fälle.
- Mit `temperature=0` sind die Antworten weitgehend, aber nicht vollständig reproduzierbar.
