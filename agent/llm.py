"""LLM-Zugang über das LiteLLM-Gateway des Moduls (SW5). Aufgabe B1.

Alle Nodes holen das Modell über get_llm(). So lässt es sich in Tests an einer
einzigen Stelle durch ein Fake ersetzen (set_llm).
"""
import os

from dotenv import load_dotenv

load_dotenv()

_llm = None


def make_llm(model: str | None = None):
    """Chat-Modell über das Gateway, mit denselben Einstellungen für Agent und Modellvergleich.

    temperature=0 für reproduzierbare Antworten. REASONING_EFFORT aus .env (z. B. none)
    schaltet bei Reasoning-Modellen das Nachdenken ab: spart Denk-Tokens und erlaubt
    temperature=0. drop_params lässt das Gateway Parameter weglassen, die ein Modell
    nicht unterstützt (z. B. temperature bei claude-haiku), statt mit 400 abzubrechen.
    """
    from langchain_openai import ChatOpenAI

    extra = {}
    if effort := os.getenv("REASONING_EFFORT", "").strip():
        extra["reasoning_effort"] = effort
    return ChatOpenAI(
        model=model or os.environ["MODEL"],
        base_url=os.environ["BASE_URL"],
        api_key=os.environ["API_KEY"],
        temperature=0,
        extra_body={"drop_params": True},
        **extra,
    )


def get_llm():
    global _llm
    if _llm is None:
        _llm = make_llm()
    return _llm


def set_llm(llm) -> None:
    """Modell ersetzen, z. B. durch ein Fake in Tests. None setzt zurück."""
    global _llm
    _llm = llm
