"""Hybrid Retrieval über docs_rag/ (Chroma + BM25). Owner: Helin (C3)."""


def search_rules(question: str, k: int = 3) -> list[dict]:
    """Die k passendsten Regel-Abschnitte zu einer Frage.

    Rückgabe (Beispiel: tests/fixtures/rules_example.json):
    [{"text": "...", "source": "personalregeln.md", "section": "P-01 Service"}, ...]
    """
    raise NotImplementedError("C3: search_rules ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
