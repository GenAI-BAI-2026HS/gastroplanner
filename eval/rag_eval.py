"""Trefferquote der Regelsuche (C3). Owner: Helin (C6).

    python -m eval.rag_eval      # Tabelle im Terminal + eval/ergebnisse_rag.md

Läuft ohne API (BM25). Ist EMBEDDING_MODEL gesetzt, wird die Hybrid-Suche gemessen.

Kennzahlen:
  Hit@1  Anteil Fragen, bei denen die richtige Regel an erster Stelle steht
  Hit@3  Anteil Fragen, bei denen sie unter den ersten drei ist (so viele bekommt das LLM)
  MRR    Mittlerer Kehrwert des Rangs: Platz 1 = 1, Platz 2 = 0.5, Platz 3 = 0.33, nicht
         gefunden = 0. Ein Wert für «wie weit oben im Schnitt».

Die Fragen sind bewusst so formuliert, wie eine Betriebsleiterin fragen würde, nicht mit
den Wörtern aus dem Dokument. Sie sind nicht dieselben wie in tests/test_rag.py.
"""
import os
from datetime import date
from pathlib import Path

from tools.rag import search_rules

ERGEBNIS_DATEI = Path(__file__).with_name("ergebnisse_rag.md")

FRAGEN = [
    ("Wie viele Servicekräfte brauche ich für 70 Gäste?", "P-01 Service"),
    ("Reicht eine Person im Service, wenn kaum jemand kommt?", "P-01 Service"),
    ("Wie viele Leute stehen in der Küche bei 90 Gästen am Nachmittag?", "P-02 Küche"),
    ("Warum sind morgens immer mindestens zwei Köche eingeplant?", "P-03 Küche Morgen"),
    ("Wer macht die Mise en place?", "P-03 Küche Morgen"),
    ("Wann braucht es eine zweite Person beim Geschirr im Abwasch?", "P-04 Abwasch"),
    ("Von wann bis wann geht die Nachmittagsschicht?", "P-05 Schichtdauer"),
    ("Wie viele Stunden dauert eine Schicht?", "P-05 Schichtdauer"),
    ("Wie lange Pause gibt es laut Arbeitsgesetz?", "P-06 Pausen"),
    ("Kann jemand morgens und nachmittags arbeiten?", "P-07 Keine Doppelschicht"),
    ("Wie lange bleibt jemand bei der Schichtübergabe länger?", "P-08 Übergabe"),
    ("Planen wir mit dem Mittelwert oder dem oberen Wert der Prognose?", "P-09 Planungsbasis"),
    ("Kann die Betriebsleitung dauerhaft eine Person mehr festlegen?", "P-10 Korrekturen der Betriebsleitung"),
    ("Wann gilt ein Personalplan als verbindlich?", "P-11 Freigabe"),
    ("Werden Namen von Mitarbeitenden im Plan gespeichert?", "P-11 Freigabe"),
    ("An welchen Tagen ist das Restaurant geöffnet?", "P-12 Öffnungstage"),
    ("Wie früh muss eine Gruppe von 25 Personen angemeldet werden?", "A-01 Vorlaufzeit"),
    ("Kann ich einen kleinen Anlass noch am Vortag melden?", "A-01 Vorlaufzeit"),
    ("Ist eine Reservation für 6 Personen schon ein Anlass?", "A-02 Was als Anlass gilt"),
    ("Was muss ich angeben, wenn ich einen Anlass melde?", "A-03 Pflichtangaben"),
    ("Gelten für Anlässe andere Personalschlüssel?", "A-04 Personal für Anlässe"),
    ("Wie viele Gäste passen maximal in eine Schicht?", "A-05 Maximale Grösse"),
    ("Kann ich am Sonntag einen Anlass durchführen?", "A-06 Ruhetag"),
    ("Was passiert, wenn ein Anlass die Kapazität übersteigt?", "A-05 Maximale Grösse"),
]


def auswerten(fragen=FRAGEN, k: int = 3) -> tuple[dict, list[dict]]:
    zeilen = []
    for frage, erwartet in fragen:
        treffer = [h["section"] for h in search_rules(frage, k=k)]
        rang = treffer.index(erwartet) + 1 if erwartet in treffer else None
        zeilen.append({"frage": frage, "erwartet": erwartet, "treffer": treffer, "rang": rang})
    n = len(zeilen)
    kennzahlen = {
        "fragen": n,
        "hit_at_1": sum(z["rang"] == 1 for z in zeilen) / n,
        "hit_at_3": sum(z["rang"] is not None for z in zeilen) / n,
        "mrr": sum(1 / z["rang"] for z in zeilen if z["rang"]) / n,
        "modus": "Hybrid (BM25 + Embeddings)" if os.getenv("EMBEDDING_MODEL") else "BM25",
    }
    return kennzahlen, zeilen


def als_markdown(kennzahlen: dict, zeilen: list[dict]) -> str:
    out = ["# Ergebnisse Regelsuche (RAG)", "",
           f"Stand: {date.today().isoformat()} · Modus: {kennzahlen['modus']} · Fragen: {kennzahlen['fragen']}", "",
           "| Kennzahl | Wert |", "|---|---|",
           f"| Hit@1 | {kennzahlen['hit_at_1']:.0%} |",
           f"| Hit@3 | {kennzahlen['hit_at_3']:.0%} |",
           f"| MRR | {kennzahlen['mrr']:.2f} |", "",
           "| Frage | Erwartet | Rang | Treffer |", "|---|---|---|---|"]
    for z in zeilen:
        out.append(f"| {z['frage']} | {z['erwartet']} | {z['rang'] or '–'} | {', '.join(z['treffer'])} |")
    return "\n".join(out) + "\n"


def main() -> None:
    kennzahlen, zeilen = auswerten()
    for z in zeilen:
        print(f"{z['rang'] or '-':>2}  {z['erwartet']:<38} {z['frage']}")
    print(f"\nHit@1 {kennzahlen['hit_at_1']:.0%} · Hit@3 {kennzahlen['hit_at_3']:.0%} · "
          f"MRR {kennzahlen['mrr']:.2f} ({kennzahlen['modus']})")
    ERGEBNIS_DATEI.write_text(als_markdown(kennzahlen, zeilen), encoding="utf-8")
    print(f"{ERGEBNIS_DATEI.name} geschrieben")


if __name__ == "__main__":
    main()
