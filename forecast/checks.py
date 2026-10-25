"""Plausibilitätsprüfung der Prognose. Owner: Person A (A5). Vertrag: Projektplan Abschnitt 5."""


def check_plausibility(forecast: list[dict], start_date: str, days: int = 7) -> dict:
    """Prüft Vollständigkeit (alle offenen Tage × Schichten), Spannen und Kapazität.

    Rückgabe: {"ok": False, "issues": ["2026-10-28 nachmittag fehlt"]}
    """
    raise NotImplementedError("A5: check_plausibility ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
