"""Tests for high-forecast restart behavior."""

from __future__ import annotations

import sys
import types
import unittest
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

from custom_components.solar_load_controller.high_mode import (
    allow_post_runtime_export_guard_restart,
    export_guard_run_available,
    should_prioritize_battery_after_runtime,
)


def _export_guard_inputs(**overrides):
    base = dict(
        forecast_day_class="high",
        high_forecast_day_class="high",
        is_load_on=False,
        grid_import_w=0.0,
        grid_import_no_grid_tolerance_w=25.0,
        high_forecast_grid_import_active=False,
        should_prioritize_battery=False,
        allow_post_runtime_restart=True,
        available_surplus_w=500.0,
        usable_battery_charge_w=0.0,
        load_power_w=400.0,
        battery_power_state="neutral",
        pv_current_power_w=500.0,
        forecast_remaining_kwh=2.0,
        battery_charge_required_kwh=1.0,
        curtailment_headroom_ratio=0.8,
    )
    base.update(overrides)
    return base


def _battery_priority_inputs(**overrides):
    base = dict(
        forecast_day_class="high",
        high_forecast_day_class="high",
        runtime_remaining_minutes=0.0,
        battery_headroom_kwh=1.0,
        battery_charge_required_kwh=1.0,
        battery_soc=50.0,
        battery_power_state="charging",
        forecast_remaining_kwh=1.5,
        household_reserve_kwh=0.3,
        time_priority_buffer_kwh=0.2,
        battery_target_soc=99.0,
        battery_headroom_min_kwh=0.05,
    )
    base.update(overrides)
    return base


class HighModeRestartTest(unittest.TestCase):
    """Unit tests for late high-mode restart gating."""

    def test_real_export_still_allows_post_runtime_restart(self) -> None:
        """Actual export should remain enough even after minimum runtime."""
        self.assertTrue(
            allow_post_runtime_export_guard_restart(
                is_load_on=False,
                runtime_remaining_minutes=0.0,
                available_surplus_w=450.0,
                effective_solar_surplus_w=450.0,
                load_power_w=400.0,
                forecast_next_hour_kwh=0.2,
                restart_surplus_margin_w=75.0,
                next_hour_ratio=1.5,
            )
        )

    def test_borderline_battery_charge_restart_is_blocked(self) -> None:
        """A tiny battery-charging margin should not restart late in the day."""
        self.assertFalse(
            allow_post_runtime_export_guard_restart(
                is_load_on=False,
                runtime_remaining_minutes=0.0,
                available_surplus_w=0.0,
                effective_solar_surplus_w=404.0,
                load_power_w=400.0,
                forecast_next_hour_kwh=0.9,
                restart_surplus_margin_w=75.0,
                next_hour_ratio=1.5,
            )
        )

    def test_weak_next_hour_forecast_blocks_post_runtime_restart(self) -> None:
        """Late restarts should stop once the next-hour forecast gets too weak."""
        self.assertFalse(
            allow_post_runtime_export_guard_restart(
                is_load_on=False,
                runtime_remaining_minutes=0.0,
                available_surplus_w=0.0,
                effective_solar_surplus_w=520.0,
                load_power_w=400.0,
                forecast_next_hour_kwh=0.5,
                restart_surplus_margin_w=75.0,
                next_hour_ratio=1.5,
            )
        )

    def test_strong_next_hour_forecast_can_still_restart(self) -> None:
        """A strong next-hour forecast may still justify a restart."""
        self.assertTrue(
            allow_post_runtime_export_guard_restart(
                is_load_on=False,
                runtime_remaining_minutes=0.0,
                available_surplus_w=0.0,
                effective_solar_surplus_w=520.0,
                load_power_w=400.0,
                forecast_next_hour_kwh=0.9,
                restart_surplus_margin_w=75.0,
                next_hour_ratio=1.5,
            )
        )


class ExportGuardRunAvailableTest(unittest.TestCase):
    """Unit tests for the high-mode export-guard run gate."""

    def test_strong_surplus_allows_run(self) -> None:
        self.assertTrue(export_guard_run_available(**_export_guard_inputs()))

    def test_non_high_day_class_blocks_run(self) -> None:
        self.assertFalse(
            export_guard_run_available(**_export_guard_inputs(forecast_day_class="mid"))
        )

    def test_grid_import_above_tolerance_blocks_off_load(self) -> None:
        self.assertFalse(
            export_guard_run_available(
                **_export_guard_inputs(
                    is_load_on=False,
                    grid_import_w=100.0,
                    available_surplus_w=0.0,
                )
            )
        )

    def test_battery_priority_blocks_run(self) -> None:
        self.assertFalse(
            export_guard_run_available(
                **_export_guard_inputs(should_prioritize_battery=True)
            )
        )

    def test_battery_charge_fallback_allows_run_when_charging(self) -> None:
        self.assertTrue(
            export_guard_run_available(
                **_export_guard_inputs(
                    available_surplus_w=0.0,
                    usable_battery_charge_w=500.0,
                    battery_power_state="charging",
                )
            )
        )

    def test_post_runtime_restart_blocked_when_disallowed(self) -> None:
        self.assertFalse(
            export_guard_run_available(
                **_export_guard_inputs(
                    available_surplus_w=0.0,
                    allow_post_runtime_restart=False,
                )
            )
        )

    def test_solarbank_guard_blocks_when_battery_discharging_and_pv_low(self) -> None:
        """The Solarbank guard must block forecast-headroom runs in that state."""
        self.assertFalse(
            export_guard_run_available(
                **_export_guard_inputs(
                    available_surplus_w=0.0,
                    usable_battery_charge_w=0.0,
                    battery_power_state="discharging",
                    pv_current_power_w=100.0,
                    load_power_w=400.0,
                    forecast_remaining_kwh=5.0,
                )
            )
        )

    def test_solarbank_guard_not_triggered_when_pv_above_load(self) -> None:
        self.assertTrue(
            export_guard_run_available(
                **_export_guard_inputs(
                    available_surplus_w=0.0,
                    usable_battery_charge_w=0.0,
                    battery_power_state="discharging",
                    pv_current_power_w=600.0,
                    load_power_w=400.0,
                    forecast_remaining_kwh=5.0,
                )
            )
        )

    def test_missing_forecast_and_no_surplus_blocks_run(self) -> None:
        self.assertFalse(
            export_guard_run_available(
                **_export_guard_inputs(
                    available_surplus_w=0.0,
                    usable_battery_charge_w=0.0,
                    forecast_remaining_kwh=None,
                )
            )
        )


class ShouldPrioritizeBatteryAfterRuntimeTest(unittest.TestCase):
    """Unit tests for late-day battery priority gating."""

    def test_non_high_day_class_disables_priority(self) -> None:
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(forecast_day_class="low")
            )
        )
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(forecast_day_class="mid")
            )
        )

    def test_runtime_outstanding_disables_priority(self) -> None:
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(runtime_remaining_minutes=10.0)
            )
        )

    def test_battery_nearly_full_disables_priority(self) -> None:
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(
                    battery_headroom_kwh=0.02,
                    battery_headroom_min_kwh=0.05,
                )
            )
        )

    def test_soc_above_target_disables_priority(self) -> None:
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(battery_soc=99.0)
            )
        )

    def test_missing_soc_falls_back_to_battery_power_state(self) -> None:
        self.assertTrue(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(battery_soc=None, battery_power_state="charging")
            )
        )
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(battery_soc=None, battery_power_state="neutral")
            )
        )

    def test_missing_forecast_keeps_priority(self) -> None:
        self.assertTrue(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(forecast_remaining_kwh=None)
            )
        )

    def test_forecast_sufficient_releases_priority(self) -> None:
        self.assertFalse(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(forecast_remaining_kwh=5.0)
            )
        )

    def test_forecast_insufficient_keeps_priority(self) -> None:
        self.assertTrue(
            should_prioritize_battery_after_runtime(
                **_battery_priority_inputs(
                    forecast_remaining_kwh=0.5,
                    battery_charge_required_kwh=1.0,
                    household_reserve_kwh=0.4,
                    time_priority_buffer_kwh=0.2,
                )
            )
        )


if __name__ == "__main__":
    unittest.main()
