"""Energy calculation helpers."""

from __future__ import annotations


def required_input_energy(storage_kwh: float | None, efficiency: float) -> float | None:
    """Return input energy required to store the requested energy."""
    if storage_kwh is None:
        return None
    if storage_kwh <= 0:
        return 0.0
    if efficiency <= 0:
        return None
    return round(storage_kwh / efficiency, 3)
