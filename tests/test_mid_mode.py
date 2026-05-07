"""Tests for mid-forecast runtime helpers."""

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

from custom_components.solar_load_controller.mid_mode import (
    MID_FORECAST_ASSISTED_SURPLUS_RATIO,
    MID_FORECAST_WAIT_NEXT_HOUR_RATIO,
    should_allow_mid_mode_assisted_run,
    should_wait_for_mid_forecast,
)


LOAD_W = 450.0
THRESHOLD_W = round(LOAD_W * MID_FORECAST_ASSISTED_SURPLUS_RATIO, 1)  # 247.5 W


class TestShouldAllowMidModeAssistedRun(unittest.TestCase):
    """Tests for should_allow_mid_mode_assisted_run."""

    def _call(self, **kwargs):
        defaults = dict(
            effective_solar_surplus_w=THRESHOLD_W,
            load_power_w=LOAD_W,
            battery_power_state="idle",
            projected_grid_import_exceeds_limit=False,
        )
        defaults.update(kwargs)
        return should_allow_mid_mode_assisted_run(**defaults)

    # --- Positive cases ---

    def test_exactly_at_threshold_allows_run(self):
        self.assertTrue(self._call(effective_solar_surplus_w=THRESHOLD_W))

    def test_above_threshold_allows_run(self):
        self.assertTrue(self._call(effective_solar_surplus_w=THRESHOLD_W + 50))

    def test_battery_idle_allows_run(self):
        self.assertTrue(self._call(battery_power_state="idle"))

    def test_battery_charging_allows_run(self):
        self.assertTrue(self._call(battery_power_state="charging"))

    # --- Blocking cases ---

    def test_below_threshold_blocks_run(self):
        self.assertFalse(self._call(effective_solar_surplus_w=THRESHOLD_W - 1))

    def test_zero_surplus_blocks_run(self):
        self.assertFalse(self._call(effective_solar_surplus_w=0.0))

    def test_negative_surplus_blocks_run(self):
        self.assertFalse(self._call(effective_solar_surplus_w=-100.0))

    def test_battery_discharging_blocks_run(self):
        self.assertFalse(
            self._call(
                effective_solar_surplus_w=THRESHOLD_W + 100,
                battery_power_state="discharging",
            )
        )

    def test_projected_grid_import_exceeds_limit_blocks_run(self):
        self.assertFalse(
            self._call(
                effective_solar_surplus_w=THRESHOLD_W + 100,
                projected_grid_import_exceeds_limit=True,
            )
        )

    def test_zero_load_power_blocks_run(self):
        self.assertFalse(self._call(load_power_w=0.0))

    # --- Custom surplus_ratio ---

    def test_custom_ratio_lower_threshold(self):
        # ratio=0.3 → threshold = 450 * 0.3 = 135 W
        self.assertTrue(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=135.0,
                load_power_w=LOAD_W,
                battery_power_state="idle",
                projected_grid_import_exceeds_limit=False,
                surplus_ratio=0.3,
            )
        )

    def test_custom_ratio_higher_threshold(self):
        # ratio=0.9 → threshold = 450 * 0.9 = 405 W; 380 W is not enough
        self.assertFalse(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=380.0,
                load_power_w=LOAD_W,
                battery_power_state="idle",
                projected_grid_import_exceeds_limit=False,
                surplus_ratio=0.9,
            )
        )

    def test_large_installation_scales_correctly(self):
        # 5000 W load, 55% ratio → 2750 W threshold
        self.assertTrue(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=2750.0,
                load_power_w=5000.0,
                battery_power_state="idle",
                projected_grid_import_exceeds_limit=False,
            )
        )
        self.assertFalse(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=2749.0,
                load_power_w=5000.0,
                battery_power_state="idle",
                projected_grid_import_exceeds_limit=False,
            )
        )


class TestShouldWaitForMidForecast(unittest.TestCase):
    """Tests for should_wait_for_mid_forecast."""

    # threshold_kwh = 450 * 0.75 / 1000 = 0.3375 kWh
    THRESHOLD_KWH = round(LOAD_W * MID_FORECAST_WAIT_NEXT_HOUR_RATIO / 1000, 4)
    WAIT_MINUTES = 60.0

    def _call(self, **kwargs):
        defaults = dict(
            forecast_remaining_kwh=2.0,
            forecast_next_hour_kwh=self.THRESHOLD_KWH,
            slack_minutes=self.WAIT_MINUTES + 1,
            load_power_w=LOAD_W,
            wait_minutes=self.WAIT_MINUTES,
        )
        defaults.update(kwargs)
        return should_wait_for_mid_forecast(**defaults)

    # --- Positive: should wait ---

    def test_exactly_at_threshold_waits(self):
        self.assertTrue(self._call())

    def test_above_threshold_waits(self):
        self.assertTrue(self._call(forecast_next_hour_kwh=self.THRESHOLD_KWH + 0.1))

    def test_plenty_of_slack_waits(self):
        self.assertTrue(self._call(slack_minutes=120.0))

    # --- Negative: should not wait ---

    def test_no_remaining_forecast_does_not_wait(self):
        self.assertFalse(self._call(forecast_remaining_kwh=None))

    def test_no_next_hour_forecast_does_not_wait(self):
        """Mid mode never waits when next-hour data is missing (unlike low mode)."""
        self.assertFalse(self._call(forecast_next_hour_kwh=None))

    def test_below_threshold_does_not_wait(self):
        self.assertFalse(self._call(forecast_next_hour_kwh=self.THRESHOLD_KWH - 0.01))

    def test_zero_next_hour_does_not_wait(self):
        self.assertFalse(self._call(forecast_next_hour_kwh=0.0))

    def test_no_slack_does_not_wait(self):
        self.assertFalse(self._call(slack_minutes=0.0))

    def test_slack_exactly_at_wait_minutes_does_not_wait(self):
        # slack <= wait_minutes → no wait
        self.assertFalse(self._call(slack_minutes=self.WAIT_MINUTES))

    def test_zero_load_power_does_not_wait(self):
        self.assertFalse(self._call(load_power_w=0.0))

    # --- Key behavioral difference from low mode ---

    def test_mid_does_not_wait_without_next_hour_data_unlike_low(self):
        """Regression: mid must return False when forecast_next_hour_kwh is None,
        even if remaining forecast is available. Low mode returns True in this case.
        """
        result = should_wait_for_mid_forecast(
            forecast_remaining_kwh=3.0,
            forecast_next_hour_kwh=None,
            slack_minutes=180.0,
            load_power_w=LOAD_W,
            wait_minutes=self.WAIT_MINUTES,
        )
        self.assertFalse(result)

    # --- Large installation ---

    def test_large_load_scales_threshold(self):
        # 3000 W load, 0.75 ratio → 2.25 kWh threshold per hour
        self.assertTrue(
            should_wait_for_mid_forecast(
                forecast_remaining_kwh=10.0,
                forecast_next_hour_kwh=2.25,
                slack_minutes=90.0,
                load_power_w=3000.0,
                wait_minutes=60.0,
            )
        )
        self.assertFalse(
            should_wait_for_mid_forecast(
                forecast_remaining_kwh=10.0,
                forecast_next_hour_kwh=2.24,
                slack_minutes=90.0,
                load_power_w=3000.0,
                wait_minutes=60.0,
            )
        )


if __name__ == "__main__":
    unittest.main()
