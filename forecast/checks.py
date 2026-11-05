"""Plausibilitätsprüfung der Prognose. Owner: Person A (A5). Vertrag: Projektplan Abschnitt 5.

Geprüft wird, bevor geplant wird. Die issues sieht der Mensch bei der Freigabe oder in
der Eskalation, deshalb sind sie als verständliche Sätze formuliert.

Was passiert im Graphen (agent/nodes/planung.py, agent/routing.py)?
- ok → Besetzung berechnen.
- nicht ok → Ersatzprognose aus dem Wochentagsmittel (forecast/baseline.py), die hier
  nochmals geprüft wird. Die Regression wird nicht wiederholt, weil sie bei gleichem Input
  dasselbe Ergebnis liefert.
- auch die Ersatzprognose nicht ok → Eskalation an den Menschen, kein Plan.

Regeln:
1. Jeder offene Tag im Horizont hat beide Schichten, keine doppelt, keine zusätzlichen.
2. 0 ≤ guests ≤ config.CAPACITY_PER_SHIFT.
3. lower ≤ guests ≤ upper.
4. Wetterwerte vorhanden. Ausnahme: Die Ersatzprognose (assumptions.fallback) nutzt kein
   Wetter und braucht deshalb keines.
"""
from datetime import date, timedelta

import config


def _expected(start_date: str, days: int) -> list[tuple[str, str]]:
    start = date.fromisoformat(start_date)
    tage = [start + timedelta(days=i) for i in range(days)]
    return [(d.isoformat(), s) for d in tage if d.weekday() in config.OPEN_WEEKDAYS
            for s in config.SHIFTS]


def _is_number(x) -> bool:
    return isinstance(x, (int, float)) and not isinstance(x, bool)


def check_plausibility(forecast: list[dict], start_date: str, days: int = 7) -> dict:
    """Prüft Vollständigkeit (alle offenen Tage × Schichten), Spannen und Kapazität.

    Rückgabe: {"ok": False, "issues": ["2026-10-28 nachmittag fehlt"]}
    """
    if not forecast:
        return {"ok": False, "issues": ["Prognose ist leer"]}

    issues: list[str] = []
    erwartet = _expected(start_date, days)
    gesehen: set[tuple[str, str]] = set()

    for row in forecast:
        key = (row.get("date"), row.get("shift"))
        name = f"{key[0]} {key[1]}"
        if key in gesehen:
            issues.append(f"{name} ist doppelt")
            continue
        gesehen.add(key)
        if key not in erwartet:
            issues.append(f"{name} gehört nicht zum Planungshorizont (Ruhetag oder ausserhalb)")
            continue

        g, lo, hi = row.get("guests"), row.get("lower"), row.get("upper")
        if not all(_is_number(x) for x in (g, lo, hi)):
            issues.append(f"{name}: Gäste oder Spanne fehlen")
            continue
        if g < 0:
            issues.append(f"{name}: {g} Gäste ist negativ")
        elif g > config.CAPACITY_PER_SHIFT:
            issues.append(f"{name}: {g} Gäste über Kapazität ({config.CAPACITY_PER_SHIFT})")
        if not lo <= g <= hi:
            issues.append(f"{name}: Spanne {lo}–{hi} passt nicht zu {g} Gästen")

        annahmen = row.get("assumptions") or {}
        if not annahmen.get("fallback") and (annahmen.get("temp_max") is None
                                              or annahmen.get("rain_mm") is None):
            issues.append(f"{name}: Wetterwerte fehlen")

    issues += [f"{d} {s} fehlt" for d, s in erwartet if (d, s) not in gesehen]
    return {"ok": not issues, "issues": issues}
