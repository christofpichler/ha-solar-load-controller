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


def should_prioritize_battery_after_runtime(
    *,
    forecast_day_class: str,
    high_forecast_day_class: str,
    runtime_remaining_minutes: float,
    battery_headroom_kwh: float | None,
    battery_charge_required_kwh: float | None,
    battery_soc: float | None,
    battery_power_state: str,
    forecast_remaining_kwh: float | None,
    household_reserve_kwh: float,
    time_priority_buffer_kwh: float,
    battery_target_soc: float = HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC,
    battery_headroom_min_kwh: float = HIGH_FORECAST_POST_RUNTIME_BATTERY_HEADROOM_KWH,
) -> bool:
    """Return whether battery should win over optional high-mode runtime.

    Battery priority after runtime is a high-mode concept only. On low and mid
    days the minimum runtime is the only target; once it is met the load simply
    stops (``runtime_met``). Applying high-mode battery reservation logic on
    those days would incorrectly block solar surplus runs and emit a confusing
    ``battery_priority`` reason.
    """
    if forecast_day_class != high_forecast_day_class:
        return False
    if runtime_remaining_minutes > 0:
        return False

    if (
        battery_headroom_kwh is not None
        and battery_headroom_kwh <= battery_headroom_min_kwh
    ):
        return False

    if battery_soc is None:
        return battery_power_state == "charging"

    if battery_soc >= battery_target_soc:
        return False

    if forecast_remaining_kwh is None or battery_charge_required_kwh is None:
        return True

    return (
        forecast_remaining_kwh
        < battery_charge_required_kwh
        + household_reserve_kwh
        + time_priority_buffer_kwh
    )


def export_guard_run_available(
    *,
    forecast_day_class: str,
    high_forecast_day_class: str,
    is_load_on: bool,
    grid_import_w: float | None,
    grid_import_no_grid_tolerance_w: float,
    high_forecast_grid_import_active: bool,
    should_prioritize_battery: bool,
    allow_post_runtime_restart: bool,
    available_surplus_w: float,
    usable_battery_charge_w: float,
    load_power_w: float,
    battery_power_state: str,
    pv_current_power_w: float | None,
    forecast_remaining_kwh: float | None,
    battery_charge_required_kwh: float | None,
    curtailment_headroom_ratio: float = HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO,
) -> bool:
    """Return whether forecast suggests running now to avoid clipping later.

    Includes the Solarbank guard: do not trigger via forecast-headroom while
    the battery is actively discharging to cover household load and PV alone
    is below the load power. In that state the low grid-import reading is an
    artefact of self-discharge management, not a solar surplus signal.
    """
    if forecast_day_class != high_forecast_day_class:
        return False
    if (
        not is_load_on
        and grid_import_w is not None
        and grid_import_w > grid_import_no_grid_tolerance_w
    ):
        return False
    if high_forecast_grid_import_active:
        return False
    if should_prioritize_battery:
        return False
    if available_surplus_w >= load_power_w:
        return True
    if not allow_post_runtime_restart:
        return False
    if (
        (available_surplus_w + usable_battery_charge_w) >= load_power_w
        and (is_load_on or battery_power_state == "charging")
    ):
        return True

    if forecast_remaining_kwh is None or battery_charge_required_kwh is None:
        return False

    if battery_power_state == "discharging" and (
        pv_current_power_w is None or pv_current_power_w < load_power_w
    ):
        return False

    return (
        forecast_remaining_kwh
        >= battery_charge_required_kwh * curtailment_headroom_ratio
    )
