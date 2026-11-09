"""Tests für die Evaluation (C6). Fake-LLM, kein Netzwerk, kein LangSmith."""
from collections import Counter

from agent import backends
from agent.schemas import Anlass, Guard, Route
from eval import agent_eval as ev
from eval.rag_eval import auswerten
from eval.testset import FAELLE
from tools.rag import load_sections

OK = Guard(erlaubt=True, grund="Personalplanung")
NEIN = Guard(erlaubt=False, grund="themenfremd")


def fall(fid):
    return next(f for f in FAELLE if f["id"] == fid)


def bewerte(fid, outputs):
    return {k: v["score"] for k, v in ev.bewerten(fall(fid), outputs).items()}


# --- Testset ----------------------------------------------------------------------------
def test_testset_wie_im_projektplan():
    anzahl = Counter(f["kategorie"] for f in FAELLE)
    assert anzahl == {"wochenplanung": 3, "anlass": 3, "regelfrage": 3,
                      "safeguarding": 3, "fehlerfall": 1}
    assert len({f["id"] for f in FAELLE}) == len(FAELLE)
    assert sorted(f["erwartet"]["ergebnis"] for f in FAELLE if f["kategorie"] == "anlass") == \
        ["plan_zur_freigabe", "rueckfrage", "rueckfrage"]


def test_erwartete_quellen_gibt_es():
    abschnitte = {d.metadata["section"] for d in load_sections()}
    for f in FAELLE:
        if "quelle" in f["erwartet"]:
            assert f["erwartet"]["quelle"] in abschnitte


# --- Ein Fall durch den Agenten (Fake-LLM) --------------------------------------------------
def test_wochenplanung(fake_llm):
    fake_llm(Guard=OK, Route=Route(intent="wochenplanung"))
    out = ev.run_case(fall("W1"))
    assert out["ergebnis"] == "plan_zur_freigabe"
    assert bewerte("W1", out) == {"ergebnis_korrekt": 1, "intent_korrekt": 1, "anlass_korrekt": None,
                                  "quelle_korrekt": None, "zahlen_aus_tools": 1}


def test_anlass_vollstaendig_mit_echter_besetzung(fake_llm):
    fake_llm(Guard=OK, Route=Route(intent="anlass"),
             Anlass=Anlass(datum="2026-10-29", schicht="morgen", personen=40, art="Firmenlunch"))
    out = ev.run_case(fall("A1"))
    assert out["ergebnis"] == "plan_zur_freigabe"
    assert bewerte("A1", out)["anlass_korrekt"] == 1
    assert '"guests_planned": ' in out["tool_daten"]


def test_anlass_unvollstaendig_fuehrt_zu_rueckfrage(fake_llm):
    fake_llm(Guard=OK, Route=Route(intent="anlass"), Anlass=Anlass(art="Apéro"))
    out = ev.run_case(fall("A2"))
    assert out["ergebnis"] == "rueckfrage"
    assert bewerte("A2", out)["ergebnis_korrekt"] == 1


def test_regelfrage_mit_echter_suche(fake_llm):
    fake = fake_llm(Guard=OK, Route=Route(intent="regelfrage"))
    fake.text = "Mindestens 15 Minuten Pause [personalregeln.md · P-06 Pausen]."
    out = ev.run_case(fall("R1"))
    assert out["ergebnis"] == "antwort"
    assert any(h["section"] == "P-06 Pausen" for h in out["rule_sources"])   # echte Dokumente
    b = bewerte("R1", out)
    assert b["quelle_korrekt"] == 1 and b["zahlen_aus_tools"] == 1


def test_safeguarding(fake_llm):
    fake_llm(Guard=NEIN)
    out = ev.run_case(fall("S1"))
    assert out["ergebnis"] == "abgelehnt"
    assert bewerte("S1", out)["ergebnis_korrekt"] == 1


def test_fehlerfall_wetter_eskaliert(fake_llm):
    fake_llm(Guard=OK, Route=Route(intent="wochenplanung"))
    out = ev.run_case(fall("F1"))
    assert out["ergebnis"] == "eskaliert"


def test_testumgebung_raeumt_auf():
    vorher = (backends.calculate_staffing, backends.get_weather, backends.search_rules)
    with ev.testumgebung("wetter_ausfall"):
        assert backends.get_weather is not vorher[1]
    assert (backends.calculate_staffing, backends.get_weather, backends.search_rules) == vorher


# --- Evaluatoren einzeln ---------------------------------------------------------------------
def test_erfundene_quelle_wird_erkannt():
    out = {"text": "15 Minuten [personalregeln.md · P-06 Pausen] [personalregeln.md · P-99 Erfunden]",
           "rule_sources": [{"section": "P-06 Pausen"}]}
    r = ev.quelle_korrekt(out, {"quelle": "P-06 Pausen"})
    assert r["score"] == 0 and "P-99" in r["comment"]


def test_fehlende_quelle_wird_erkannt():
    out = {"text": "15 Minuten Pause.", "rule_sources": [{"section": "P-06 Pausen"}]}
    assert ev.quelle_korrekt(out, {"quelle": "P-06 Pausen"})["score"] == 0


def test_erfundene_zahl_wird_erkannt():
    out = {"text": "Am Montag braucht es 7 Personen im Service.", "tool_daten": '{"service": 2}'}
    r = ev.zahlen_aus_tools(out, {"ergebnis": "plan_zur_freigabe"})
    assert r["score"] == 0 and "7" in r["comment"]


def test_zahlen_aus_daten_sind_ok():
    out = {"text": "Am 29.10. morgens 85 Gäste, Service 3.",
           "tool_daten": '{"date": "2026-10-29", "guests_planned": 85, "service": 3}'}
    assert ev.zahlen_aus_tools(out, {"ergebnis": "plan_zur_freigabe"})["score"] == 1


def test_nicht_anwendbar_ist_none():
    out = {"ergebnis": "abgelehnt", "intent": None, "text": "Dabei kann ich nicht helfen.",
           "events": [], "rule_sources": [], "tool_daten": ""}
    b = ev.bewerten(fall("S1"), out)
    assert [k for k, v in b.items() if v["score"] is None] == \
        ["intent_korrekt", "anlass_korrekt", "quelle_korrekt", "zahlen_aus_tools"]


def test_bericht_zaehlt_nur_anwendbare():
    out = {"ergebnis": "abgelehnt", "intent": None, "text": "", "events": [], "rule_sources": [],
           "tool_daten": "", "dauer_s": 1.0, "tokens": 100}
    zeilen = [{"fall": fall("S1"), "outputs": out, "bewertung": ev.bewerten(fall("S1"), out)}]
    s = ev.zusammenfassung(zeilen)
    assert s["ergebnis_korrekt"] == (1, 1) and s["quelle_korrekt"] == (0, 0)
    assert "| S1 | safeguarding | abgelehnt | abgelehnt |" in ev.als_markdown(zeilen)


# --- RAG-Trefferquote --------------------------------------------------------------------------
def test_rag_trefferquote_nicht_schlechter():
    kennzahlen, _ = auswerten()
    assert kennzahlen["hit_at_3"] >= 0.9
