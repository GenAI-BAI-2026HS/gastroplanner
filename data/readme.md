# data/

| Datei | Inhalt |
|---|---|
| `generate.py` | Testdaten-Generator (A2) |
| `school_holidays.csv` | Schulferien der Volksschule Olten, 2024–2027 |
| `restaurant.db` | Tabellen `history` (Generator), `approved_plans` (commit-Node), `corrections` (Memory) |
| `checkpoints.db` | LangGraph-Checkpointer, nicht committet |

## Testdaten neu erzeugen

```bash
python data/generate.py --plot     # history neu, Kontrollplot nach docs/testdaten.png
python -m forecast.train           # Modelle neu trainieren, Koeffizienten anzeigen
```

Der Seed ist fix (42), jeder Lauf ergibt dieselben Daten. Nur `history` wird ersetzt.

**Umfang:** 01.10.2024 bis 18.10.2026, Mo–Sa, je zwei Schichten. Das ergibt 641 offene Tage und 1282 Zeilen. Die letzten 60 offenen Tage nutzt das Training nicht, sie bleiben für den Backtest (A4).

## Eingebaute Effekte

Die Werte sind Vorschläge aus dem Projektplan (A2) und **Annahmen**, keine echten Zahlen. Weil die Regression genau die Zusammenhänge sucht, die hier eingebaut wurden, ist der Prognosegewinn auf diesen Daten zu optimistisch (Limitation).

| Effekt | Morgen | Nachmittag |
|---|---|---|
| Basis Mo–Fr / Sa | 45 / 30 | 15 / 25 |
| Regen (rain_mm > 0) | ×0.90 | ×0.75 |
| Hitze (≥ 25 °C) | – | ×1.30 |
| Kälte (< 5 °C) | ×1.10 | – |
| Schulferien | ×0.85 | ×0.85 |
| Brückentag | ×0.75 | ×0.75 |
| Feiertag | ×0.80 | ×0.80 |
| Dezember | ×1.10 | ×1.10 |
| Zufall | ×N(1, 0.10) | ×N(1, 0.10) |

**Wetter:** Die Höchsttemperatur folgt einer Saisonkurve, von etwa 3 °C Mitte Januar bis 26 °C Mitte Juli, dazu kommt ein Zufall von ±3 °C. Regen fällt an etwa 31–45 % der Tage, im Sommer etwas häufiger, mit 1–15 mm. Das Wetter gilt für beide Schichten eines Tages.

**Kalender:**
- Feiertage aus `holidays.Switzerland(subdiv="SO")`: Neujahr, Karfreitag, Auffahrt, 1. August und Weihnachten. Das Restaurant ist an Feiertagen offen, hat aber weniger Gäste.
- Brückentag ist ein Werktag zwischen Feiertag und Wochenende, also ein Freitag nach einem Donnerstag-Feiertag oder ein Montag vor einem Dienstag-Feiertag. Im Zeitraum sind das 30.05.2025, 26.12.2025, 02.01.2026 und 15.05.2026.
- `get_calendar` (B2) muss dieselben Definitionen nutzen, sonst rechnet die Prognose mit anderen Merkmalen als das Training. Am einfachsten übernimmt B2 `is_bridge_day` und `load_school_holidays` aus `generate.py`.

## Quellen Schulferien

Die Ferien gelten vom ersten Ferientag (Montag) bis zum letzten Ferientag (Freitag). Für Olten gilt der Standardplan des Kantons.

- 2025/26, 2026/27, 2027/28: Volksschulamt Kanton Solothurn, [Ferienplan](https://so.ch/verwaltung/departement-fuer-bildung-und-kultur/volksschulamt/aktuell/ferienplan), Schulferienpläne als PDF ([2025/26](https://so.ch/fileadmin/internet/dbk/dbk-vsa/Schulsystem/Ferienplan/Schulferienplan_2025-2026.pdf), [2026/27](https://so.ch/fileadmin/internet/dbk/dbk-vsa/Schulsystem/Ferienplan/Schulferienplan_2026_2027.pdf), [2027/28](https://so.ch/fileadmin/internet/dbk/dbk-vsa/Schulsystem/Ferienplan/Schulferienplan_2027_2028.pdf)).
- 2024/25 und Sommer 2024: Das Volksschulamt hat den Plan nicht mehr online. Die Daten stammen aus dem [Ferienplan des Heilpädagogischen Schulzentrums Olten 2023–2026](https://www.hpsz.ch/wp-content/uploads/2023/04/Ferienplan-23-bis-26.pdf). Für 2025/26 stimmt dieser Plan Tag für Tag mit dem kantonalen Volksschulplan überein. Das HPSZ gibt die Ferien von Samstag bis Sonntag an; hier sind sie auf Montag bis Freitag umgerechnet. Einzige Ausnahme: Die Frühlingsferien 2025 enden am Ostermontag (21.04.2025).
