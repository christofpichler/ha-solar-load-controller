"""Helpers and tuning constants for mid-forecast runtime behavior.

Mid mode is a calm, independent mode for days with moderate solar yield
(between the low and high thresholds). It does NOT share logic with low mode:

* No runtime-pressure curve — decisions do not become more aggressive over time.
* Simple hold window — after a forecast_run start, mid mode keeps running for a
  short fixed period (MID_FORECAST_ASSISTED_HOLD_MINUTES) even if the solar
  signal temporarily collapses.  Grid-import protection still applies.
  There is no decayed support signal or hysteresis beyond this plain timer.
* No force cascade — minimum runtime forcing remains a low-mode responsibility.
* No battery mixing — only grid-free solar surplus (available_surplus_w) is used.
* No next-hour fallback — if forecast_next_hour_kwh is unavailable, mid mode
  uses whatever current solar is available instead of waiting.

The two public functions are pure and tested in isolation.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Tuning constants — all MID_FORECAST_* live here so that coordinator.py
# can import them from a single home.
# ---------------------------------------------------------------------------

# Fraction of load_power_w that solar must supply for an assisted start.
# At 0.55 a 450 W load requires at least 247.5 W of solar surplus.
MID_FORECAST_ASSISTED_SURPLUS_RATIO: float = 0.55

# Fraction of a full-load hour expected in the next-hour forecast to justify
# waiting rather than starting. At 0.75 a 450 W load requires ≥ 0.3375 kWh
# forecast for the coming hour before mid mode decides to wait.
MID_FORECAST_WAIT_NEXT_HOUR_RATIO: float = 0.75

# Minutes to hold a forecast_run after the load has started, even if the solar
# signal temporarily drops below the assisted-run threshold.  Grid-import
# protection still cancels the hold immediately.  This prevents rapid cycling
# on installations with noisy solar measurements (e.g. microinverters that
# report 0 W briefly between measurement cycles).
MID_FORECAST_ASSISTED_HOLD_MINUTES: float = 5.0


def should_allow_mid_mode_assisted_run(
    *,
    effective_solar_surplus_w: float,
    load_power_w: float,
    battery_power_state: str,
    projected_grid_import_exceeds_limit: bool,
    surplus_ratio: float = MID_FORECAST_ASSISTED_SURPLUS_RATIO,
) -> bool:
    """Return whether mid mode may start the load with partial solar coverage.

    Mid mode uses only grid-free solar surplus (available_surplus_w) — callers
    must NOT pass a battery-boosted surplus value here.  The check is
    intentionally simple: no pressure curve, no priority adjustment.
    """
    if projected_grid_import_exceeds_limit:
        return False
    if battery_power_state == "discharging":
        return False
    if load_power_w <= 0:
        return False
    threshold_w = round(load_power_w * surplus_ratio, 1)
    return effective_solar_surplus_w >= threshold_w


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

    Unlike low mode, mid mode returns False when forecast_next_hour_kwh is
    None — there is no "wait because we think something better might come"
    fallback.  If we have no next-hour data we act on what we see now.

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
    # No remaining forecast — no point waiting.
    if forecast_remaining_kwh is None:
        return False
    # No next-hour data — use current solar, do not wait.
    if forecast_next_hour_kwh is None:
        return False
    # Not enough slack to absorb a wait period.
    if slack_minutes <= wait_minutes:
        return False
    if load_power_w <= 0:
        return False

    threshold_kwh = round(load_power_w * next_hour_ratio / 1000, 4)
    return forecast_next_hour_kwh >= threshold_kwh
