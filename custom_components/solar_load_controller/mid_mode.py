"""Helpers and tuning constants for mid-forecast runtime behavior.

Mid mode is a calm, independent mode for days with moderate solar yield
(between the low and high thresholds). It does NOT share logic with low mode:

* No runtime-pressure curve - decisions do not become more aggressive over time.
* Simple hold window - after a forecast_run start, mid mode keeps running for a
  short fixed period (MID_FORECAST_ASSISTED_HOLD_MINUTES) even if the solar
  signal temporarily collapses.  Grid-import protection still applies.
  There is no decayed support signal or hysteresis beyond this plain timer.
* No force cascade - minimum runtime forcing remains a low-mode responsibility.
* No battery discharge - charging solar that is usable on the AC side may count,
  but an actively discharging battery blocks assisted starts.
* No next-hour fallback - if forecast_next_hour_kwh is unavailable, mid mode
  uses whatever current solar is available instead of waiting.

The two public functions are pure and tested in isolation.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tuning constants - all MID_FORECAST_* live here so that coordinator.py
# can import them from a single home.
# ---------------------------------------------------------------------------

# Share of load_power_w solar must supply for an assisted start.
MID_FORECAST_ASSISTED_SURPLUS_RATIO: float = 0.55

# Share of a full-load hour the next-hour forecast must reach to justify waiting.
MID_FORECAST_WAIT_NEXT_HOUR_RATIO: float = 0.75

# Hold window after a forecast_run start, absorbing brief solar dropouts.
# Grid-import protection still cancels it immediately.
MID_FORECAST_ASSISTED_HOLD_MINUTES: float = 5.0

# Deadband on the load-compensated battery reading, absorbing regulation noise
# around balance. Scales with load power; the floor wins below a 1 kW load.
MID_FORECAST_DISCHARGE_DEADBAND_W: float = 50.0
MID_FORECAST_DISCHARGE_DEADBAND_RATIO: float = 0.05


def discharge_deadband_w(
    load_power_w: float,
    *,
    floor_w: float = MID_FORECAST_DISCHARGE_DEADBAND_W,
    ratio: float = MID_FORECAST_DISCHARGE_DEADBAND_RATIO,
) -> float:
    """Return how far below zero the compensated battery may sit before blocking."""
    if load_power_w <= 0:
        return floor_w
    return round(max(floor_w, load_power_w * ratio), 1)


def battery_discharge_blocks_assist(
    *,
    battery_power_state: str,
    is_load_on: bool,
    battery_power_w: float | None,
    load_power_w: float,
) -> bool:
    """Return whether battery discharge blocks an assisted run.

    Judged on the counterfactual, matching ``effective_solar_surplus_w``: with
    the load off the raw state applies, with it on the load's draw is credited
    back and only a remaining discharge beyond the deadband blocks.
    """
    if battery_power_state != "discharging":
        return False
    if not is_load_on or battery_power_w is None:
        return True
    return (battery_power_w + load_power_w) <= -discharge_deadband_w(load_power_w)


def should_allow_mid_mode_assisted_run(
    *,
    effective_solar_surplus_w: float,
    load_power_w: float,
    battery_power_state: str,
    projected_grid_import_exceeds_limit: bool,
    is_load_on: bool = False,
    battery_power_w: float | None = None,
    surplus_ratio: float = MID_FORECAST_ASSISTED_SURPLUS_RATIO,
) -> bool:
    """Return whether mid mode may start the load with partial solar coverage.

    Mid mode uses AC-usable solar surplus, including solar that is currently
    being diverted into battery charging. It still blocks assisted starts while
    the battery is discharging on its own account. The check is intentionally
    simple: no pressure curve, no priority adjustment.
    """
    if projected_grid_import_exceeds_limit:
        return False
    if battery_discharge_blocks_assist(
        battery_power_state=battery_power_state,
        is_load_on=is_load_on,
        battery_power_w=battery_power_w,
        load_power_w=load_power_w,
    ):
        return False
    if load_power_w <= 0:
        return False
    threshold_w = round(load_power_w * surplus_ratio, 1)
    return effective_solar_surplus_w >= threshold_w


def forecast_assisted_run_available(
    *,
    is_currently_assisting: bool,
    minutes_since_turn_on: float | None,
    projected_grid_import_exceeds_limit: bool,
    available_surplus_w: float,
    effective_solar_surplus_w: float,
    load_power_w: float,
    battery_power_state: str,
    is_load_on: bool = False,
    battery_power_w: float | None = None,
    assisted_hold_minutes: float = MID_FORECAST_ASSISTED_HOLD_MINUTES,
) -> bool:
    """Return whether mid mode may run the load via forecast assistance.

    Callers must pre-check that the current day class is mid and that runtime
    is still outstanding and not already being forced.
    """
    if available_surplus_w >= load_power_w:
        return False
    if (
        is_currently_assisting
        and minutes_since_turn_on is not None
        and minutes_since_turn_on < assisted_hold_minutes
    ):
        return not projected_grid_import_exceeds_limit
    return should_allow_mid_mode_assisted_run(
        effective_solar_surplus_w=effective_solar_surplus_w,
        load_power_w=load_power_w,
        battery_power_state=battery_power_state,
        projected_grid_import_exceeds_limit=projected_grid_import_exceeds_limit,
        is_load_on=is_load_on,
        battery_power_w=battery_power_w,
    )


def should_wait_for_mid_forecast(
    *,
    forecast_remaining_kwh: float | None,
    forecast_next_hour_kwh: float | None,
    slack_minutes: float,
    load_power_w: float,
    wait_minutes: float,
    next_hour_ratio: float = MID_FORECAST_WAIT_NEXT_HOUR_RATIO,
) -> bool:
    """Return whether mid mode should wait for a better solar window.

    Returns False when forecast_next_hour_kwh is None: without next-hour data
    mid mode acts on current solar rather than waiting.

    Args:
        forecast_remaining_kwh: Remaining today forecast; None skips waiting.
        forecast_next_hour_kwh: Next-hour forecast; None → never wait.
        slack_minutes: Minutes between now and the latest finish time minus
            remaining required runtime.
        load_power_w: Configured load power in watts.
        wait_minutes: Minimum slack required before we consider waiting
            (typically DEFAULT_FORECAST_WAIT_MINUTES = 60).
        next_hour_ratio: Fraction of a full-load hour the next-hour forecast
            must reach to justify waiting.
    """
    # No remaining forecast - no point waiting.
    if forecast_remaining_kwh is None:
        return False
    # No next-hour data - use current solar, do not wait.
    if forecast_next_hour_kwh is None:
        return False
    # Not enough slack to absorb a wait period.
    if slack_minutes <= wait_minutes:
        return False
    if load_power_w <= 0:
        return False

    threshold_kwh = round(load_power_w * next_hour_ratio / 1000, 4)
    return forecast_next_hour_kwh >= threshold_kwh
