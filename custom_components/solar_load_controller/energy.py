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


def usable_battery_charge_for_ac_surplus(
    battery_charge_w: float,
    pv_current_power_w: float | None,
    inverter_limit_w: float | None,
) -> float:
    """Return battery charge power that may still help an AC load decision.

    If current PV already exceeds the AC inverter limit, the clipped portion is
    assumed to go into the battery and is not treated as freely usable surplus
    for starting another AC load.
    """
    if battery_charge_w <= 0:
        return 0.0
    if pv_current_power_w is None or inverter_limit_w is None or inverter_limit_w <= 0:
        return round(battery_charge_w, 1)

    clipped_to_battery_w = max(0.0, pv_current_power_w - inverter_limit_w)
    return round(max(0.0, battery_charge_w - clipped_to_battery_w), 1)


def household_energy_reserve_kwh(
    base_household_load_w: float,
    reserve_margin_percent: float,
    remaining_hours: float,
) -> float:
    """Return household reserve energy for the remaining day window."""
    if base_household_load_w <= 0 or remaining_hours <= 0:
        return 0.0
    effective_household_load_w = base_household_load_w * (
        1 + max(0.0, reserve_margin_percent) / 100
    )
    return round(effective_household_load_w * remaining_hours / 1000, 3)
