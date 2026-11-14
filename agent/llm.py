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
        from langchain_openai import ChatOpenAI

        # Optional in .env: REASONING_EFFORT (z. B. none für Reasoning-Modelle, damit
        # temperature=0 erlaubt ist und keine Denk-Tokens anfallen) und TEMPERATURE
        # (leer = Parameter weglassen, für Modelle, die nur ihren Standardwert erlauben).
        extra = {}
        if effort := os.getenv("REASONING_EFFORT", "").strip():
            extra["reasoning_effort"] = effort
        temperature = os.getenv("TEMPERATURE", "0").strip()
        if temperature:
            extra["temperature"] = float(temperature)
        _llm = ChatOpenAI(
            model=os.environ["MODEL"],
            base_url=os.environ["BASE_URL"],
            api_key=os.environ["API_KEY"],
            **extra,
        )
    return _llm


def set_llm(llm) -> None:
    """Modell ersetzen, z. B. durch ein Fake in Tests. None setzt zurück."""
    global _llm
    _llm = llm
