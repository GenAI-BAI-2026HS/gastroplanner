"""Verbindungstest für das LiteLLM-Gateway (B1). Vor dem Evaluationslauf (C6) ausführen.

    python -m agent.check_gateway            # Modelle auflisten, Testaufruf, strukturierte Ausgabe
    python -m agent.check_gateway --models   # nur die verfügbaren Modelle auflisten

Prüft der Reihe nach:
1. MODEL, BASE_URL und API_KEY sind in .env gesetzt.
2. Das Gateway antwortet und kennt das Modell aus MODEL.
3. Ein einfacher Aufruf über get_llm() funktioniert (derselbe Weg wie im Agenten).
4. with_structured_output funktioniert (brauchen supervisor, guard, anlass).
"""
import argparse
import os
import sys
import time

from dotenv import load_dotenv
from pydantic import BaseModel, Field

load_dotenv()

NOETIG = ["MODEL", "BASE_URL", "API_KEY"]


class _Probe(BaseModel):
    intent: str = Field(description="Eines von: planung, regelfrage, anlass, sonstiges")
    begruendung: str = Field(description="Ein kurzer Satz")


def _fehlt() -> list[str]:
    return [k for k in NOETIG if not os.getenv(k)]


def _hinweis_verbindung(fehler: Exception) -> str:
    text = str(fehler)
    if "401" in text or "Authentication" in text or "invalid" in text.lower():
        return "API_KEY wird abgelehnt. Key in LiteLLM prüfen oder neu generieren."
    if "404" in text or "not found" in text.lower():
        return "Modell unbekannt. Mit --models die verfügbaren Namen anzeigen und MODEL anpassen."
    if "budget" in text.lower() or "429" in text:
        return "Budget oder Rate-Limit des Keys erreicht (SW4, Folie 37)."
    return ("Gateway nicht erreichbar. Ausserhalb des FHNW-Netzes eventuell VPN nötig; "
            "BASE_URL prüfen.")


def modelle_auflisten() -> list[str]:
    from openai import OpenAI

    client = OpenAI(base_url=os.environ["BASE_URL"], api_key=os.environ["API_KEY"])
    return sorted(m.id for m in client.models.list().data)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--models", action="store_true", help="nur Modelle auflisten")
    args = parser.parse_args()

    if fehlt := _fehlt():
        print(f"FEHLT in .env: {', '.join(fehlt)}  (Vorlage: .env.example)")
        return 1
    print(f"Gateway: {os.environ['BASE_URL']}\nModell:  {os.environ['MODEL']}\n")

    # 1. Modelle
    try:
        modelle = modelle_auflisten()
    except Exception as e:  # noqa: BLE001 – Verbindungstest, jede Ursache melden
        print(f"[FEHLER] Modellliste: {e}\n  → {_hinweis_verbindung(e)}")
        return 1
    print(f"[OK] {len(modelle)} Modelle verfügbar")
    if args.models:
        print("\n".join(f"  - {m}" for m in modelle))
        return 0
    if os.environ["MODEL"] not in modelle:
        print(f"[WARNUNG] MODEL «{os.environ['MODEL']}» nicht in der Liste. "
              "Mit --models die Namen anzeigen.")

    from agent.llm import get_llm

    llm = get_llm()

    # 2. Einfacher Aufruf
    try:
        t0 = time.perf_counter()
        antwort = llm.invoke("Antworte nur mit dem Wort: bereit")
        print(f"[OK] Testaufruf ({time.perf_counter() - t0:.1f} s): {antwort.content.strip()[:60]}")
    except Exception as e:  # noqa: BLE001
        print(f"[FEHLER] Testaufruf: {e}\n  → {_hinweis_verbindung(e)}")
        return 1

    # 3. Strukturierte Ausgabe
    try:
        t0 = time.perf_counter()
        probe = llm.with_structured_output(_Probe).invoke(
            "Ordne die Anfrage ein: «Wie viele Servicekräfte braucht es am Samstagabend?»")
        print(f"[OK] Strukturierte Ausgabe ({time.perf_counter() - t0:.1f} s): "
              f"intent={probe.intent}")
    except Exception as e:  # noqa: BLE001
        print(f"[FEHLER] Strukturierte Ausgabe: {e}\n"
              "  → Modell unterstützt evtl. kein Tool-Calling/JSON-Schema. Anderes MODEL wählen.")
        return 1

    tracing = os.getenv("LANGSMITH_TRACING") == "true" and os.getenv("LANGSMITH_API_KEY")
    print(f"\nLangSmith-Tracing: {'aktiv, Trace im Projekt ' + os.getenv('LANGSMITH_PROJECT', 'default') if tracing else 'aus (LANGSMITH_API_KEY fehlt)'}")
    print("Gateway bereit. Weiter mit: python -m eval.agent_eval --langsmith")
    return 0


if __name__ == "__main__":
    sys.exit(main())
