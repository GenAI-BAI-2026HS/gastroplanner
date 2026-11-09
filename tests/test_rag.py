"""Tests für die Regelsuche (C3): echte Dokumente in docs_rag/, ohne API."""
import re

import pytest
from langchain_core.embeddings import DeterministicFakeEmbedding

import config
from tools import rag


# --- Dokumente ------------------------------------------------------------------------
def test_dokumente_werden_in_regeln_aufgeteilt():
    abschnitte = rag.load_sections()
    titel = [d.metadata["section"] for d in abschnitte]
    assert {d.metadata["source"] for d in abschnitte} == {"personalregeln.md", "anlaesse.md"}
    assert len(titel) == len(set(titel))                               # jede Regel einmal
    assert all(re.match(r"[PA]-\d\d ", t) for t in titel)              # mit Regel-ID
    assert all(d.page_content.strip() for d in abschnitte)             # kein leerer Abschnitt


def test_regeln_aus_dem_code_stehen_im_dokument():
    """calculate_staffing verweist auf P-01 bis P-04, die Erklärung zitiert sie."""
    titel = {d.metadata["section"].split()[0] for d in rag.load_sections()}
    assert {"P-01", "P-02", "P-03", "P-04"} <= titel


def test_zahlen_im_dokument_wie_im_code():
    """Dokument und config.py dürfen sich nicht widersprechen."""
    text = {d.metadata["section"].split()[0]: d.page_content for d in rag.load_sections()}
    assert f"1 Person pro {config.GUESTS_PER_SERVICE} geplante Gäste" in text["P-01"]
    assert f"1 Person pro {config.GUESTS_PER_COOK} geplante Gäste" in text["P-02"]
    assert f"am Morgen {config.MIN_KUECHE['morgen']} Personen" in text["P-02"]
    assert f"Ab {config.ABWASCH_THRESHOLD} geplanten Gästen" in text["P-04"]
    assert f"höchstens {config.CAPACITY_PER_SHIFT} Gäste" in text["A-05"]


# --- Suche ----------------------------------------------------------------------------
@pytest.mark.parametrize("frage, erwartet", [
    ("Wie lange dauert eine Schicht?", "P-05 Schichtdauer"),
    ("Wie viele Kellner braucht es?", "P-01 Service"),
    ("Wie viele Köche braucht es am Morgen?", "P-03 Küche Morgen"),
    ("Was ist P-03?", "P-03 Küche Morgen"),
    ("Wie viele Leute im Abwasch?", "P-04 Abwasch"),
    ("Wie lange Pause habe ich?", "P-06 Pausen"),
    ("Darf jemand zwei Schichten am Tag arbeiten?", "P-07 Keine Doppelschicht"),
    ("Wie läuft die Übergabe um 14 Uhr?", "P-08 Übergabe"),
    ("Warum plant ihr mit dem oberen Wert?", "P-09 Planungsbasis"),
    ("Wer muss den Plan freigeben?", "P-11 Freigabe"),
    ("Wann muss ich einen Firmenlunch melden?", "A-01 Vorlaufzeit"),
    ("Ab wie vielen Personen ist es ein Anlass?", "A-02 Was als Anlass gilt"),
    ("Welche Angaben braucht ein Anlass?", "A-03 Pflichtangaben"),
    ("Wie viele Gäste haben pro Schicht Platz?", "A-05 Maximale Grösse"),
])
def test_richtige_regel_zuerst(frage, erwartet):
    assert rag.search_rules(frage)[0]["section"] == erwartet


def test_format_der_treffer():
    treffer = rag.search_rules("Service", k=2)
    assert len(treffer) == 2
    for t in treffer:
        assert set(t) == {"text", "source", "section"}
        assert not t["text"].startswith("##")


def test_k_begrenzt_die_treffer():
    assert len(rag.search_rules("Schicht Personen Gäste", k=5)) == 5


def test_ohne_passende_woerter_keine_treffer():
    assert rag.search_rules("Mietvertrag Parkplatz") == []
    assert rag.search_rules("   ") == []


def test_tokenize():
    assert rag.tokenize("Wie viele Schichten?") == ["schicht"]
    assert "p-03" in rag.tokenize("Was sagt P-03?")


# --- Index ----------------------------------------------------------------------------
def test_index_wird_nach_aenderung_neu_gebaut(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_RAG_DIR", tmp_path)
    datei = tmp_path / "test.md"
    datei.write_text("# Test\n\n## X-01 Eins\n\nAlpha Regel.\n", encoding="utf-8")
    assert rag.search_rules("Alpha")[0]["section"] == "X-01 Eins"

    datei.write_text("# Test\n\n## X-02 Zwei\n\nBeta Regel.\n", encoding="utf-8")
    assert rag.search_rules("Beta")[0]["section"] == "X-02 Zwei"


def test_ohne_dokumente_keine_treffer(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DOCS_RAG_DIR", tmp_path)
    assert rag.search_rules("Pause") == []


# --- Hybrid: BM25 + Vektorsuche --------------------------------------------------------
def test_ohne_embedding_modell_nur_bm25(monkeypatch):
    monkeypatch.delenv("EMBEDDING_MODEL", raising=False)
    _, _, vektoren = rag._get_index()
    assert vektoren is None


def test_hybrid_mit_embeddings(monkeypatch):
    """Mit Fake-Embeddings (kein Netzwerk): Vektorsuche läuft mit, BM25-Treffer bleiben vorne."""
    monkeypatch.setattr(rag, "_embeddings", lambda: DeterministicFakeEmbedding(size=64))
    _, _, vektoren = rag._get_index()
    assert vektoren is not None
    treffer = rag.search_rules("Wie lange Pause habe ich?", k=3)
    assert len(treffer) == 3
    assert "P-06 Pausen" in [t["section"] for t in treffer]


def test_vektorspeicher_ohne_doppelte_nach_neuaufbau():
    e = DeterministicFakeEmbedding(size=16)
    rag._build_vectorstore(["a", "b"], e)
    assert rag._build_vectorstore(["a", "b", "c"], e)._collection.count() == 3
