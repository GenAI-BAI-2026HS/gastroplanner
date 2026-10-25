"""Besetzung aus Gästeprognose. Owner: Helin (C2). Vertrag: Projektplan Abschnitt 5."""


def calculate_staffing(forecast: list[dict], events: list[dict] | None = None,
                       corrections: list[dict] | None = None) -> list[dict]:
    """Deterministische Besetzung pro Tag, Schicht und Rolle (Regeln P-01 bis P-04).

    events:      [{"date": "2026-10-29", "shift": "morgen", "persons": 40, "type": "Firmenlunch"}]
    corrections: [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1}]
    Rückgabe (Beispiel: tests/fixtures/staffing_example.json):
    [{"date": "2026-10-26", "shift": "morgen", "guests_planned": 48,
      "kueche": 2, "service": 2, "abwasch": 1, "rule_refs": ["P-01", "P-02", "P-04"]}, ...]
    """
    raise NotImplementedError("C2: calculate_staffing ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
