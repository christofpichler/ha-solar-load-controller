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
    assisted_run_effective_surplus_threshold_w,
    assisted_run_forecast_threshold_kwh,
    assisted_run_priority,
    assisted_run_strength_ratio,
    assisted_run_surplus_threshold_w,
    forecast_wait_threshold_kwh,
    runtime_pressure,
    runtime_wait_buffer_minutes,
    should_allow_assisted_run,
    should_force_runtime,
    should_keep_assisted_run,
    should_wait_for_forecast,
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
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
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
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
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
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
            )
        )

    def test_assisted_run_strength_ratio_reports_how_far_current_solar_exceeds_threshold(self) -> None:
        """Current solar strength should be visible as a ratio above the assist threshold."""
        self.assertEqual(assisted_run_strength_ratio(1720.0, 275.4), 6.245)

    def test_assisted_run_priority_grows_later_in_the_day(self) -> None:
        """Later low-mode progress should make assisted starts more aggressive."""
        self.assertEqual(round(assisted_run_priority(0.5, exponent=0.65), 3), 0.637)

    def test_late_assist_priority_can_lower_required_surplus(self) -> None:
        """Later low-mode assist may accept a meaningfully smaller current solar share."""
        self.assertEqual(
            assisted_run_effective_surplus_threshold_w(
                275.4,
                1.0,
                late_relief_ratio=0.45,
            ),
            151.5,
        )

    def test_strong_current_solar_can_relax_forecast_threshold_to_zero(self) -> None:
        """A very strong current solar window should neutralize the weak next-hour veto."""
        self.assertEqual(
            assisted_run_forecast_threshold_kwh(
                0.497,
                1720.0,
                275.4,
                assist_priority=0.0,
                ratio_span=1.0,
                exponent=2.4,
                late_relief_ratio=0.8,
            ),
            0.0,
        )
        self.assertTrue(
            should_allow_assisted_run(
                effective_solar_surplus_w=1720.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.364,
                forecast_wait_threshold_kwh=0.497,
                required_surplus_w=275.4,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
            )
        )

    def test_slight_current_solar_overage_still_needs_some_forecast_support(self) -> None:
        """A small assisted overage should still keep meaningful forecast caution."""
        adjusted_threshold = assisted_run_forecast_threshold_kwh(
            0.489,
            350.0,
            280.6,
            assist_priority=0.0,
            ratio_span=1.0,
            exponent=2.4,
            late_relief_ratio=0.8,
        )
        self.assertGreater(adjusted_threshold, 0.0)
        self.assertFalse(
            should_allow_assisted_run(
                effective_solar_surplus_w=350.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.364,
                forecast_wait_threshold_kwh=0.489,
                required_surplus_w=280.6,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
            )
        )

    def test_later_assist_priority_can_accept_partial_solar_before_force(self) -> None:
        """Later low-mode assist should prefer moderate PV now over later forced runtime."""
        self.assertTrue(
            should_allow_assisted_run(
                effective_solar_surplus_w=180.0,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.268,
                forecast_wait_threshold_kwh=0.504,
                required_surplus_w=270.6,
                assist_priority=1.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
            )
        )

    def test_later_assist_priority_also_relaxes_forecast_for_just_enough_solar(self) -> None:
        """Later assist should ease the forecast veto even near the relaxed surplus threshold."""
        self.assertEqual(
            assisted_run_forecast_threshold_kwh(
                0.504,
                148.8,
                148.8,
                assist_priority=1.0,
                ratio_span=1.0,
                exponent=2.4,
                late_relief_ratio=0.8,
            ),
            0.101,
        )
        self.assertTrue(
            should_allow_assisted_run(
                effective_solar_surplus_w=148.8,
                projected_grid_import_exceeds_limit=False,
                battery_power_state="charging",
                forecast_next_hour_kwh=0.11,
                forecast_wait_threshold_kwh=0.504,
                required_surplus_w=270.6,
                assist_priority=1.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
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
                effective_solar_surplus_w=250.0,
                current_effective_solar_surplus_w=250.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
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
                effective_solar_surplus_w=250.0,
                current_effective_solar_surplus_w=250.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
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
                effective_solar_surplus_w=250.0,
                current_effective_solar_surplus_w=250.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
            )
        )

    def test_assisted_run_hold_uses_lower_surplus_hysteresis_than_start(self) -> None:
        """Running assist should survive a moderate dip below the start threshold."""
        self.assertTrue(
            should_keep_assisted_run(
                minutes_since_turn_on=1.2,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=False,
                forecast_next_hour_kwh=0.32,
                forecast_wait_threshold_kwh=0.4,
                effective_solar_surplus_w=170.0,
                current_effective_solar_surplus_w=170.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
            )
        )

    def test_assisted_run_hold_still_stops_when_support_drops_too_far(self) -> None:
        """Hold hysteresis should still stop if assist support falls well below the hold floor."""
        self.assertFalse(
            should_keep_assisted_run(
                minutes_since_turn_on=1.2,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=False,
                forecast_next_hour_kwh=0.5,
                forecast_wait_threshold_kwh=0.4,
                effective_solar_surplus_w=150.0,
                current_effective_solar_surplus_w=150.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
            )
        )

    def test_assisted_run_hold_stops_on_real_support_collapse_even_with_smoothed_memory(self) -> None:
        """A running assist should still stop if current support collapses to near zero."""
        self.assertFalse(
            should_keep_assisted_run(
                minutes_since_turn_on=1.2,
                configured_min_on_minutes=1.0,
                assisted_hold_minutes=3.0,
                projected_grid_import_exceeds_limit=False,
                forecast_next_hour_kwh=0.5,
                forecast_wait_threshold_kwh=0.4,
                effective_solar_surplus_w=250.0,
                current_effective_solar_surplus_w=1.0,
                required_surplus_w=200.0,
                assist_priority=0.0,
                forecast_override_ratio_span=1.0,
                forecast_override_exponent=2.4,
                surplus_late_relief_ratio=0.45,
                forecast_late_relief_ratio=0.8,
                hold_surplus_ratio=0.8,
                hold_forecast_ratio=0.75,
                collapse_floor_ratio=0.3,
            )
        )


from custom_components.solar_load_controller.low_mode import (
    forecast_assisted_run_available as low_mode_forecast_assisted_run_available,
)


def _low_assisted_run_inputs(**overrides):
    base = dict(
        is_currently_assisting=False,
        minutes_since_turn_on=None,
        configured_min_on_minutes=5.0,
        assisted_hold_minutes=3.0,
        projected_grid_import_exceeds_limit=False,
        forecast_next_hour_kwh=0.5,
        forecast_wait_threshold_kwh=0.3,
        effective_solar_surplus_w=600.0,
        hold_support_w=600.0,
        required_surplus_w=400.0,
        assist_priority=0.5,
        available_surplus_w=100.0,
        load_power_w=400.0,
        battery_power_state="charging",
        forecast_override_ratio_span=1.0,
        forecast_override_exponent=2.4,
        surplus_late_relief_ratio=0.6,
        forecast_late_relief_ratio=0.9,
        hold_surplus_ratio=0.6,
        hold_forecast_ratio=0.6,
        collapse_floor_ratio=0.5,
    )
    base.update(overrides)
    return base


class LowModeForecastAssistedRunAvailableTest(unittest.TestCase):
    """Unit tests for the low-mode assisted-run orchestrator."""

    def test_strong_solar_already_above_load_blocks_new_start(self) -> None:
        self.assertFalse(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(
                    available_surplus_w=500.0, load_power_w=400.0
                )
            )
        )

    def test_active_assist_holds_within_window(self) -> None:
        self.assertTrue(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(
                    is_currently_assisting=True,
                    minutes_since_turn_on=1.0,
                    forecast_next_hour_kwh=1.0,
                )
            )
        )

    def test_active_assist_releases_after_hold_window(self) -> None:
        self.assertFalse(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(
                    is_currently_assisting=True,
                    minutes_since_turn_on=999.0,
                )
            )
        )

    def test_new_start_when_solar_below_load_and_forecast_strong(self) -> None:
        self.assertTrue(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(
                    available_surplus_w=100.0,
                    load_power_w=400.0,
                    forecast_next_hour_kwh=1.0,
                    effective_solar_surplus_w=900.0,
                )
            )
        )

    def test_grid_import_exceeds_limit_blocks_start(self) -> None:
        self.assertFalse(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(
                    projected_grid_import_exceeds_limit=True,
                )
            )
        )

    def test_discharging_battery_blocks_new_start(self) -> None:
        self.assertFalse(
            low_mode_forecast_assisted_run_available(
                **_low_assisted_run_inputs(battery_power_state="discharging")
            )
        )


if __name__ == "__main__":
    unittest.main()
