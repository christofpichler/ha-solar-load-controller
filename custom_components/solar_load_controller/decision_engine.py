"""Pure decision engine for Solar Load Controller."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .const import (
    DECISION_AUTOMATION_PAUSED,
    DECISION_BATTERY_PROTECTED,
    DECISION_BATTERY_PRIORITY,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_FORECAST_WAIT,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_LOW_FORECAST_WAIT,
    DECISION_MINIMUM_OFF_TIME_ACTIVE,
    DECISION_MINIMUM_ON_TIME_ACTIVE,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_MISSING_REQUIRED_SENSOR,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DECISION_TIME_WINDOW_BLOCKED,
    DECISION_WAITING_FOR_SURPLUS,
)


@dataclass(frozen=True)
class DecisionCheck:
    """One decision check for debug output."""

    name: str
    passed: bool


@dataclass(frozen=True)
class DecisionInputs:
    """Inputs needed to decide the configured load state."""

    is_load_on: bool
    automation_paused: bool
    inside_time_window: bool
    missing_required_grid_sensor_value: bool
    grid_import_w: float | None
    grid_export_w: float | None
    grid_import_limit_w: float
    grid_import_start_limit_w: float
    grid_import_over_limit_duration_seconds: float
    grid_import_shutdown_delay_seconds: float
    grid_import_shutdown_allowed: bool
    grid_import_cooldown_active: bool
    grid_import_cooldown_remaining_seconds: float
    projected_grid_import_w: float | None
    projected_grid_import_formula: str
    available_surplus_w: float
    effective_solar_surplus_w: float
    load_power_w: float
    runtime_today_minutes: float
    runtime_remaining_minutes: float
    required_remaining_energy_kwh: float
    minutes_until_finish: float
    low_mode_runtime_progress: float
    low_mode_runtime_pressure: float
    low_mode_runtime_slack_minutes: float
    low_mode_runtime_wait_buffer_minutes: float
    low_mode_forecast_wait_threshold_kwh: float
    low_mode_assisted_surplus_threshold_w: float
    min_on_active: bool
    min_on_remaining_minutes: float
    min_off_active: bool
    min_off_remaining_minutes: float
    export_guard_run_available: bool
    battery_priority_after_runtime: bool
    battery_headroom_kwh: float | None
    battery_charge_required_kwh: float | None
    high_forecast_post_runtime_battery_charge_required_kwh: float | None
    high_mode_base_household_load_w: float
    high_mode_household_reserve_margin_percent: float
    high_mode_household_reserve_kwh: float
    forecast_excess_after_battery_kwh: float | None
    forecast_assisted_run_available: bool
    high_forecast_grid_import_active: bool
    high_forecast_grid_import_duration_seconds: float
    high_forecast_grid_import_shutdown_delay_seconds: float
    must_force_minimum_runtime: bool
    min_runtime_battery_override: bool
    min_runtime_grid_override: bool
    projected_grid_import_exceeds_limit: bool
    battery_can_support_forced_runtime: bool
    should_wait_for_forecast: bool
    battery_mode: str
    battery_soc: float | None
    battery_power_w: float | None
    battery_power_state: str
    forecast_today_kwh: float | None
    forecast_remaining_today_kwh: float | None
    forecast_next_hour_kwh: float | None
    forecast_kwh_per_kwp: float | None
    forecast_day_class: str


@dataclass(frozen=True)
class DecisionResult:
    """Decision result and debug trace."""

    should_run: bool
    reason: str
    available_surplus_w: float
    runtime_remaining_minutes: float
    summary: str
    inputs: DecisionInputs
    checks: tuple[DecisionCheck, ...]

    def as_debug_dict(self) -> dict[str, Any]:
        """Return a Home Assistant friendly debug dictionary."""
        return {
            "final": {
                "should_run": self.should_run,
                "reason": self.reason,
                "summary": self.summary,
            },
            "inputs": asdict(self.inputs),
            "checks": [asdict(check) for check in self.checks],
        }


def evaluate_decision(inputs: DecisionInputs) -> DecisionResult:
    """Evaluate whether the configured load should run."""
    reason: str
    should_run: bool

    if inputs.automation_paused:
        should_run = False
        reason = DECISION_AUTOMATION_PAUSED
    elif not inputs.inside_time_window:
        should_run = False
        reason = DECISION_TIME_WINDOW_BLOCKED
    elif inputs.missing_required_grid_sensor_value:
        should_run = False
        reason = DECISION_MISSING_REQUIRED_SENSOR
    elif inputs.is_load_on and inputs.min_on_active:
        should_run = True
        reason = DECISION_MINIMUM_ON_TIME_ACTIVE
    elif (
        inputs.is_load_on
        and inputs.high_forecast_grid_import_active
    ):
        should_run = False
        reason = DECISION_GRID_IMPORT_LIMIT_EXCEEDED
    elif (
        inputs.is_load_on
        and inputs.grid_import_w is not None
        and inputs.grid_import_w > inputs.grid_import_limit_w
        and inputs.grid_import_shutdown_allowed
        and not _minimum_runtime_overrides_grid(inputs)
    ):
        should_run = False
        reason = DECISION_GRID_IMPORT_LIMIT_EXCEEDED
    elif (
        inputs.min_off_active
        and not inputs.must_force_minimum_runtime
    ):
        should_run = False
        reason = DECISION_MINIMUM_OFF_TIME_ACTIVE
    elif (
        inputs.grid_import_cooldown_active
        and not _minimum_runtime_overrides_grid(inputs)
    ):
        should_run = False
        reason = DECISION_GRID_IMPORT_LIMIT_EXCEEDED
    elif inputs.export_guard_run_available:
        should_run = True
        reason = DECISION_EXPORT_GUARD
    elif inputs.battery_priority_after_runtime:
        should_run = False
        reason = DECISION_BATTERY_PRIORITY
    elif inputs.runtime_remaining_minutes <= 0:
        should_run = False
        reason = DECISION_MINIMUM_RUNTIME_REACHED
    elif inputs.available_surplus_w >= inputs.load_power_w:
        should_run = True
        reason = DECISION_SOLAR_SURPLUS_AVAILABLE
    elif inputs.forecast_assisted_run_available:
        should_run = True
        if inputs.forecast_day_class == "low":
            reason = DECISION_LOW_FORECAST_ASSISTED_RUN
        else:
            reason = DECISION_FORECAST_ASSISTED_RUN
    elif inputs.must_force_minimum_runtime:
        if (
            inputs.projected_grid_import_exceeds_limit
            and not inputs.min_runtime_grid_override
        ):
            should_run = False
            reason = DECISION_GRID_IMPORT_LIMIT_EXCEEDED
        elif (
            not inputs.battery_can_support_forced_runtime
            and not _minimum_runtime_overrides_battery(inputs)
        ):
            should_run = False
            reason = DECISION_BATTERY_PROTECTED
        else:
            should_run = True
            reason = DECISION_MINIMUM_RUNTIME_REQUIRED
    elif inputs.should_wait_for_forecast:
        should_run = False
        if inputs.forecast_day_class == "low":
            reason = DECISION_LOW_FORECAST_WAIT
        else:
            reason = DECISION_FORECAST_WAIT
    else:
        should_run = False
        reason = DECISION_WAITING_FOR_SURPLUS

    checks = _build_checks(inputs)
    summary = _build_summary(inputs, should_run, reason)
    return DecisionResult(
        should_run=should_run,
        reason=reason,
        available_surplus_w=inputs.available_surplus_w,
        runtime_remaining_minutes=inputs.runtime_remaining_minutes,
        summary=summary,
        inputs=inputs,
        checks=checks,
    )


def _build_checks(inputs: DecisionInputs) -> tuple[DecisionCheck, ...]:
    """Return decision checks in the same order as the decision tree."""
    return (
        DecisionCheck("automation_paused", not inputs.automation_paused),
        DecisionCheck("time_window", inputs.inside_time_window),
        DecisionCheck(
            "required_grid_sensors",
            not inputs.missing_required_grid_sensor_value,
        ),
        DecisionCheck(
            "high_forecast_no_grid_import",
            not (
                inputs.is_load_on
                and inputs.high_forecast_grid_import_active
            ),
        ),
        DecisionCheck(
            "running_grid_import_limit",
            not (
                inputs.is_load_on
                and inputs.grid_import_w is not None
                and inputs.grid_import_w > inputs.grid_import_limit_w
                and inputs.grid_import_shutdown_allowed
                and not _minimum_runtime_overrides_grid(inputs)
            ),
        ),
        DecisionCheck(
            "minimum_off_time",
            not inputs.min_off_active
            or inputs.must_force_minimum_runtime
        ),
        DecisionCheck(
            "grid_import_cooldown",
            not inputs.grid_import_cooldown_active
            or _minimum_runtime_overrides_grid(inputs),
        ),
        DecisionCheck("runtime_remaining", inputs.runtime_remaining_minutes > 0),
        DecisionCheck(
            "battery_priority_after_runtime",
            not inputs.battery_priority_after_runtime,
        ),
        DecisionCheck(
            "export_guard",
            inputs.export_guard_run_available,
        ),
        DecisionCheck(
            "solar_surplus",
            inputs.effective_solar_surplus_w >= inputs.load_power_w,
        ),
        DecisionCheck("minimum_on_time", inputs.min_on_active),
        DecisionCheck(
            "forecast_assisted_run",
            inputs.forecast_assisted_run_available,
        ),
        DecisionCheck("must_force_runtime", inputs.must_force_minimum_runtime),
        DecisionCheck(
            "minimum_runtime_grid_override",
            not inputs.projected_grid_import_exceeds_limit
            or inputs.min_runtime_grid_override,
        ),
        DecisionCheck(
            "projected_grid_import_limit",
            not inputs.projected_grid_import_exceeds_limit
            or inputs.min_runtime_grid_override,
        ),
        DecisionCheck(
            "minimum_runtime_battery_override",
            inputs.battery_can_support_forced_runtime
            or _minimum_runtime_overrides_battery(inputs),
        ),
        DecisionCheck("wait_for_forecast", inputs.should_wait_for_forecast),
    )


def _build_summary(inputs: DecisionInputs, should_run: bool, reason: str) -> str:
    """Return a compact human-readable decision summary."""
    if reason == DECISION_MINIMUM_ON_TIME_ACTIVE:
        return "min_on: keeping load on"
    if reason == DECISION_MINIMUM_OFF_TIME_ACTIVE:
        return "min_off: waiting"
    if reason == DECISION_GRID_IMPORT_LIMIT_EXCEEDED:
        if inputs.grid_import_cooldown_active:
            return "grid_import: cooldown active"
        if inputs.is_load_on and inputs.high_forecast_grid_import_active:
            return "high_grid_import: import above tolerance"
        if inputs.is_load_on:
            return "grid_import: current import above limit"
        return "grid_import: projected import above start limit"
    if reason == DECISION_BATTERY_PROTECTED:
        return "battery: protected"
    if reason == DECISION_BATTERY_PRIORITY:
        return "battery_priority: reserving forecast for battery"
    if reason == DECISION_MINIMUM_RUNTIME_REQUIRED:
        if inputs.min_off_active:
            return "runtime_force: minimum runtime overrides min_off"
        if inputs.projected_grid_import_exceeds_limit:
            return "runtime_force: minimum runtime overrides grid limit"
        if not inputs.battery_can_support_forced_runtime:
            return "runtime_force: minimum runtime overrides battery protection"
        return "runtime_force: minimum runtime required"
    if reason == DECISION_EXPORT_GUARD:
        return "export_guard: preventing forecast clipping"
    if reason == DECISION_SOLAR_SURPLUS_AVAILABLE:
        return "solar: surplus covers load"
    if reason == DECISION_FORECAST_ASSISTED_RUN:
        return "forecast_run: high forecast with partial surplus"
    if reason == DECISION_LOW_FORECAST_ASSISTED_RUN:
        return "low_assist: partial solar with forecast support"
    if reason == DECISION_FORECAST_WAIT:
        return "forecast: waiting for forecast"
    if reason == DECISION_LOW_FORECAST_WAIT:
        return "low_wait: waiting for better low-day solar"
    if reason == DECISION_MINIMUM_RUNTIME_REACHED:
        return "runtime_met: minimum runtime reached"
    if reason == DECISION_TIME_WINDOW_BLOCKED:
        return "time_window: outside allowed running time"
    if reason == DECISION_AUTOMATION_PAUSED:
        return "paused: automatic control is paused"
    if reason == DECISION_MISSING_REQUIRED_SENSOR:
        return "missing_sensor: required input unavailable"
    action = "run" if should_run else "wait"
    return f"{action}: waiting for better conditions"


def _minimum_runtime_overrides_grid(inputs: DecisionInputs) -> bool:
    """Return whether minimum runtime may ignore grid import protection."""
    return inputs.must_force_minimum_runtime and inputs.min_runtime_grid_override


def _minimum_runtime_overrides_battery(inputs: DecisionInputs) -> bool:
    """Return whether minimum runtime may ignore battery protection."""
    return inputs.must_force_minimum_runtime and inputs.min_runtime_battery_override
