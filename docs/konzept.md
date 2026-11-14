# Konzept: Restaurant-Personalplanungsagent

Stand: 13.11.2026 · ersetzt das frühere Konzept (Personal- und Einkaufsplanung, siehe `daten/`, `Skizze/`) · Bezug: Projektplan vom 19.10.2026

## 1. Problem

In kleinen Restaurants plant die Betriebsleitung das Personal für die nächste Woche meist aus dem Bauchgefühl: «Freitags ist immer viel los.» Wetter, Feiertage, Brückentage und Schulferien verändern die Gästezahl aber deutlich, und Gruppenanlässe kommen kurzfristig dazu. Die Folgen:

- **Unterbesetzung:** lange Wartezeiten, gestresstes Team, verlorene Gäste. Teurer als eine Person zu viel.
- **Überbesetzung:** unnötige Lohnkosten.
- **Wissen im Kopf:** Personalschlüssel und Hausregeln (Pausen, Schichtdauer, Vorlaufzeit für Anlässe) stehen in Dokumenten, die beim Planen niemand nachschlägt.

## 2. Use-Case

Ein LLM-Orchestrator holt Wetterprognose, Feiertage und Schulferien, lässt ein Regressionsmodell die Gästezahl der nächsten sieben Tage pro Schicht prognostizieren, leitet daraus die Besetzung für Küche, Service und Abwasch ab, begründet sie mit Quellen aus den Personalregeln und übernimmt den Plan erst nach Freigabe durch einen Menschen.

**Grundprinzip:** Das LLM rechnet nie selbst. Zahlen kommen aus Tools (Regression, Planungsfunktion). Das LLM macht nur, was Sprache und Urteil verlangt: Anfrage verstehen, Pfad wählen, Anlässe aus Freitext erfassen, nachfragen, erklären.

**Rahmen (festgelegt):**

| Thema | Entscheid |
|---|---|
| Fokus | nur Personalplanung (Einkauf, Lager und Eventmenüs sind nicht Teil der Lösung) |
| Standort | Olten, Kanton Solothurn (Wetter, Feiertage, Schulferien) |
| Schichten | Morgen 08–14 Uhr, Nachmittag 14–20 Uhr |
| Öffnungstage | Mo–Sa, Sonntag Ruhetag |
| Rollen | Küche, Service, Abwasch; Ausgabe = Anzahl Personen, keine Namen |
| Horizont | 7 Tage |
| Planungsbasis | oberer Wert der 80 %-Prognosespanne |

**Nutzende:** Betriebsleitung eines Restaurants (eine Person, plant wöchentlich, keine Datenkenntnisse).

**Warum ein Agent und nicht nur ein Skript?** Die Rechnung selbst ist ein Skript (Prognose → Besetzung). Der Agent kommt dort ins Spiel, wo Sprache ins Spiel kommt: Er versteht frei formulierte Aufträge («Plane die Woche ab Montag», «Donnerstag Firmenlunch, 40 Personen»), fragt bei fehlenden Angaben nach, beantwortet Regelfragen aus den Dokumenten mit Quelle, übernimmt Korrekturen aus Freitext ins Gedächtnis und erklärt den Plan. Die Zahlen bleiben dabei in deterministischen Funktionen.

## 3. User Stories

| # | Als Betriebsleitung möchte ich … | damit … | Umgesetzt in |
|---|---|---|---|
| US1 | … mit einem Satz einen Personalplan für die nächsten 7 Tage anfordern | ich nicht selbst rechnen muss | supervisor, Planungskette, A6 |
| US2 | … sehen, mit wie vielen Gästen pro Schicht gerechnet wird und wie unsicher das ist | ich den Plan einschätzen kann | A3 (Spanne), App-Tabelle |
| US3 | … sehen, welche Annahmen (Wetter, Feiertag, Ferien, Anlässe) in den Plan eingeflossen sind | ich Fehler erkenne | explain, App «Annahmen und Quellen» |
| US4 | … einen Anlass in einem Satz melden und bei fehlenden Angaben gefragt werden | Gruppen richtig eingeplant sind | B6 anlass + Rückfrage |
| US5 | … Fragen zu den Hausregeln stellen und die Quelle sehen | ich der Antwort vertrauen kann | C3 regelfrage (RAG) |
| US6 | … einen Plan freigeben, anpassen oder ablehnen | nichts ohne mein Einverständnis gilt | B5 approval/commit |
| US7 | … eine dauerhafte Korrektur angeben («Freitagnachmittag immer einen Service mehr») | ich sie nicht jede Woche wiederholen muss | C5 Memory |
| US8 | … bei fehlenden Daten (Wetterdienst nicht erreichbar) informiert werden statt einen erfundenen Plan zu bekommen | ich mich auf den Plan verlassen kann | Eskalation, Fallback |
| US9 | … dass der Assistent bei themenfremden oder manipulativen Anfragen ablehnt und nichts über einzelne Mitarbeitende urteilt | das System im Rahmen bleibt | C4 guard |

## 4. Prozess

```
Anfrage (Chat)
   │
   ▼
guard ── themenfremd / Manipulation ──► höfliche Ablehnung
   │
   ▼
supervisor: Absicht + Startdatum
   ├── regelfrage ──► Regelsuche (RAG, Tool-Calling) ──► Antwort mit Quelle
   ├── anlass ──► Anlass erfassen ── Lücke? ──► Rückfrage an Mensch ──┐
   │                 ▲─────────────────────────────────────────────────┘
   │                 │ vollständig
   └── wochenplanung ┴──► context (Wetter + Kalender über MCP)
                           ► forecast (Regression, 80 %-Spanne)
                           ► plausibility ── unplausibel ──► Ersatzprognose (Wochentagsmittel)
                           ► staffing (Personalschlüssel P-01–P-04, Anlässe, Korrekturen)
                           ► explain (LLM erklärt, Zahlen nur übernehmen, Quellen nennen)
                           ► approval (Mensch)
                                ├── freigeben ► commit (Plan speichern) ► memory (Korrekturen speichern)
                                ├── anpassen  ► korrektur (Freitext → Korrektur) ► staffing … ► approval
                                └── ablehnen  ► Ende, nichts gespeichert
Datenfehler oder zu viele Runden ──► Eskalation an die Betriebsleitung
```

Das vollständige Graph-Bild steht in [graph.png](graph.png) (Quelle: [graph.mmd](graph.mmd)), die Begründungen in [architektur.md](architektur.md).

**Wo das LLM vorkommt:** guard, supervisor, anlass, regelfrage, explain, korrektur. **Wo es nicht vorkommt:** context, forecast, plausibility, fallback, staffing, commit, memory.

## 5. Erfolgskriterien

| Kriterium | Messung | Ergebnis | Stand |
|---|---|---|---|
| Lauffähiger Agent: Personalplan aus einem Satz | «Plane die Woche ab …» liefert erklärten Plan zur Freigabe, mit echten Daten | `tests/test_ende_zu_ende.py`, App | erfüllt (Lauf mit echtem LLM: C6) |
| Prognose besser als Bauchgefühl | Backtest A4: MAE Regression < MAE Wochentagsmittel | 2.2 statt 3.7 Gäste (−40 %), [Ergebnisse](../eval/ergebnisse_backtest.md) | erfüllt |
| Unsicherheit ehrlich | Abdeckung der 80 %-Spanne im Backtest | 89 % | erfüllt |
| Regelfragen mit richtiger Quelle | Hit@3 der Regelsuche | 92 % (BM25), [Ergebnisse](../eval/ergebnisse_rag.md) | erfüllt |
| Nichts ohne Freigabe | Test: Lauf ohne Freigabe schreibt nichts in `approved_plans` | `tests/test_graph.py`, `tests/test_app.py` | erfüllt |
| Anlass mit Rückfrage | 1 vollständiger, 2 unvollständige Anlässe | Testset C6 (A1–A3) | offen bis zum LLM-Lauf |
| Safeguarding | 3 manipulative/themenfremde Anfragen werden abgelehnt | Testset C6 (S1–S3) | offen bis zum LLM-Lauf |
| Zahlen nur aus Tools | Evaluator `zahlen_aus_tools` | Testset C6 | offen bis zum LLM-Lauf |
| Nachvollziehbar | Trace in LangSmith | Evaluationslauf C6 | offen bis zum LLM-Lauf |

## 6. Abgrenzung zum früheren Konzept

Das erste Konzept sah zusätzlich einen Einkaufsplan («Personal- und Einkaufsplan», «Einkaufsbedarf» bei Anlässen) und ein Mehragentensystem vor. Der Projektplan vom 19.10.2026 beschränkt die Lösung auf die Personalplanung, damit der Kern in der verfügbaren Zeit sauber gebaut, getestet und evaluiert werden kann. Einkauf und Lager bleiben eine mögliche Ausbaustufe; die Architektur (Supervisor mit weiteren Pfaden) liesse das zu.
