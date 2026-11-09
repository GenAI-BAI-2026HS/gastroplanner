"""Agenten-Evaluation mit Testset und Code-Evaluatoren. Owner: Helin (C6).

    python -m eval.agent_eval              # lokal: Tabelle im Terminal + eval/ergebnisse_agent.md
    python -m eval.agent_eval --langsmith  # Dataset + Experiment in LangSmith (evaluate)

Braucht in .env: MODEL, BASE_URL, API_KEY (LLM über das Gateway). Für --langsmith
zusätzlich LANGSMITH_API_KEY. Ohne LangSmith läuft dieselbe Auswertung lokal.

Was gemessen wird (Projektplan C6), pro Fall:
  ergebnis_korrekt   Hat der Agent das erwartete Ergebnis geliefert (Plan, Rückfrage,
                     Antwort, Ablehnung, Eskalation)?
  intent_korrekt     Hat der Supervisor die Absicht richtig erkannt?
  anlass_korrekt     Wurden Datum, Schicht und Personen des Anlasses richtig erfasst?
  quelle_korrekt     Nennt die Antwort die richtige Regel, und nur Regeln, die die Suche
                     wirklich geliefert hat (keine erfundenen Quellen)?
  zahlen_aus_tools   Stammen alle Zahlen im Text aus den Tools (Prognose, Besetzung,
                     Regeln)? Das prüft das Grundprinzip «Das LLM rechnet nie».
Dazu Antwortzeit und Tokens pro Fall (Kosten: Tokens × Preis des Modells).

Nicht anwendbare Prüfungen haben den Wert None und zählen nicht in den Durchschnitt.

Testumgebung: Das LLM ist echt. Prognose, Wetter und Kalender kommen noch aus den
Beispieldaten (USE_FIXTURES=1), weil A3/A5/B2 noch nicht fertig sind. Die fertigen
Funktionen von Helin laufen echt: Besetzung (C2), Regelsuche (C3), Memory (C5, in einer
temporären Datenbank). Sobald alles fertig ist: ECHTE_FUNKTIONEN erweitern bzw.
USE_FIXTURES=0 setzen.
"""
import argparse
import contextlib
import json
import re
import tempfile
import time
import uuid
from datetime import date
from pathlib import Path

from langchain_core.callbacks import get_usage_metadata_callback
from langgraph.checkpoint.memory import InMemorySaver

import config
from agent import backends
from agent.graph import build_graph
from agent.nodes import anlass, planung, supervisor
from agent.state import initial_state
from eval.testset import FAELLE

HEUTE = date(2026, 10, 25)          # Sonntag vor der Fixture-Woche (ab 26.10.)
DATASET = "gastroplanner-testset"
ERGEBNIS_DATEI = Path(__file__).with_name("ergebnisse_agent.md")
QUELLE_RE = re.compile(r"\[([\w-]+\.md) · ([^\]]+)\]")


# --- Testumgebung -----------------------------------------------------------------------
@contextlib.contextmanager
def testumgebung(simuliere: str | None = None):
    """Fixtures für Prognose/Wetter/Kalender, echte Funktionen von Helin, festes Datum."""
    from planning.staffing import calculate_staffing
    from tools import memory, rag

    alt = {}

    def setze(obj, name, wert):
        alt.setdefault((obj, name), getattr(obj, name))
        setattr(obj, name, wert)

    def wetter_ausfall(*_):
        raise ConnectionError("Wetter-API nicht erreichbar (simuliert)")

    with tempfile.TemporaryDirectory() as tmp, _env(USE_FIXTURES="1"):
        setze(config, "DB_PATH", Path(tmp) / "eval.db")
        setze(supervisor, "heute", lambda: HEUTE)
        setze(anlass, "heute", lambda: HEUTE)
        setze(planung, "WARTEZEIT_S", 0)
        # Echte Funktionen von Helin statt Beispieldaten
        setze(backends, "calculate_staffing", calculate_staffing)
        setze(backends, "search_rules", rag.search_rules)
        setze(backends, "get_corrections", memory.get_corrections)
        setze(backends, "save_correction", memory.save_correction)
        if simuliere == "wetter_ausfall":
            setze(backends, "get_weather", wetter_ausfall)
        try:
            yield
        finally:
            for (obj, name), wert in alt.items():
                setattr(obj, name, wert)


@contextlib.contextmanager
def _env(**werte):
    import os
    alt = {k: os.environ.get(k) for k in werte}
    os.environ.update(werte)
    try:
        yield
    finally:
        for k, v in alt.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


# --- Ein Fall --------------------------------------------------------------------------
def run_case(inputs: dict) -> dict:
    """Schickt eine Eingabe durch den Agenten und sammelt, was die Evaluatoren brauchen.

    Läuft bis zur ersten Unterbrechung (Freigabe oder Rückfrage) oder bis zum Ende.
    Es wird nie freigegeben, also nie etwas gespeichert.
    """
    with testumgebung(inputs.get("simuliere")), get_usage_metadata_callback() as usage:
        graph = build_graph(checkpointer=InMemorySaver())
        cfg = {"configurable": {"thread_id": str(uuid.uuid4())},
               "run_name": "eval", "tags": ["eval", inputs.get("id", "")]}
        start = time.perf_counter()
        result = graph.invoke(initial_state(inputs["eingabe"]), cfg)
        dauer = time.perf_counter() - start
        state = graph.get_state(cfg).values

    payload = result["__interrupt__"][0].value if "__interrupt__" in result else None
    text = (payload or {}).get("erklaerung") or (payload or {}).get("frage") \
        or (result["messages"][-1].content if result.get("messages") else "")
    return {
        "ergebnis": ergebnis_aus(state, payload),
        "intent": state.get("intent"),
        "text": text or "",
        "events": state.get("events") or [],
        "rule_sources": state.get("rule_sources") or [],
        "tool_daten": _tool_daten(state),
        "dauer_s": round(dauer, 2),
        "tokens": sum(u.get("total_tokens", 0) for u in usage.usage_metadata.values()),
    }


def ergebnis_aus(state: dict, payload: dict | None) -> str:
    if payload:
        return {"freigabe": "plan_zur_freigabe", "rueckfrage": "rueckfrage"}.get(payload.get("typ"), "sonstiges")
    if state.get("escalation"):
        return "eskaliert"
    if state.get("allowed") is False or state.get("intent") == "themenfremd":
        return "abgelehnt"
    if state.get("intent") == "regelfrage":
        return "antwort"
    return "sonstiges"


def _tool_daten(state: dict) -> str:
    """Alles, was aus Tools kam, als Text: Daraus dürfen Zahlen im Text stammen."""
    teile = {k: state.get(k) for k in ("forecast", "staffing", "events", "corrections",
                                         "context", "fallback_grund", "start_date")}
    teile["regeln"] = [h["text"] + " " + h["section"] for h in state.get("rule_sources") or []]
    return json.dumps(teile, ensure_ascii=False, default=str)


# --- Evaluatoren (rein: Dict rein, Bewertung raus) ----------------------------------------
def ergebnis_korrekt(outputs: dict, reference_outputs: dict) -> dict:
    ok = outputs["ergebnis"] == reference_outputs["ergebnis"]
    return {"key": "ergebnis_korrekt", "score": int(ok),
            "comment": f"erwartet {reference_outputs['ergebnis']}, erhalten {outputs['ergebnis']}"}


def intent_korrekt(outputs: dict, reference_outputs: dict) -> dict:
    erwartet = reference_outputs.get("intent")
    if erwartet is None:
        return {"key": "intent_korrekt", "score": None}
    return {"key": "intent_korrekt", "score": int(outputs.get("intent") == erwartet),
            "comment": f"erwartet {erwartet}, erhalten {outputs.get('intent')}"}


def anlass_korrekt(outputs: dict, reference_outputs: dict) -> dict:
    erwartet = reference_outputs.get("anlass")
    if erwartet is None:
        return {"key": "anlass_korrekt", "score": None}
    treffer = any(all(e.get(k) == v for k, v in erwartet.items()) for e in outputs.get("events", []))
    return {"key": "anlass_korrekt", "score": int(treffer), "comment": str(outputs.get("events"))}


def quelle_korrekt(outputs: dict, reference_outputs: dict) -> dict:
    erwartet = reference_outputs.get("quelle")
    if erwartet is None:
        return {"key": "quelle_korrekt", "score": None}
    zitiert = {abschnitt.strip() for _, abschnitt in QUELLE_RE.findall(outputs["text"])}
    gefunden = {h["section"] for h in outputs.get("rule_sources", [])}
    erfunden = zitiert - gefunden
    ok = erwartet in zitiert and not erfunden
    return {"key": "quelle_korrekt", "score": int(ok),
            "comment": f"zitiert {sorted(zitiert)}" + (f", erfunden {sorted(erfunden)}" if erfunden else "")}


def zahlen_aus_tools(outputs: dict, reference_outputs: dict) -> dict:
    if reference_outputs["ergebnis"] not in ("plan_zur_freigabe", "antwort") or not outputs["text"]:
        return {"key": "zahlen_aus_tools", "score": None}
    erlaubt = _zahlen(outputs["tool_daten"])
    fremd = sorted(_zahlen(outputs["text"]) - erlaubt)
    return {"key": "zahlen_aus_tools", "score": int(not fremd),
            "comment": f"Zahlen ohne Quelle: {fremd}" if fremd else "alle Zahlen aus Tools"}


def _zahlen(text: str) -> set[int]:
    """Ganze Zahlen im Text. «08:00» → 8 und 0, «2026-10-29» → 2026, 10, 29."""
    return {int(z) for z in re.findall(r"\d+", text)}


EVALUATOREN = [ergebnis_korrekt, intent_korrekt, anlass_korrekt, quelle_korrekt, zahlen_aus_tools]


# --- Lokal auswerten ------------------------------------------------------------------------
def bewerten(fall: dict, outputs: dict) -> dict:
    return {ev.__name__: ev(outputs, fall["erwartet"]) for ev in EVALUATOREN}


def lokal(faelle: list[dict] = FAELLE) -> list[dict]:
    zeilen = []
    for fall in faelle:
        try:
            outputs = run_case({**fall, "eingabe": fall["eingabe"]})
        except Exception as e:                       # Fehler zählen als nicht bestanden
            outputs = {"ergebnis": f"fehler: {type(e).__name__}", "intent": None, "text": str(e),
                       "events": [], "rule_sources": [], "tool_daten": "", "dauer_s": 0, "tokens": 0}
        zeilen.append({"fall": fall, "outputs": outputs, "bewertung": bewerten(fall, outputs)})
        print(_zeile(zeilen[-1]))
    return zeilen


def zusammenfassung(zeilen: list[dict]) -> dict:
    """Anteil bestanden pro Evaluator (nur anwendbare Fälle), Ø Zeit, Ø Tokens."""
    summe = {}
    for ev in EVALUATOREN:
        werte = [z["bewertung"][ev.__name__]["score"] for z in zeilen
                 if z["bewertung"][ev.__name__]["score"] is not None]
        summe[ev.__name__] = (sum(werte), len(werte))
    n = len(zeilen) or 1
    summe["dauer_s"] = round(sum(z["outputs"]["dauer_s"] for z in zeilen) / n, 1)
    summe["tokens"] = round(sum(z["outputs"]["tokens"] for z in zeilen) / n)
    return summe


def als_markdown(zeilen: list[dict]) -> str:
    kurz = ["ergebnis", "intent", "anlass", "quelle", "zahlen"]
    out = ["# Ergebnisse Agenten-Evaluation", "",
           f"Stand: {date.today().isoformat()} · Fälle: {len(zeilen)} · Testumgebung: "
           "echtes LLM, Prognose/Wetter/Kalender aus Beispieldaten, Besetzung/RAG/Memory echt", "",
           "| Fall | Kategorie | Erwartet | Erhalten | " + " | ".join(kurz) + " | Zeit (s) | Tokens |",
           "|---|---|---|---|" + "---|" * len(kurz) + "---|---|"]
    for z in zeilen:
        b = [_symbol(z["bewertung"][ev.__name__]["score"]) for ev in EVALUATOREN]
        out.append(f"| {z['fall']['id']} | {z['fall']['kategorie']} | {z['fall']['erwartet']['ergebnis']} "
                   f"| {z['outputs']['ergebnis']} | " + " | ".join(b)
                   + f" | {z['outputs']['dauer_s']} | {z['outputs']['tokens']} |")
    s = zusammenfassung(zeilen)
    out += ["", "## Zusammenfassung", "", "| Prüfung | Bestanden |", "|---|---|"]
    out += [f"| {ev.__name__} | {s[ev.__name__][0]} / {s[ev.__name__][1]} |" for ev in EVALUATOREN]
    out += [f"| Ø Antwortzeit | {s['dauer_s']} s |", f"| Ø Tokens pro Fall | {s['tokens']} |", "",
            "## Nicht bestanden", ""]
    fehler = [f"- **{z['fall']['id']}** {ev}: {r.get('comment', '')}"
              for z in zeilen for ev, r in z["bewertung"].items() if r["score"] == 0]
    out += fehler or ["- keine"]
    return "\n".join(out) + "\n"


def _symbol(score) -> str:
    return "–" if score is None else ("✅" if score else "❌")


def _zeile(z: dict) -> str:
    b = " ".join(_symbol(r["score"]) for r in z["bewertung"].values())
    return f"{z['fall']['id']:<3} {z['outputs']['ergebnis']:<18} {b}  {z['outputs']['dauer_s']} s"


# --- LangSmith --------------------------------------------------------------------------------
def langsmith_experiment():
    """Legt das Dataset an (falls nötig) und startet ein Experiment mit evaluate()."""
    from langsmith import Client, evaluate

    client = Client()
    if not client.has_dataset(dataset_name=DATASET):
        ds = client.create_dataset(DATASET, description="Gastroplanner: 13 Testfälle (C6)")
        client.create_examples(
            dataset_id=ds.id,
            inputs=[{"id": f["id"], "eingabe": f["eingabe"], "simuliere": f.get("simuliere")} for f in FAELLE],
            outputs=[f["erwartet"] for f in FAELLE],
            metadata=[{"kategorie": f["kategorie"]} for f in FAELLE],
        )
    return evaluate(run_case, data=DATASET, evaluators=EVALUATOREN,
                    experiment_prefix="gastroplanner", max_concurrency=1,
                    metadata={"umgebung": "fixtures + echte C2/C3/C5"})


def fehlende_einstellungen(langsmith: bool) -> list[str]:
    import os

    from dotenv import load_dotenv
    load_dotenv()
    noetig = ["MODEL", "BASE_URL", "API_KEY"] + (["LANGSMITH_API_KEY"] if langsmith else [])
    return [k for k in noetig if not os.getenv(k)]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--langsmith", action="store_true", help="Experiment in LangSmith statt lokal")
    args = p.parse_args()
    if fehlt := fehlende_einstellungen(args.langsmith):
        raise SystemExit(f"Bitte in .env eintragen: {', '.join(fehlt)} (Vorlage: .env.example)")
    if args.langsmith:
        langsmith_experiment()
        print("Experiment in LangSmith gestartet: Projekt «Datasets & Experiments» → gastroplanner-testset")
        return
    zeilen = lokal()
    ERGEBNIS_DATEI.write_text(als_markdown(zeilen), encoding="utf-8")
    print(f"\n{ERGEBNIS_DATEI.name} geschrieben")


if __name__ == "__main__":
    main()
