"""Langzeit-Memory: Korrekturen der Betriebsleitung (Tabelle corrections). Owner: Helin (C5)."""


def save_correction(weekday: int, shift: str, role: str, delta: int, note: str) -> None:
    """Speichert eine Korrektur, z. B. Freitag Nachmittag immer einen Service mehr."""
    raise NotImplementedError("C5: save_correction ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")


def get_corrections() -> list[dict]:
    """Alle gespeicherten Korrekturen.

    Rückgabe: [{"weekday": 4, "shift": "nachmittag", "role": "service", "delta": 1, "note": "..."}]
    """
    raise NotImplementedError("C5: get_corrections ist noch nicht umgesetzt (USE_FIXTURES=1 nutzen)")
