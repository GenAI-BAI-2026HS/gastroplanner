"""LLM-Zugang über das LiteLLM-Gateway des Moduls (SW5). Owner: Person B (B1).

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

        _llm = ChatOpenAI(
            model=os.environ["MODEL"],
            base_url=os.environ["BASE_URL"],
            api_key=os.environ["API_KEY"],
            temperature=0,
        )
    return _llm


def set_llm(llm) -> None:
    """Modell ersetzen, z. B. durch ein Fake in Tests. None setzt zurück."""
    global _llm
    _llm = llm
