"""Helpers for high-forecast runtime behavior."""

from __future__ import annotations


def allow_post_runtime_curtailment_restart(
    *,
    is_load_on: bool,
    runtime_remaining_minutes: float,
    available_surplus_w: float,
    effective_solar_surplus_w: float,
    load_power_w: float,
    forecast_next_hour_kwh: float | None,
    restart_surplus_margin_w: float,
    next_hour_ratio: float,
) -> bool:
    """Return whether high-mode curtailment may restart after runtime is met.

    Once the minimum daily runtime is already satisfied, restarting purely from
    battery charge power should be more conservative than restarting from real
    export. This reduces late-afternoon off/on loops when PV is tapering off.
    """
    if is_load_on or runtime_remaining_minutes > 0:
        return True

    if available_surplus_w >= load_power_w:
        return True

    if effective_solar_surplus_w < load_power_w + restart_surplus_margin_w:
        return False

    if forecast_next_hour_kwh is None:
        return False

    required_next_hour_kwh = load_power_w * next_hour_ratio / 1000
    return forecast_next_hour_kwh >= required_next_hour_kwh
