"""Besetzung aus Gästeprognose. Aufgabe C2. Vertrag: Projektplan Abschnitt 5.

Rein deterministisch: kein LLM, keine Datenbank, kein Netzwerk. Gleicher Input ergibt
immer denselben Plan. Die Zahlen kommen aus config.py, die Regel-IDs verweisen auf
docs_rag/personalregeln.md, damit die Erklärung jede Zahl mit einer Quelle belegen kann.

Ablauf pro Tag und Schicht:

1. Geplante Gäste = oberer Wert der Prognosespanne + Gäste aus Anlässen
   (Unterbesetzung ist teurer als eine Person zu viel).
2. Personalschlüssel anwenden, immer aufrunden, nie unter die Mindestbesetzung:
     P-01 Service:       1 pro 30 Gäste, mindestens 1
     P-02 Küche:         1 pro 40 Gäste; Nachmittag mindestens 1
     P-03 Küche Morgen:  macht die Mise en place für den ganzen Tag:
                         max(2, aufrunden(Tagesgäste / 40))
     P-04 Abwasch:       1 Person, ab 100 Gästen 2
3. Korrekturen der Betriebsleitung (Memory) addieren, aber nie unter die Mindestbesetzung.
"""
from datetime import date
from math import ceil

import config


def calculate_staffing(forecast: list[dict], events: list[dict] | None = None,
                       corrections: list[dict] | None = None) -> list[dict]:
    """Deterministische Besetzung pro Tag, Schicht und Rolle (Regeln P-01 bis P-04).

    events:      [{"date": "2026-10-29", "shift": "morgen", "persons": 40, "type": "Firmenlunch"}]
    corrections: [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1}]
    Rückgabe (Beispiel: tests/fixtures/staffing_example.json):
    [{"date": "2026-10-26", "shift": "morgen", "guests_planned": 48,
      "kueche": 2, "service": 2, "abwasch": 1, "rule_refs": ["P-01", "P-02", "P-04"]}, ...]

    Anlässe an Tagen oder in Schichten, die nicht in der Prognose stehen (z. B. Ruhetag),
    werden nicht verplant. Ob ein Anlass im Horizont liegt, prüft vorher der Agent.
    """
    events = events or []
    corrections = corrections or []

    # 1. Geplante Gäste pro Tag und Schicht
    geplant = {}
    for row in forecast:
        key = (row["date"], row["shift"])
        geplant[key] = geplant.get(key, 0) + _obere_grenze(row)
    for e in events:
        key = (e["date"], e["shift"])
        if key in geplant:
            geplant[key] += int(e["persons"])

    # Tagesgäste für P-03 (Mise en place am Morgen für den ganzen Tag)
    tagesgaeste = {}
    for (datum, _), gaeste in geplant.items():
        tagesgaeste[datum] = tagesgaeste.get(datum, 0) + gaeste

    plan = []
    for (datum, schicht), gaeste in sorted(geplant.items(), key=_sortierung):
        # 2. Personalschlüssel
        besetzung = {
            "kueche": _kueche(schicht, gaeste, tagesgaeste[datum]),
            "service": max(config.MIN_SERVICE, ceil(gaeste / config.GUESTS_PER_SERVICE)),
            "abwasch": 2 if gaeste >= config.ABWASCH_THRESHOLD else config.MIN_ABWASCH,
        }
        # 3. Korrekturen der Betriebsleitung
        wochentag = date.fromisoformat(datum).weekday()
        for c in corrections:
            if c["weekday"] == wochentag and c["shift"] == schicht and c["role"] in besetzung:
                besetzung[c["role"]] = max(minimum(c["role"], schicht),
                                           besetzung[c["role"]] + int(c["delta"]))

        plan.append({
            "date": datum, "shift": schicht, "guests_planned": gaeste, **besetzung,
            "rule_refs": ["P-01", "P-02", "P-03", "P-04"] if schicht == "morgen"
                         else ["P-01", "P-02", "P-04"],
        })
    return plan


def minimum(rolle: str, schicht: str) -> int:
    """Mindestbesetzung pro Rolle und Schicht. Darunter geht auch keine Korrektur."""
    if rolle == "kueche":
        return config.MIN_KUECHE[schicht]
    if rolle == "service":
        return config.MIN_SERVICE
    return config.MIN_ABWASCH


def _kueche(schicht: str, gaeste: int, tagesgaeste: int) -> int:
    if schicht == "morgen":                                           # P-03
        return max(config.MIN_KUECHE["morgen"], ceil(tagesgaeste / config.GUESTS_PER_COOK))
    return max(config.MIN_KUECHE[schicht], ceil(gaeste / config.GUESTS_PER_COOK))  # P-02


def _obere_grenze(row: dict) -> int:
    """Oberer Wert der Spanne; fehlt er, die Punktprognose."""
    return int(row.get("upper", row["guests"]))


def _sortierung(item):
    (datum, schicht), _ = item
    reihenfolge = config.SHIFTS.index(schicht) if schicht in config.SHIFTS else len(config.SHIFTS)
    return datum, reihenfolge
