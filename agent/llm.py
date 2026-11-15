"""LLM-Zugang über das LiteLLM-Gateway des Moduls (SW5). Aufgabe B1.

Alle Nodes holen das Modell über get_llm(). So lässt es sich in Tests an einer
einzigen Stelle durch ein Fake ersetzen (set_llm).
"""
import os

from dotenv import load_dotenv

load_dotenv()

_llm = None


def get_llm():
    global _llm
    if _llm is None:
        _llm = erstelle_llm(os.environ["MODEL"])
    return _llm


def erstelle_llm(modell: str):
    """ChatOpenAI über das Gateway mit den Einstellungen aus .env (auch für den Modellvergleich).

    Optional in .env: REASONING_EFFORT (z. B. none für Reasoning-Modelle, damit
    temperature=0 erlaubt ist und keine Denk-Tokens anfallen) und TEMPERATURE
    (leer = Parameter weglassen, für Modelle, die nur ihren Standardwert erlauben).
    """
    from langchain_openai import ChatOpenAI

    extra = {}
    if effort := os.getenv("REASONING_EFFORT", "").strip():
        extra["reasoning_effort"] = effort
    temperature = os.getenv("TEMPERATURE", "0").strip()
    if temperature:
        extra["temperature"] = float(temperature)
    return ChatOpenAI(model=modell, base_url=os.environ["BASE_URL"],
                      api_key=os.environ["API_KEY"], **extra)


def set_llm(llm) -> None:
    """Modell ersetzen, z. B. durch ein Fake in Tests. None setzt zurück."""
    global _llm
    _llm = llm
