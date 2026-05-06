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


def assisted_run_strength_ratio(
    effective_solar_surplus_w: float,
    required_surplus_w: float,
) -> float:
    """Return how strongly current solar exceeds the low-assist threshold."""
    if required_surplus_w <= 0:
        return 0.0
    if effective_solar_surplus_w <= 0:
        return 0.0
    return round(effective_solar_surplus_w / required_surplus_w, 3)


def assisted_run_priority(
    progress: float,
    *,
    exponent: float,
) -> float:
    """Return how strongly low assist should prefer earlier PV usage."""
    clamped_progress = min(1.0, max(0.0, progress))
    if exponent <= 0:
        return clamped_progress
    return clamped_progress**exponent


def assisted_run_effective_surplus_threshold_w(
    required_surplus_w: float,
    assist_priority: float,
    *,
    late_relief_ratio: float,
) -> float:
    """Return the assisted surplus threshold after later-day relief."""
    if required_surplus_w <= 0:
        return 0.0

    clamped_priority = min(1.0, max(0.0, assist_priority))
    relief_ratio = clamped_priority * max(0.0, late_relief_ratio)
    return round(max(0.0, required_surplus_w * (1.0 - relief_ratio)), 1)


def assisted_run_forecast_threshold_kwh(
    forecast_wait_threshold_kwh: float,
    effective_solar_surplus_w: float,
    required_surplus_w: float,
    *,
    assist_priority: float,
    ratio_span: float,
    exponent: float,
    late_relief_ratio: float,
) -> float:
    """Return the forecast threshold after current solar quality relief.

    If current solar only barely exceeds the assisted threshold, the next-hour
    forecast should still matter almost fully. If current solar strongly
    exceeds the threshold, the forecast hurdle should rapidly fade because the
    controller should use that strong current solar window on a low day.
    """
    if forecast_wait_threshold_kwh <= 0:
        return 0.0

    strength_ratio = assisted_run_strength_ratio(
        effective_solar_surplus_w,
        required_surplus_w,
    )
    priority_relief = min(1.0, max(0.0, assist_priority)) * max(0.0, late_relief_ratio)
    if strength_ratio <= 1.0:
        return round(max(0.0, forecast_wait_threshold_kwh * (1.0 - priority_relief)), 3)

    if ratio_span <= 0:
        return round(
            max(
                0.0,
                forecast_wait_threshold_kwh
                * (1.0 - priority_relief),
            ),
            3,
        )

    normalized_strength = min(1.0, max(0.0, (strength_ratio - 1.0) / ratio_span))
    strength_relief = normalized_strength**exponent
    relief = min(1.0, strength_relief + priority_relief)
    return round(max(0.0, forecast_wait_threshold_kwh * (1.0 - relief)), 3)


def should_allow_assisted_run(
    *,
    effective_solar_surplus_w: float,
    projected_grid_import_exceeds_limit: bool,
    battery_power_state: str,
    forecast_next_hour_kwh: float | None,
    forecast_wait_threshold_kwh: float,
    required_surplus_w: float,
    assist_priority: float,
    forecast_override_ratio_span: float,
    forecast_override_exponent: float,
    surplus_late_relief_ratio: float,
    forecast_late_relief_ratio: float,
) -> bool:
    """Return whether low mode may start with partial current solar support."""
    if projected_grid_import_exceeds_limit:
        return False
    if battery_power_state == "discharging":
        return False

    effective_required_surplus_w = assisted_run_effective_surplus_threshold_w(
        required_surplus_w,
        assist_priority,
        late_relief_ratio=surplus_late_relief_ratio,
    )
    if effective_solar_surplus_w < effective_required_surplus_w:
        return False

    assisted_forecast_threshold_kwh = assisted_run_forecast_threshold_kwh(
        forecast_wait_threshold_kwh,
        effective_solar_surplus_w,
        effective_required_surplus_w,
        assist_priority=assist_priority,
        ratio_span=forecast_override_ratio_span,
        exponent=forecast_override_exponent,
        late_relief_ratio=forecast_late_relief_ratio,
    )
    if forecast_next_hour_kwh is None:
        return assisted_forecast_threshold_kwh <= 0
    return forecast_next_hour_kwh >= assisted_forecast_threshold_kwh


def should_keep_assisted_run(
    *,
    minutes_since_turn_on: float,
    configured_min_on_minutes: float,
    assisted_hold_minutes: float,
    projected_grid_import_exceeds_limit: bool,
    forecast_next_hour_kwh: float | None,
    forecast_wait_threshold_kwh: float,
    effective_solar_surplus_w: float,
    current_effective_solar_surplus_w: float,
    required_surplus_w: float,
    assist_priority: float,
    forecast_override_ratio_span: float,
    forecast_override_exponent: float,
    surplus_late_relief_ratio: float,
    forecast_late_relief_ratio: float,
    hold_surplus_ratio: float,
    hold_forecast_ratio: float,
    collapse_floor_ratio: float,
) -> bool:
    """Return whether an active low-assist run should be held a bit longer."""
    if projected_grid_import_exceeds_limit:
        return False

    hold_minutes = max(0.0, configured_min_on_minutes, assisted_hold_minutes)
    if minutes_since_turn_on >= hold_minutes:
        return False

    effective_required_surplus_w = assisted_run_effective_surplus_threshold_w(
        required_surplus_w,
        assist_priority,
        late_relief_ratio=surplus_late_relief_ratio,
    )
    collapse_floor_w = round(
        max(0.0, effective_required_surplus_w * max(0.0, collapse_floor_ratio)),
        1,
    )
    if current_effective_solar_surplus_w < collapse_floor_w:
        return False

    hold_required_surplus_w = round(
        max(0.0, effective_required_surplus_w * max(0.0, hold_surplus_ratio)),
        1,
    )
    if effective_solar_surplus_w < hold_required_surplus_w:
        return False

    assisted_forecast_threshold_kwh = assisted_run_forecast_threshold_kwh(
        forecast_wait_threshold_kwh,
        effective_solar_surplus_w,
        hold_required_surplus_w,
        assist_priority=assist_priority,
        ratio_span=forecast_override_ratio_span,
        exponent=forecast_override_exponent,
        late_relief_ratio=forecast_late_relief_ratio,
    )
    assisted_forecast_threshold_kwh = round(
        max(0.0, assisted_forecast_threshold_kwh * max(0.0, hold_forecast_ratio)),
        3,
    )
    if forecast_next_hour_kwh is None:
        return assisted_forecast_threshold_kwh <= 0
    return forecast_next_hour_kwh >= assisted_forecast_threshold_kwh
