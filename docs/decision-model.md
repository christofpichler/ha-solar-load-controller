# Decision Model

This document explains the technical decision model behind the Solar Load
Controller integration. It focuses on the internal runtime logic, the current
mode-specific helper functions, and the hardcoded tuning constants that shape
behavior.

## Overview

The controller makes a decision on every relevant state update and reduces that
decision to one short reason such as `solar`, `low_wait`, `export_guard`, or
`battery_priority`.

At a high level, the runtime flow combines:

- current grid import and export
- current battery state
- current and remaining PV forecast
- minimum daily runtime progress
- the configured day window
- mode-specific logic for `low` and `high`

The day class is captured once per day after `06:00` and then held stable for
that day unless the user applies a manual mode override.

Current day classes:

- `low`
- `high`

`mid` is planned, but not implemented yet.

## Core Calculations

These shared values drive both current modes.

### `available_surplus_w`

Real export surplus that is currently visible at the grid point.

- based on the export sensor
- used as the strongest signal for “this load can run from real AC surplus”

### `effective_solar_surplus_w`

Broader solar support estimate used for runtime decisions.

It combines:

- real export surplus
- battery charging power that is still usable for AC load decisions

It explicitly does **not** blindly count battery charging above the AC inverter
limit as freely usable AC surplus.

Relevant helper:

- `usable_battery_charge_for_ac_surplus(...)` in
  [energy.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/energy.py)

### `projected_grid_import_w`

Estimated grid import if the load were started or kept running.

Typical formulas:

- while off:
  `current_grid_import - current_grid_export + load_power`
- while on:
  `current_grid_import`

This is one of the main guards against false restarts.

### `battery_charge_required_kwh`

Energy still needed to charge the battery from current SOC toward the active
target, including charging losses.

Relevant helper:

- `required_input_energy(...)` in
  [energy.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/energy.py)

## Day Class Capture

The controller distinguishes between:

- live forecast values that continue updating during the day
- a captured day class that stabilizes overall mode behavior

After `06:00`, the integration captures the day class from:

- `forecast_today_kwh`
- `pv_size_kwp`
- configured high-mode threshold in `kWh/kWp`

That means:

- `forecast_remaining_today_kwh` and `forecast_next_hour_kwh` remain live
- `forecast_day_class` remains stable for the day

This prevents mode flapping when forecast services revise totals during the
day.

## Decision Reasons

The current short decision reasons are:

- `solar`
- `export_guard`
- `forecast_run`
- `forecast`
- `low_assist`
- `low_wait`
- `grid_import`
- `battery`
- `battery_priority`
- `runtime_force`
- `runtime_met`
- `paused`
- `waiting`
- `missing_sensor`
- `min_on`
- `min_off`
- `time_window`

## High Mode

High mode is designed for strong forecast days. It is more willing to use
available solar support early, but becomes stricter later in the day after the
minimum runtime is already satisfied.

### Main behavior

Before minimum runtime is met:

- can run from real surplus
- can run from broader effective solar support when the grid situation is clean

After minimum runtime is met:

- battery completion becomes more important
- expected household consumption is reserved
- a late-day time-priority buffer is added
- restart decisions become stricter

### Key helpers

In [energy.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/energy.py):

- `household_energy_reserve_kwh(...)`
- `time_priority_buffer_kwh(...)`

In [high_mode.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/high_mode.py):

- `allow_post_runtime_export_guard_restart(...)`

### High-mode tuning constants

These are currently hardcoded in
[coordinator.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/coordinator.py).

#### Shared high-mode forecast and restart behavior

- `HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO = 0.8`
  - minimum fraction of post-runtime battery need that still counts as “enough
    remaining forecast” for a strong day
- `HIGH_FORECAST_NO_GRID_TOLERANCE_W = 25`
  - tolerance for “no meaningful grid import” checks in high mode
- `BATTERY_CHARGING_EFFICIENCY = 0.9`
  - used when converting battery headroom into required PV input energy
- `HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC = 99`
  - internal battery-complete target for post-runtime high-mode logic
- `HIGH_FORECAST_POST_RUNTIME_BATTERY_HEADROOM_KWH = 0.05`
  - small top-end headroom under which the battery is treated as effectively at
    target
- `HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W = 75`
  - extra effective-surplus margin required for post-runtime restart when no
    real export is available
- `HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO = 1.5`
  - multiplier that defines how strong the next-hour forecast must be for a
    restart based on effective solar support

#### Late-day battery-priority curve

- `HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS = 2.0`
  - minimum reserve window, expressed as hours of effective household load
- `HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS = 8.0`
  - maximum reserve window late in the day
- `HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT = 1.6`
  - shapes the late-day rise of battery priority; values above `1.0` make it
    more conservative later than earlier

### High-mode config inputs

These are user-configurable and directly feed the high-mode model:

- `forecast_high_threshold_kwh_per_kwp`
- `high_mode_base_household_load_w`
- `high_mode_household_reserve_margin_percent`

## Low Mode

Low mode is designed for weaker forecast days. Its job is not to maximize
surplus usage, but to reach the minimum daily runtime with as little unnecessary
grid and battery stress as possible.

### Main behavior

Low mode currently has three main phases:

1. **Wait defensively**
   - if enough time slack remains and the short-term forecast still justifies
     waiting, it emits `low_wait`
2. **Allow controlled assisted starts**
   - if there is partial current solar support, a clean projected grid state,
     and enough short-term forecast confidence, it may emit `low_assist`
3. **Force runtime when the deadline gets too close**
   - once waiting is no longer responsible, it falls through toward
     `runtime_force`

### Key helpers

In [low_mode.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/low_mode.py):

- `runtime_pressure(...)`
- `runtime_wait_buffer_minutes(...)`
- `should_force_runtime(...)`
- `forecast_wait_threshold_kwh(...)`
- `should_wait_for_forecast(...)`
- `assisted_run_surplus_threshold_w(...)`
- `should_allow_assisted_run(...)`
- `should_keep_assisted_run(...)`

### Low-mode tuning constants

These are currently hardcoded in
[coordinator.py](/Users/A200029998/Documents/pool-automation/custom_components/solar_load_controller/coordinator.py).

#### Runtime pressure curve

- `LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO = 0.15`
  - early-day tolerance for remaining slack, expressed as a fraction of minimum
    daily runtime
- `LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO = 0.75`
  - late-day tolerance for remaining slack before low mode should stop waiting
- `LOW_FORECAST_RUNTIME_BUFFER_EXPONENT = 1.6`
  - shapes how fast runtime pressure ramps up over the day

Together these constants answer:

- how much slack low mode may still tolerate
- and how early `runtime_force` should begin to take over

#### Forecast-wait thresholds

- `LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER = 1.0`
  - early-day multiplier for the next-hour forecast threshold
- `LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER = 1.75`
  - later-day multiplier that makes waiting harder to justify

Together they shape how optimistic low mode still is about waiting for a better
solar window.

#### Assisted-run thresholds

- `LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO = 0.85`
  - early in the day, low assist requires almost the full load power to be
    backed by current effective solar support
- `LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO = 0.35`
  - later in the day, low assist can start with less current solar support
    because runtime pressure is higher
- `LOW_FORECAST_ASSISTED_HOLD_MINUTES = 3.0`
  - once started via `low_assist`, the controller will hold the run for a short
    additional window, as long as the projected grid state stays clean and the
    next-hour forecast still justifies it

### Low-mode config inputs

These user-configurable values most strongly affect low-mode behavior:

- `grid_import_limit_w`
- `min_daily_runtime_minutes`
- `min_runtime_grid_override`
- `min_runtime_battery_override`
- `min_battery_soc`

## Mid Mode

`mid` is not implemented yet.

The likely role of `mid` is to sit between:

- low-mode deadline protection
- and high-mode aggressive surplus usage

Once `mid` exists, this document should be extended with:

- its own helper functions
- its own tuning constants
- its own boundary against `low` and `high`

## Debugging and Analysis

For practical debugging there are two main surfaces:

- `sensor.<name>_decision_reason`
  - compact reason plus contextual attributes
- `sensor.<name>_decision_debug`
  - full structured decision tree when debug is enabled

The JSONL decision log records:

- the final decision
- all decision inputs
- relevant settings
- raw Home Assistant states
- manual load changes as separate events

Manual load changes are logged with:

- `event.type = "load_change"`
- `event.source = "manual"`
- `event.action = "turn_on"` or `turn_off`

That makes it possible to exclude manual tests from later behavior analysis.
