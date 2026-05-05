"""Tests for low-forecast runtime helpers."""

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

from custom_components.solar_load_controller.low_mode import (
    assisted_run_surplus_threshold_w,
    should_allow_assisted_run,
    should_keep_assisted_run,
    forecast_wait_threshold_kwh,
    runtime_pressure,
    runtime_wait_buffer_minutes,
    should_wait_for_forecast,
    should_force_runtime,
)


class LowModeHelperTest(unittest.TestCase):
    """Unit tests for low-mode runtime pressure helpers."""

    def test_runtime_pressure_uses_light_exponential_curve(self) -> None:
        """Later day progress should increase pressure non-linearly."""
        self.assertEqual(round(runtime_pressure(0.5, exponent=1.6), 3), 0.33)

    def test_wait_buffer_grows_with_day_progress(self) -> None:
        """Low mode should tolerate less slack later in the day."""
        early_buffer = runtime_wait_buffer_minutes(
            180.0,
            0.0,
            min_ratio=0.15,
            max_ratio=0.75,
            exponent=1.6,
        )
        late_buffer = runtime_wait_buffer_minutes(
            180.0,
            1.0,
            min_ratio=0.15,
            max_ratio=0.75,
            exponent=1.6,
        )

        self.assertEqual(early_buffer, 27.0)
        self.assertEqual(late_buffer, 135.0)

    def test_force_runtime_when_slack_falls_below_buffer(self) -> None:
        """Low mode should force once remaining slack gets too small."""
        self.assertTrue(
            should_force_runtime(
                runtime_remaining_minutes=90.0,
                minutes_until_finish=180.0,
                min_daily_runtime_minutes=180.0,
                progress=1.0,
                min_ratio=0.15,
                max_ratio=0.75,
                exponent=1.6,
            )
        )

    def test_keep_waiting_when_early_day_slack_is_still_large(self) -> None:
        """Low mode should stay defensive while enough slack still exists."""
        self.assertFalse(
            should_force_runtime(
                runtime_remaining_minutes=90.0,
                minutes_until_finish=180.0,
                min_daily_runtime_minutes=180.0,
                progress=0.0,
                min_ratio=0.15,
                max_ratio=0.75,
                exponent=1.6,
            )
        )

    def test_forecast_wait_threshold_rises_with_pressure(self) -> None:
        """Later low-mode waiting should require a stronger next-hour forecast."""
        self.assertEqual(
            forecast_wait_threshold_kwh(
                450.0,
                60.0,
                0.0,
                min_multiplier=1.0,
                max_multiplier=1.75,
            ),
            0.45,
        )
        self.assertEqual(
            forecast_wait_threshold_kwh(
                450.0,
                60.0,
                1.0,
                min_multiplier=1.0,
                max_multiplier=1.75,
            ),
            0.787,
        )

    def test_low_mode_waits_early_when_forecast_is_good_enough(self) -> None:
        """Early low mode may still wait if enough slack and next-hour forecast exist."""
        self.assertTrue(
            should_wait_for_forecast(
                forecast_remaining_kwh=1.8,
                forecast_next_hour_kwh=0.5,
                slack_minutes=180.0,
                wait_buffer_minutes=27.0,
                load_power_w=450.0,
                wait_minutes=60.0,
                pressure=0.0,
                min_multiplier=1.0,
                max_multiplier=1.75,
            )
        )

    def test_low_mode_stops_waiting_when_time_pressure_is_high(self) -> None:
        """Later low mode should stop waiting when slack falls below the buffer."""
        self.assertFalse(
            should_wait_for_forecast(
                forecast_remaining_kwh=1.8,
                forecast_next_hour_kwh=0.9,
                slack_minutes=60.0,
                wait_buffer_minutes=90.0,
                load_power_w=450.0,
                wait_minutes=60.0,
                pressure=1.0,
                min_multiplier=1.0,
                max_multiplier=1.75,
            )
        )

    def test_assisted_surplus_threshold_drops_with_pressure(self) -> None:
        """Later low mode may accept a smaller partial solar contribution."""
        self.assertEqual(
            assisted_run_surplus_threshold_w(
                450.0,
                0.0,
                early_ratio=0.85,
                late_ratio=0.35,
            ),
            382.5,
        )
        self.assertEqual(
            assisted_run_surplus_threshold_w(
                450.0,
                1.0,
                early_ratio=0.85,
                late_ratio=0.35,
            ),
            157.5,
        )

    def test_assisted_run_requires_partial_solar_and_good_forecast(self) -> None:
        """Low assisted starts should still require solar contribution and forecast support."""
        self.assertTrue(
            should_allow_assisted_run(
                effective_solar_surplus_w=250.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
                required_surplus_w=200.0,
            )
        )
        self.assertFalse(
            should_allow_assisted_run(
                effective_solar_surplus_w=180.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
                required_surplus_w=200.0,
            )
        )
        self.assertFalse(
            should_allow_assisted_run(
                effective_solar_surplus_w=250.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="discharging",
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
                required_surplus_w=200.0,
            )
        )

    def test_assisted_run_hold_keeps_recent_start_alive(self) -> None:
        """Low assisted runs should hold briefly if grid stays clean and forecast still looks good."""
        self.assertTrue(
            should_keep_assisted_run(
                minutes_since_turn_on=1.2,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=False,
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
            )
        )

    def test_assisted_run_hold_ends_after_window_or_grid_limit(self) -> None:
        """Assisted hold should stop once the hold window passes or grid gets too high."""
        self.assertFalse(
            should_keep_assisted_run(
                minutes_since_turn_on=3.1,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=False,
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
            )
        )
        self.assertFalse(
            should_keep_assisted_run(
                minutes_since_turn_on=1.2,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=True,
                forecast_next_hour_kwh=0.8,
                forecast_wait_threshold_kwh=0.7,
            )
        )


if __name__ == "__main__":
    unittest.main()
