"""Tests for the pure Solar Load Controller decision engine."""

from __future__ import annotations

import unittest
import sys
import types
from dataclasses import replace
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS_DIR = PROJECT_DIR / "custom_components"
PACKAGE_NAME = "custom_components.solar_load_controller"
PACKAGE_DIR = CUSTOM_COMPONENTS_DIR / "solar_load_controller"

custom_components = sys.modules.setdefault(
    "custom_components", types.ModuleType("custom_components")
)
custom_components.__path__ = [str(CUSTOM_COMPONENTS_DIR)]
solar_load_controller = sys.modules.setdefault(
    PACKAGE_NAME, types.ModuleType(PACKAGE_NAME)
)
solar_load_controller.__path__ = [str(PACKAGE_DIR)]
setattr(custom_components, "solar_load_controller", solar_load_controller)

from custom_components.solar_load_controller.const import (
    DECISION_BATTERY_PROTECTED,
    DECISION_BATTERY_PRIORITY,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_FORECAST_WAIT,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_LOW_FORECAST_WAIT,
    DECISION_MISSING_REQUIRED_SENSOR,
    DECISION_MINIMUM_OFF_TIME_ACTIVE,
    DECISION_MINIMUM_ON_TIME_ACTIVE,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
)
from custom_components.solar_load_controller.decision_engine import (
    DecisionInputs,
    evaluate_decision,
)


def make_inputs(**overrides: object) -> DecisionInputs:
    """Return a default decision input set suitable for tests."""
    base = DecisionInputs(
        is_load_on=False,
        automation_paused=False,
        inside_time_window=True,
        missing_required_grid_sensor_value=False,
        grid_import_w=100.0,
        grid_export_w=0.0,
        grid_import_limit_w=800.0,
        grid_import_start_limit_w=750.0,
        grid_import_over_limit_duration_seconds=0.0,
        grid_import_shutdown_delay_seconds=60.0,
        grid_import_shutdown_allowed=False,
        grid_import_cooldown_active=False,
        grid_import_cooldown_remaining_seconds=0.0,
        projected_grid_import_w=550.0,
        projected_grid_import_formula="current_grid_import - current_grid_export + load_power",
        available_surplus_w=0.0,
        effective_solar_surplus_w=0.0,
        load_power_w=450.0,
        runtime_today_minutes=0.0,
        runtime_remaining_minutes=180.0,
        required_remaining_energy_kwh=1.35,
        minutes_until_finish=360.0,
        low_mode_runtime_progress=0.0,
        low_mode_runtime_pressure=0.0,
        low_mode_runtime_slack_minutes=180.0,
        low_mode_runtime_wait_buffer_minutes=27.0,
        low_mode_forecast_wait_threshold_kwh=0.45,
        low_mode_assisted_surplus_threshold_w=382.5,
        low_mode_assisted_effective_surplus_threshold_w=382.5,
        low_mode_assisted_start_surplus_w=0.0,
        low_mode_assisted_strength_ratio=0.0,
        low_mode_assisted_priority=0.0,
        low_mode_assisted_forecast_threshold_kwh=0.45,
        min_on_active=False,
        min_on_remaining_minutes=0.0,
        min_off_active=False,
        min_off_remaining_minutes=0.0,
        export_guard_run_available=False,
        battery_priority_after_runtime=False,
        battery_headroom_kwh=4.0,
        battery_charge_required_kwh=4.444,
        high_forecast_post_runtime_battery_charge_required_kwh=4.2,
        high_mode_base_household_load_w=250.0,
        high_mode_household_reserve_margin_percent=20.0,
        high_mode_household_reserve_kwh=2.4,
        forecast_excess_after_battery_kwh=-1.0,
        forecast_assisted_run_available=False,
        high_forecast_grid_import_active=False,
        high_forecast_grid_import_duration_seconds=0.0,
        high_forecast_grid_import_shutdown_delay_seconds=15.0,
        runtime_force_latched=False,
        must_force_minimum_runtime=False,
        min_runtime_battery_override=True,
        min_runtime_grid_override=True,
        projected_grid_import_exceeds_limit=False,
        battery_can_support_forced_runtime=True,
        should_wait_for_forecast=False,
        mid_mode_assisted_surplus_threshold_w=247.5,
        mid_mode_solar_surplus_w=0.0,
        mid_mode_forecast_wait_threshold_kwh=0.3375,
        battery_mode="preserve",
        battery_soc=5.0,
        battery_power_w=0.0,
        battery_power_state="neutral",
        forecast_today_kwh=1.0,
        forecast_remaining_today_kwh=0.0,
        forecast_next_hour_kwh=0.0,
        forecast_kwh_per_kwp=0.5,
        forecast_day_class="low",
    )
    return replace(base, **overrides)


class DecisionEngineTest(unittest.TestCase):
    """Unit tests for decision priority and debug behavior."""

    def test_solar_surplus_runs_load(self) -> None:
        """Solar surplus should run when it covers the load."""
        result = evaluate_decision(make_inputs(available_surplus_w=500.0))

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_SOLAR_SURPLUS_AVAILABLE)

    def test_waits_for_forecast_when_runtime_not_urgent(self) -> None:
        """Good forecast should keep the load off when runtime is not urgent."""
        result = evaluate_decision(make_inputs(should_wait_for_forecast=True))

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_LOW_FORECAST_WAIT)

    def test_missing_sensor_beats_time_window_for_startup_diagnostics(self) -> None:
        """Missing required input should be visible even outside the time window."""
        result = evaluate_decision(
            make_inputs(
                inside_time_window=False,
                missing_required_grid_sensor_value=True,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MISSING_REQUIRED_SENSOR)

    def test_forecast_assisted_run_uses_low_assist_reason(self) -> None:
        """Controlled low-mode assisted starts should use the low_assist reason."""
        result = evaluate_decision(
            make_inputs(
                forecast_assisted_run_available=True,
                should_wait_for_forecast=True,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_LOW_FORECAST_ASSISTED_RUN)

    def test_export_guard_runs_before_runtime_is_due(self) -> None:
        """High forecast export guard should start the load early."""
        result = evaluate_decision(
            make_inputs(
                export_guard_run_available=True,
                should_wait_for_forecast=True,
                battery_soc=20.0,
                battery_power_state="discharging",
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_EXPORT_GUARD)

    def test_export_guard_can_run_after_minimum_runtime(self) -> None:
        """Export guard may continue after minimum runtime is met."""
        result = evaluate_decision(
            make_inputs(
                runtime_remaining_minutes=0.0,
                export_guard_run_available=True,
                forecast_excess_after_battery_kwh=1.2,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_EXPORT_GUARD)

    def test_runtime_met_beats_export_guard_when_no_real_extra_surplus_exists(self) -> None:
        """Export guard should not self-sustain purely from the already running load."""
        result = evaluate_decision(
            make_inputs(
                is_load_on=True,
                runtime_remaining_minutes=0.0,
                export_guard_run_available=False,
                battery_priority_after_runtime=False,
                available_surplus_w=0.0,
                effective_solar_surplus_w=400.0,
                forecast_excess_after_battery_kwh=3.0,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REACHED)

    def test_battery_priority_replaces_runtime_met_after_runtime(self) -> None:
        """High-mode battery reservation should expose its own reason after runtime is met."""
        result = evaluate_decision(
            make_inputs(
                runtime_remaining_minutes=0.0,
                battery_priority_after_runtime=True,
                export_guard_run_available=False,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_BATTERY_PRIORITY)
        self.assertEqual(
            result.summary,
            "battery_priority: reserving forecast for battery",
        )

    def test_high_forecast_grid_import_turns_running_load_off(self) -> None:
        """High forecast mode should stop after min_on when grid import starts."""
        result = evaluate_decision(
            make_inputs(
                is_load_on=True,
                high_forecast_grid_import_active=True,
                export_guard_run_available=True,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_GRID_IMPORT_LIMIT_EXCEEDED)
        self.assertEqual(result.summary, "high_grid_import: import above tolerance")

    def test_min_on_blocks_high_forecast_grid_import_shutdown(self) -> None:
        """Min on should avoid rapid high-mode off/on switching."""
        result = evaluate_decision(
            make_inputs(
                is_load_on=True,
                min_on_active=True,
                high_forecast_grid_import_active=True,
                export_guard_run_available=True,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_ON_TIME_ACTIVE)

    def test_grid_limit_blocks_forced_runtime_without_override(self) -> None:
        """Grid limit should block forced runtime when override is disabled."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                min_runtime_grid_override=False,
                projected_grid_import_exceeds_limit=True,
                projected_grid_import_w=1200.0,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_GRID_IMPORT_LIMIT_EXCEEDED)

    def test_minimum_runtime_overrides_grid_limit_when_enabled(self) -> None:
        """Forced runtime may exceed grid limits when override is enabled."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                min_runtime_grid_override=True,
                projected_grid_import_exceeds_limit=True,
                projected_grid_import_w=2000.0,
                battery_can_support_forced_runtime=False,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)
        self.assertEqual(
            result.summary,
            "runtime_force: minimum runtime overrides grid limit",
        )

    def test_battery_protection_blocks_forced_runtime_without_battery_override(self) -> None:
        """Battery protection should still block forced runtime when its override is disabled."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=False,
                min_runtime_battery_override=False,
                min_runtime_grid_override=True,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_BATTERY_PROTECTED)

    def test_minimum_runtime_may_override_battery_protection_separately(self) -> None:
        """Battery override should allow forced runtime without needing grid override changes."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=False,
                min_runtime_battery_override=True,
                min_runtime_grid_override=False,
                projected_grid_import_exceeds_limit=False,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)
        self.assertEqual(
            result.summary,
            "runtime_force: minimum runtime overrides battery protection",
        )

    def test_minimum_runtime_overrides_min_off(self) -> None:
        """Forced runtime should override min_off to avoid missing the target."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                min_off_active=True,
                min_off_remaining_minutes=8.0,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)
        self.assertEqual(
            result.summary,
            "runtime_force: minimum runtime overrides min_off",
        )

    def test_min_off_blocks_non_urgent_start(self) -> None:
        """Min off should still block normal non-urgent starts."""
        result = evaluate_decision(
            make_inputs(
                min_off_active=True,
                min_off_remaining_minutes=8.0,
                must_force_minimum_runtime=False,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_OFF_TIME_ACTIVE)

    def test_min_off_blocks_high_forecast_export_guard_start(self) -> None:
        """Min off should avoid rapid high-mode restarts."""
        result = evaluate_decision(
            make_inputs(
                min_off_active=True,
                min_off_remaining_minutes=8.0,
                export_guard_run_available=True,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_OFF_TIME_ACTIVE)

    def test_grid_import_cooldown_blocks_high_forecast_export_guard_restart(self) -> None:
        """Grid-import cooldown should block export-guard restarts."""
        result = evaluate_decision(
            make_inputs(
                grid_import_cooldown_active=True,
                grid_import_cooldown_remaining_seconds=540.0,
                export_guard_run_available=True,
            )
        )

        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_GRID_IMPORT_LIMIT_EXCEEDED)

    def test_debug_summary_is_stable_for_grid_projection(self) -> None:
        """Grid import debug summary should not include changing watt values."""
        result = evaluate_decision(
            make_inputs(
                projected_grid_import_exceeds_limit=True,
                projected_grid_import_w=833.0,
                min_runtime_grid_override=False,
                must_force_minimum_runtime=True,
            )
        )

        self.assertEqual(
            result.summary,
            "grid_import: projected import above start limit",
        )

    # --- Mid-mode / force-path priority regression (Codex Fix 1) ---

    def test_must_force_runtime_wins_when_forecast_assisted_not_set(self) -> None:
        """On a deadline mid-day the engine must produce runtime_force, not forecast_run.

        The coordinator is responsible for setting forecast_assisted_run_available=False
        when _must_force_minimum_runtime is True.  This test verifies the engine
        picks runtime_force when the coordinator has done its job correctly.
        """
        result = evaluate_decision(
            make_inputs(
                forecast_day_class="mid",
                forecast_assisted_run_available=False,   # coordinator cleared this
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=True,
                projected_grid_import_exceeds_limit=False,
            )
        )

        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)

    def test_forecast_assisted_run_suppresses_force_runtime_in_engine(self) -> None:
        """Engine priority: forecast_assisted_run_available beats must_force_minimum_runtime.

        This documents WHY the coordinator must never set forecast_assisted_run_available=True
        when must_force_minimum_runtime is True: the engine would pick forecast_run
        instead of runtime_force, and the force-latch would not activate.

        The coordinator fix (checking _must_force_minimum_runtime inside
        _mid_forecast_assisted_run_available) prevents this combination from
        ever reaching the engine.
        """
        result = evaluate_decision(
            make_inputs(
                forecast_day_class="mid",
                forecast_assisted_run_available=True,    # coordinator must NOT do this
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=True,
            )
        )

        # Engine picks forecast_run — load runs but the force-latch does NOT activate.
        # This is the wrong outcome on a deadline day, which is why the coordinator
        # must guard against this combination.
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_FORECAST_ASSISTED_RUN)


if __name__ == "__main__":
    unittest.main()
