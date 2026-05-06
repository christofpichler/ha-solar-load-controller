"""Helpers and tuning constants for high-forecast runtime behavior."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tuning constants — all HIGH_FORECAST_* live here so coordinator.py
# (and the future mid_mode.py) can import them from a single home.
# ---------------------------------------------------------------------------

# curtailment / grid-import tolerance
HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO: float = 0.8
HIGH_FORECAST_NO_GRID_TOLERANCE_W: float = 25.0

# post-runtime battery top-up targets
HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC: float = 99.0
HIGH_FORECAST_POST_RUNTIME_BATTERY_HEADROOM_KWH: float = 0.05

# post-runtime export-guard restart thresholds
HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W: float = 75.0
HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO: float = 1.5

# post-runtime priority-buffer timing
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS: float = 2.0
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS: float = 8.0
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT: float = 1.6


def allow_post_runtime_export_guard_restart(
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
    """Return whether high-mode export guard may restart after runtime is met.

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
