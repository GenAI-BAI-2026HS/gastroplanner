"""Startdatum: Python rechnet den Wochenstart, nicht das LLM (B4)."""
from datetime import date

from agent.nodes import supervisor


def _heute(monkeypatch, tag):
    monkeypatch.setattr(supervisor, "heute", lambda: tag)


def test_tag_mitten_in_der_woche_wird_zum_montag(monkeypatch):
    _heute(monkeypatch, date(2026, 10, 25))                       # Sonntag
    assert supervisor.wochenstart("2026-10-29") == "2026-10-26"   # Donnerstag → Montag


def test_montag_bleibt_montag(monkeypatch):
    _heute(monkeypatch, date(2026, 10, 25))
    assert supervisor.wochenstart("2026-11-02") == "2026-11-02"


def test_laufende_woche_beginnt_nicht_in_der_vergangenheit(monkeypatch):
    _heute(monkeypatch, date(2026, 10, 28))                       # Mittwoch
    assert supervisor.wochenstart("2026-10-30") == "2026-10-30"   # Montag 26.10. wäre vorbei
