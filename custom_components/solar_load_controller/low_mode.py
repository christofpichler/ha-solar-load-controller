"""Helpers for low-forecast runtime behavior."""

from __future__ import annotations


def runtime_pressure(progress: float, *, exponent: float) -> float:
    """Return a clamped low-mode runtime pressure value between 0 and 1."""
    clamped_progress = min(1.0, max(0.0, progress))
    return clamped_progress**exponent


def runtime_wait_buffer_minutes(
    min_daily_runtime_minutes: float,
    progress: float,
    *,
    min_ratio: float,
    max_ratio: float,
    exponent: float,
) -> float:
    """Return how much remaining slack low mode may still tolerate."""
    if min_daily_runtime_minutes <= 0:
        return 0.0

    shaped_progress = runtime_pressure(progress, exponent=exponent)
    ratio = min_ratio + shaped_progress * max(0.0, max_ratio - min_ratio)
    return round(max(0.0, min_daily_runtime_minutes * ratio), 1)


def should_force_runtime(
    runtime_remaining_minutes: float,
    minutes_until_finish: float,
    min_daily_runtime_minutes: float,
    progress: float,
    *,
    min_ratio: float,
    max_ratio: float,
    exponent: float,
) -> bool:
    """Return whether low mode should already force runtime."""
    if runtime_remaining_minutes <= 0:
        return False

    slack_minutes = max(0.0, minutes_until_finish - runtime_remaining_minutes)
    wait_buffer_minutes = runtime_wait_buffer_minutes(
        min_daily_runtime_minutes,
        progress,
        min_ratio=min_ratio,
        max_ratio=max_ratio,
        exponent=exponent,
    )
    return slack_minutes <= wait_buffer_minutes


def forecast_wait_threshold_kwh(
    load_power_w: float,
    wait_minutes: float,
    pressure: float,
    *,
    min_multiplier: float,
    max_multiplier: float,
) -> float:
    """Return the next-hour forecast threshold needed to justify waiting."""
    if load_power_w <= 0 or wait_minutes <= 0:
        return 0.0

    clamped_pressure = min(1.0, max(0.0, pressure))
    multiplier = min_multiplier + clamped_pressure * max(
        0.0, max_multiplier - min_multiplier
    )
    base_threshold_kwh = load_power_w * wait_minutes / 60 / 1000
    return round(base_threshold_kwh * multiplier, 3)


def should_wait_for_forecast(
    *,
    forecast_remaining_kwh: float | None,
    forecast_next_hour_kwh: float | None,
    slack_minutes: float,
    wait_buffer_minutes: float,
    load_power_w: float,
    wait_minutes: float,
    pressure: float,
    min_multiplier: float,
    max_multiplier: float,
) -> bool:
    """Return whether low mode should still wait for better solar."""
    if forecast_remaining_kwh is None:
        return False

    if slack_minutes <= wait_buffer_minutes:
        return False

    if forecast_next_hour_kwh is None:
        return True

    threshold_kwh = forecast_wait_threshold_kwh(
        load_power_w,
        wait_minutes,
        pressure,
        min_multiplier=min_multiplier,
        max_multiplier=max_multiplier,
    )
    return forecast_next_hour_kwh >= threshold_kwh


def assisted_run_surplus_threshold_w(
    load_power_w: float,
    pressure: float,
    *,
    early_ratio: float,
    late_ratio: float,
) -> float:
    """Return the solar contribution needed for a low-mode assisted start."""
    if load_power_w <= 0:
        return 0.0

    clamped_pressure = min(1.0, max(0.0, pressure))
    ratio = max(0.0, early_ratio - clamped_pressure * max(0.0, early_ratio - late_ratio))
    return round(load_power_w * ratio, 1)


def should_allow_assisted_run(
    *,
    effective_solar_surplus_w: float,
    projected_grid_import_exceeds_limit: bool,
    battery_power_state: str,
    forecast_next_hour_kwh: float | None,
    forecast_wait_threshold_kwh: float,
    required_surplus_w: float,
) -> bool:
    """Return whether low mode may start with partial current solar support."""
    if projected_grid_import_exceeds_limit:
        return False
    if battery_power_state == "discharging":
        return False
    if effective_solar_surplus_w < required_surplus_w:
        return False
    if forecast_next_hour_kwh is None:
        return False
    return forecast_next_hour_kwh >= forecast_wait_threshold_kwh
