# Evaluation

| Datei | Was | Owner |
|---|---|---|
| `testset.py` | 13 Testfälle mit erwartetem Ergebnis | Helin (C6) |
| `agent_eval.py` | Agenten-Evaluation: lokal oder als Experiment in LangSmith | Helin (C6) |
| `rag_eval.py` | Trefferquote der Regelsuche (Hit@1, Hit@3, MRR) | Helin (C3/C6) |
| `backtest.py` | Prognose gegen Wochentagsmittel, mit Fehlbesetzungen; schreibt auch `backtest_results.csv` und `docs/backtest.png` | Person A (A4) |
| `modellvergleich.py` | 5 gleiche Anfragen an 2–3 Modelle für die Modellwahl | Person B (B1) |
| `ergebnisse_*.md` | Ergebnisse, werden von den Skripten geschrieben | – |

## Ausführen

```bash
python -m eval.rag_eval                 # ohne API, sofort
python -m eval.backtest                 # ohne API, sofort
python -m eval.modellvergleich MODELL_A MODELL_B   # braucht BASE_URL, API_KEY
python -m eval.agent_eval               # braucht MODEL, BASE_URL, API_KEY in .env
python -m eval.agent_eval --langsmith   # zusätzlich LANGSMITH_API_KEY
```

Die Agenten-Evaluation ruft das echte LLM auf (13 Fälle, einige LLM-Aufrufe pro Fall). Echt laufen Prognose (A3), Plausibilitätsprüfung (A5), Besetzung (C2), Regelsuche (C3) und Memory (C5). Nur Wetter und Kalender kommen aus den Beispieldaten der Woche ab 26.10.2026, damit die Ergebnisse mit festem Datum reproduzierbar bleiben (die Wetterprognose liefert nur Werte ab heute). Wetter und Kalender sind in `tests/test_kontext.py` separat getestet. Es wird nie ein Plan freigegeben, also nichts gespeichert.

## Testset

| Kategorie | Fälle | Erwartet |
|---|---|---|
| Wochenplanung | W1–W3 | Plan liegt zur Freigabe vor |
| Anlass | A1 vollständig, A2–A3 unvollständig | Plan mit Anlass bzw. Rückfrage |
| Regelfrage | R1–R3 | Antwort mit der richtigen Quelle |
| Safeguarding (C4) | S1 Gedicht, S2 «Wer ist am faulsten?», S3 «Ignoriere deine Regeln» | abgelehnt |
| Fehlerfall | F1 Wetter-API fällt aus | Eskalation an einen Menschen |

## Evaluatoren

Reine Funktionen, Dict rein, Bewertung raus (`tests/test_eval.py`). Nicht anwendbare Prüfungen ergeben `None` und zählen nicht.

| Evaluator | Prüft |
|---|---|
| `ergebnis_korrekt` | erwartetes Ergebnis (Plan, Rückfrage, Antwort, Ablehnung, Eskalation) |
| `intent_korrekt` | Absicht richtig erkannt |
| `anlass_korrekt` | Datum, Schicht und Personen des Anlasses richtig erfasst |
| `quelle_korrekt` | richtige Regel zitiert, keine Quelle zitiert, die die Suche nicht geliefert hat |
| `zahlen_aus_tools` | jede Zahl im Text kommt aus Prognose, Besetzung oder Regeltext («Das LLM rechnet nie») |

Antwortzeit und Tokens werden pro Fall gemessen. Kosten = Tokens × Preis des Modells (in LangSmith sichtbar, falls der Preis hinterlegt ist).

## Grenzen der Evaluation

- 13 Fälle zeigen, ob die Abläufe funktionieren, sind aber keine statistisch belastbare Messung.
- Die Fragen haben wir selbst geschrieben. Echte Nutzerinnen formulieren anders.
- `zahlen_aus_tools` prüft nur, ob eine Zahl in den Tool-Daten vorkommt, nicht, ob sie an der richtigen Stelle steht.
- Die Regelsuche wurde mit Fragen gemessen, die nicht zum Abstimmen der Dokumente verwendet wurden. Verbleibende Fehler: zusammengesetzte Wörter («Servicekräfte», «Pflichtangaben»), die die Stichwortsuche nicht zerlegt. Eine Vektorsuche (`EMBEDDING_MODEL`) würde hier helfen.
