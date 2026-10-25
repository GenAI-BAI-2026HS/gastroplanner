"""Router sind reine Funktionen: Dict rein, Node-Name raus."""
import pytest

from agent import routing as r


@pytest.mark.parametrize("allowed, ziel", [(True, "supervisor"), (False, "reject"), (None, "reject")])
def test_route_after_guard(allowed, ziel):
    assert r.route_after_guard({"allowed": allowed}) == ziel


@pytest.mark.parametrize("intent, ziel", [
    ("wochenplanung", "context"), ("anlass", "anlass"),
    ("regelfrage", "regelfrage"), ("themenfremd", "reject"), (None, "reject"),
])
def test_route_intent(intent, ziel):
    assert r.route_intent({"intent": intent}) == ziel


def test_route_after_anlass():
    assert r.route_after_anlass({"pending_event": {"datum": "2026-10-29"}}) == "anlass_rueckfrage"
    assert r.route_after_anlass({"pending_event": None}) == "context"
    assert r.route_after_anlass({"pending_event": None, "escalation": "x"}) == "escalate"


def test_route_after_step():
    assert r.route_after_step({"escalation": None}) == "ok"
    assert r.route_after_step({"escalation": "API weg"}) == "escalate"


@pytest.mark.parametrize("ok, retries, ziel", [
    (True, 0, "staffing"), (False, 1, "context"), (False, 2, "context"), (False, 3, "escalate"),
])
def test_route_after_plausibility(ok, retries, ziel):
    state = {"plausibility": {"ok": ok, "issues": []}, "retries": retries}
    assert r.route_after_plausibility(state) == ziel


@pytest.mark.parametrize("decision, revisions, ziel", [
    ("freigeben", 0, "commit"), ("anpassen", 0, "memory"),
    ("anpassen", r.MAX_REVISIONS, "escalate"), ("ablehnen", 0, "end"), (None, 0, "end"),
])
def test_route_after_approval(decision, revisions, ziel):
    assert r.route_after_approval({"decision": decision, "revisions": revisions}) == ziel


def test_route_after_memory():
    assert r.route_after_memory({"hinweis": "Welche Schicht?"}) == "approval"
    assert r.route_after_memory({"hinweis": None}) == "staffing"
