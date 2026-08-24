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
    MID_FORECAST_ASSISTED_HOLD_MINUTES,
    MID_FORECAST_DISCHARGE_DEADBAND_RATIO,
    MID_FORECAST_DISCHARGE_DEADBAND_W,
    battery_discharge_blocks_assist,
    discharge_deadband_w,
    MID_FORECAST_ASSISTED_SURPLUS_RATIO,
    MID_FORECAST_WAIT_NEXT_HOUR_RATIO,
    forecast_assisted_run_available as mid_mode_forecast_assisted_run_available,
    should_allow_mid_mode_assisted_run,
    should_wait_for_mid_forecast,
)


def _mid_assisted_run_inputs(**overrides):
    base = dict(
        is_currently_assisting=False,
        minutes_since_turn_on=None,
        projected_grid_import_exceeds_limit=False,
        available_surplus_w=100.0,
        effective_solar_surplus_w=300.0,
        load_power_w=450.0,
        battery_power_state="neutral",
        assisted_hold_minutes=MID_FORECAST_ASSISTED_HOLD_MINUTES,
    )
    base.update(overrides)
    return base


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


class TestMidModeConstants(unittest.TestCase):
    """Sanity checks for mid-mode tuning constants."""

    def test_hold_minutes_is_positive(self) -> None:
        """Hold window must be a positive number of minutes."""
        self.assertGreater(MID_FORECAST_ASSISTED_HOLD_MINUTES, 0)

    def test_hold_minutes_is_less_than_one_hour(self) -> None:
        """Hold window should not be absurdly long."""
        self.assertLess(MID_FORECAST_ASSISTED_HOLD_MINUTES, 60)


class MidModeForecastAssistedRunAvailableTest(unittest.TestCase):
    """Unit tests for the mid-mode assisted-run orchestrator."""

    def test_strong_solar_above_load_blocks_assisted_start(self) -> None:
        self.assertFalse(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    available_surplus_w=500.0, load_power_w=450.0
                )
            )
        )

    def test_active_assist_holds_within_window_with_no_grid_import(self) -> None:
        self.assertTrue(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    is_currently_assisting=True,
                    minutes_since_turn_on=1.0,
                )
            )
        )

    def test_grid_import_cancels_hold(self) -> None:
        self.assertFalse(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    is_currently_assisting=True,
                    minutes_since_turn_on=1.0,
                    projected_grid_import_exceeds_limit=True,
                )
            )
        )

    def test_active_assist_releases_after_hold_window(self) -> None:
        # When the hold window has passed, fall through to should_allow logic
        # which requires sufficient solar coverage.
        self.assertFalse(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    is_currently_assisting=True,
                    minutes_since_turn_on=999.0,
                    effective_solar_surplus_w=50.0,
                )
            )
        )

    def test_new_start_when_solar_meets_threshold(self) -> None:
        load_w = 450.0
        threshold_w = load_w * MID_FORECAST_ASSISTED_SURPLUS_RATIO
        self.assertTrue(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    is_currently_assisting=False,
                    load_power_w=load_w,
                    available_surplus_w=threshold_w,
                    effective_solar_surplus_w=threshold_w,
                    battery_power_state="charging",
                )
            )
        )

    def test_discharging_battery_blocks_new_start(self) -> None:
        self.assertFalse(
            mid_mode_forecast_assisted_run_available(
                **_mid_assisted_run_inputs(
                    is_currently_assisting=False,
                    battery_power_state="discharging",
                    effective_solar_surplus_w=400.0,
                )
            )
        )


class MidModeBatteryDischargeCounterfactualTest(unittest.TestCase):
    """Self-inflicted battery discharge must not cancel a running assist."""

    def test_running_load_causing_discharge_does_not_block(self) -> None:
        # Load is on and eats the 500 W that used to charge the battery, so the
        # battery now shows a small discharge. Without the load it would still
        # be charging, so the assist must continue.
        self.assertTrue(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=400.0,
                load_power_w=400.0,
                battery_power_state="discharging",
                projected_grid_import_exceeds_limit=False,
                is_load_on=True,
                battery_power_w=-36.0,
            )
        )

    def test_real_discharge_still_blocks_while_load_runs(self) -> None:
        self.assertFalse(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=400.0,
                load_power_w=400.0,
                battery_power_state="discharging",
                projected_grid_import_exceeds_limit=False,
                is_load_on=True,
                battery_power_w=-800.0,
            )
        )

    def test_discharge_blocks_start_while_load_is_off(self) -> None:
        self.assertFalse(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=400.0,
                load_power_w=400.0,
                battery_power_state="discharging",
                projected_grid_import_exceeds_limit=False,
                is_load_on=False,
                battery_power_w=-36.0,
            )
        )

    def test_grid_protection_still_wins_over_counterfactual(self) -> None:
        self.assertFalse(
            should_allow_mid_mode_assisted_run(
                effective_solar_surplus_w=400.0,
                load_power_w=400.0,
                battery_power_state="discharging",
                projected_grid_import_exceeds_limit=True,
                is_load_on=True,
                battery_power_w=-36.0,
            )
        )


class DischargeDeadbandTest(unittest.TestCase):
    """A few watts below zero is inverter noise, not a reason to stop."""

    def test_floor_applies_to_small_loads(self) -> None:
        self.assertEqual(discharge_deadband_w(400.0), MID_FORECAST_DISCHARGE_DEADBAND_W)

    def test_scales_with_large_loads(self) -> None:
        self.assertEqual(discharge_deadband_w(3000.0), 150.0)

    def test_floor_wins_up_to_break_even(self) -> None:
        break_even = (
            MID_FORECAST_DISCHARGE_DEADBAND_W / MID_FORECAST_DISCHARGE_DEADBAND_RATIO
        )
        self.assertEqual(
            discharge_deadband_w(break_even), MID_FORECAST_DISCHARGE_DEADBAND_W
        )

    def test_zero_or_negative_load_falls_back_to_floor(self) -> None:
        for load_w in (0.0, -100.0):
            with self.subTest(load_power_w=load_w):
                self.assertEqual(
                    discharge_deadband_w(load_w), MID_FORECAST_DISCHARGE_DEADBAND_W
                )


class BatteryDischargeDeadbandTest(unittest.TestCase):
    """Regression cases taken directly from the observed decision log."""

    def _blocks(self, battery_power_w, *, is_load_on=True, load_power_w=400.0):
        return battery_discharge_blocks_assist(
            battery_power_state="discharging",
            is_load_on=is_load_on,
            battery_power_w=battery_power_w,
            load_power_w=load_power_w,
        )

    def test_noise_level_discharge_does_not_block(self) -> None:
        # Compensated results of -4, -8, -13, -14 and -41 W were each enough to
        # cancel a run before the deadband existed.
        for battery_w in (-404.0, -408.0, -413.0, -414.0, -441.0):
            with self.subTest(battery_power_w=battery_w):
                self.assertFalse(self._blocks(battery_w))

    def test_substantial_discharge_still_blocks(self) -> None:
        # -163 W compensated: the battery really is carrying the household.
        self.assertTrue(self._blocks(-563.0))

    def test_deadband_boundary_is_inclusive(self) -> None:
        self.assertTrue(self._blocks(-450.0))    # exactly -50 W compensated
        self.assertFalse(self._blocks(-449.0))

    def test_load_off_blocks_on_any_discharge(self) -> None:
        self.assertTrue(self._blocks(-10.0, is_load_on=False))


if __name__ == "__main__":
    unittest.main()
