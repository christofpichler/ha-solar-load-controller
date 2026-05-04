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
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_WAIT,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_MINIMUM_OFF_TIME_ACTIVE,
    DECISION_MINIMUM_ON_TIME_ACTIVE,
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
        min_on_active=False,
        min_on_remaining_minutes=0.0,
        min_off_active=False,
        min_off_remaining_minutes=0.0,
        export_guard_run_available=False,
        battery_headroom_kwh=4.0,
        battery_charge_required_kwh=4.444,
        high_forecast_post_runtime_battery_charge_required_kwh=4.2,
        forecast_excess_after_battery_kwh=-1.0,
        forecast_assisted_run_available=False,
        high_forecast_grid_import_active=False,
        high_forecast_grid_import_duration_seconds=0.0,
        high_forecast_grid_import_shutdown_delay_seconds=15.0,
        must_force_minimum_runtime=False,
        min_runtime_grid_override=True,
        projected_grid_import_exceeds_limit=False,
        battery_can_support_forced_runtime=True,
        should_wait_for_forecast=False,
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
        self.assertEqual(result.reason, DECISION_FORECAST_WAIT)

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


if __name__ == "__main__":
    unittest.main()
