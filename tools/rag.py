"""Hybrid Retrieval über docs_rag/ (BM25 + Chroma). Owner: Helin (C3).

Ablauf (SW5: Document Loader, Text Splitter, Embeddings, Vektorspeicher, Retriever):

1. Laden und Aufteilen: Jedes Markdown-Dokument in docs_rag/ wird an den Überschriften
   «## ...» in Abschnitte geteilt. Ein Abschnitt = eine Regel = ein Chunk. So bleibt jede
   Regel ganz, und die Quelle lässt sich genau angeben (z. B. «P-03 Küche Morgen»).
2. Zwei Suchen:
   - BM25 (Stichwortsuche, rank-bm25): findet exakte Begriffe wie «P-03», «Vorlaufzeit»,
     «Abwasch». Läuft lokal, ohne API, immer gleich.
   - Vektorsuche (Chroma + Embeddings): findet Abschnitte mit ähnlicher Bedeutung, auch
     wenn andere Wörter verwendet werden («Wann ist Feierabend?» → Schichtdauer).
     Nur aktiv, wenn EMBEDDING_MODEL in .env gesetzt ist. Sonst nur BM25.
3. Zusammenführen mit Reciprocal Rank Fusion (RRF): Jeder Abschnitt bekommt pro Suche
   1 / (60 + Rang) Punkte. Was in beiden Suchen weit oben steht, gewinnt. RRF braucht
   keine Gewichte und keine vergleichbaren Scores, deshalb ist es Standard für Hybrid-Suche.

Der Index wird beim ersten Aufruf gebaut und danach wiederverwendet (wenige Abschnitte,
dauert unter einer Sekunde). Nach Änderungen an docs_rag/ wird er automatisch neu gebaut.
"""
import os
import re
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.documents import Document
from langchain_text_splitters import MarkdownHeaderTextSplitter
from rank_bm25 import BM25Okapi

import config

load_dotenv()

RRF_K = 60

# Häufige Wörter ohne Inhalt. Bei nur ca. 20 Abschnitten würden sie sonst mitzählen.
STOPWORDS = set("""
aber als am an auch auf aus bei bin bis da dann das dass dem den der des die dies diese
du durch ein eine einem einen einer es für gibt hat ich ihr im in ist ja kann man mit
muss nach nicht noch nur ob oder pro sich sie sind so über um und uns von vor was wann
warum wer wie wieviel viele wird wo zu zum zur
""".split())

_index = None          # (Stand der Dokumente, Abschnitte, BM25, Vektorspeicher oder None)


def search_rules(question: str, k: int = 3) -> list[dict]:
    """Die k passendsten Regel-Abschnitte zu einer Frage.

    Rückgabe (Beispiel: tests/fixtures/rules_example.json):
    [{"text": "...", "source": "personalregeln.md", "section": "P-01 Service"}, ...]
    """
    abschnitte, bm25, vektoren = _get_index()
    if not abschnitte or not question.strip():
        return []

    rankings = [_bm25_ranking(bm25, question)]
    if vektoren is not None:
        rankings.append(_vektor_ranking(vektoren, question, len(abschnitte)))

    punkte = {}
    for ranking in rankings:
        for rang, i in enumerate(ranking):
            punkte[i] = punkte.get(i, 0.0) + 1.0 / (RRF_K + rang + 1)

    beste = sorted(punkte, key=lambda i: (-punkte[i], i))[:k]
    return [_als_treffer(abschnitte[i]) for i in beste]


# --- 1. Laden und Aufteilen ---------------------------------------------------------
def load_sections(docs_dir: Path | str | None = None) -> list[Document]:
    """Alle Abschnitte aus docs_rag/*.md, je mit Quelle und Abschnittstitel."""
    splitter = MarkdownHeaderTextSplitter([("#", "dokument"), ("##", "section")])
    abschnitte = []
    for pfad in sorted(Path(docs_dir or config.DOCS_RAG_DIR).glob("*.md")):
        for doc in splitter.split_text(pfad.read_text(encoding="utf-8")):
            if "section" not in doc.metadata:          # Einleitung vor der ersten Regel
                continue
            doc.metadata["source"] = pfad.name
            abschnitte.append(doc)
    return abschnitte


# --- 2a. Stichwortsuche (BM25) ------------------------------------------------------
def tokenize(text: str) -> list[str]:
    """Kleinschreibung, Stoppwörter weg, einfache Endungen kürzen (Schichten → schicht).

    Regel-IDs wie «P-03» bleiben ein Wort, damit man gezielt danach suchen kann.
    """
    woerter = re.findall(r"[a-z]-\d+|[a-zäöüß0-9]+", text.lower())
    return [_stamm(w) for w in woerter if w not in STOPWORDS]


def _stamm(wort: str) -> str:
    if len(wort) > 5 and not re.fullmatch(r"[a-z]-\d+", wort):
        for endung in ("ungen", "en", "er", "es", "e", "n", "s"):
            if wort.endswith(endung):
                return wort[: -len(endung)]
    return wort


def _bm25_ranking(bm25: BM25Okapi, question: str) -> list[int]:
    """Abschnitte mit mindestens einem Suchwort, sortiert nach BM25-Score."""
    woerter = tokenize(question)
    scores = bm25.get_scores(woerter)
    passend = [i for i, freq in enumerate(bm25.doc_freqs) if any(w in freq for w in woerter)]
    return sorted(passend, key=lambda i: (-scores[i], i))


# --- 2b. Vektorsuche (Chroma) -------------------------------------------------------
def _embeddings():
    """Embedding-Modell über das LiteLLM-Gateway, falls in .env eingetragen."""
    modell = os.getenv("EMBEDDING_MODEL")
    if not modell:
        return None
    from langchain_openai import OpenAIEmbeddings
    return OpenAIEmbeddings(model=modell, base_url=os.environ["BASE_URL"],
                            api_key=os.environ["API_KEY"], check_embedding_ctx_length=False)


def _vektor_ranking(vektoren, question: str, n: int) -> list[int]:
    return [doc.metadata["nr"] for doc in vektoren.similarity_search(question, k=n)]


# --- Index --------------------------------------------------------------------------
def _get_index():
    global _index
    stand = _docs_stand()
    if _index is None or _index[0] != stand:
        abschnitte = load_sections()
        if not abschnitte:
            _index = (stand, [], None, None)
        else:
            texte = [_suchtext(d) for d in abschnitte]
            bm25 = BM25Okapi([tokenize(t) for t in texte])
            _index = (stand, abschnitte, bm25, _build_vectorstore(texte))
    return _index[1:]


def _build_vectorstore(texte: list[str], embeddings=None):
    embeddings = embeddings or _embeddings()
    if embeddings is None:
        return None
    from uuid import uuid4

    from langchain_chroma import Chroma
    # Nur im Arbeitsspeicher. Neuer Name pro Aufbau: Chroma teilt den Speicher im Prozess,
    # mit gleichem Namen kämen die Abschnitte nach einer Dokumentänderung doppelt hinein.
    return Chroma.from_texts(texte, embeddings, metadatas=[{"nr": i} for i in range(len(texte))],
                             collection_name=f"regeln_{uuid4().hex[:8]}")


def reset_index() -> None:
    """Index verwerfen (Tests). Wird beim nächsten Aufruf neu gebaut."""
    global _index
    _index = None


def _docs_stand():
    return tuple((p.name, p.stat().st_mtime_ns)
                 for p in sorted(Path(config.DOCS_RAG_DIR).glob("*.md")))


def _suchtext(doc: Document) -> str:
    """Der Titel zählt doppelt: Er fasst die Regel zusammen («P-06 Pausen»)."""
    titel = doc.metadata["section"]
    return f"{titel}\n{titel}\n{doc.page_content}"


def _als_treffer(doc: Document) -> dict:
    return {"text": doc.page_content.strip(), "source": doc.metadata["source"],
            "section": doc.metadata["section"]}
