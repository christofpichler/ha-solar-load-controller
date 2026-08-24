"""Tests for energy calculation helpers."""

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

from custom_components.solar_load_controller.energy import (
    load_compensated_battery_charge_w,
    household_energy_reserve_kwh,
    required_input_energy,
    time_priority_buffer_kwh,
    usable_battery_charge_for_ac_surplus,
)


class EnergyHelperTest(unittest.TestCase):
    """Unit tests for energy helper functions."""

    def test_required_input_energy_accounts_for_losses(self) -> None:
        """Stored energy should be scaled by charging efficiency."""
        self.assertEqual(required_input_energy(1.0, 0.9), 1.111)

    def test_required_input_energy_handles_zero_storage(self) -> None:
        """Zero storage target should require zero input energy."""
        self.assertEqual(required_input_energy(0.0, 0.9), 0.0)

    def test_battery_charge_above_inverter_limit_does_not_count(self) -> None:
        """Clipped PV above the inverter limit should not count as AC surplus."""
        self.assertEqual(
            usable_battery_charge_for_ac_surplus(462.0, 1449.0, 1000.0),
            13.0,
        )

    def test_battery_charge_counts_normally_below_inverter_limit(self) -> None:
        """Battery charging may still count when PV is below the AC limit."""
        self.assertEqual(
            usable_battery_charge_for_ac_surplus(300.0, 900.0, 1000.0),
            300.0,
        )

    def test_household_reserve_accounts_for_margin_and_time(self) -> None:
        """Household reserve should include the configured margin and remaining hours."""
        self.assertEqual(household_energy_reserve_kwh(250.0, 20.0, 8.0), 2.4)

    def test_time_priority_buffer_uses_light_exponential_curve(self) -> None:
        """Late-day priority buffer should grow with progress and household load."""
        self.assertEqual(
            time_priority_buffer_kwh(
                250.0,
                20.0,
                0.429,
                min_hours=2.0,
                max_hours=8.0,
                exponent=1.6,
            ),
            1.065,
        )


class LoadCompensatedBatteryChargeTest(unittest.TestCase):
    """Surplus checks gating a running load must use the counterfactual."""

    def test_load_off_returns_the_raw_reading(self) -> None:
        self.assertEqual(
            load_compensated_battery_charge_w(500.0, 400.0, is_load_on=False), 500.0
        )

    def test_load_off_clamps_discharge_to_zero(self) -> None:
        self.assertEqual(
            load_compensated_battery_charge_w(-300.0, 400.0, is_load_on=False), 0.0
        )

    def test_running_load_is_credited_back(self) -> None:
        """The observed failure: charging drops from 935 W to 452 W once the
        load runs, falling under the assist threshold and cancelling the run."""
        self.assertEqual(
            load_compensated_battery_charge_w(452.0, 400.0, is_load_on=True), 852.0
        )

    def test_self_inflicted_discharge_becomes_charge_again(self) -> None:
        self.assertEqual(
            load_compensated_battery_charge_w(-171.0, 400.0, is_load_on=True), 229.0
        )

    def test_real_discharge_stays_zero(self) -> None:
        self.assertEqual(
            load_compensated_battery_charge_w(-800.0, 400.0, is_load_on=True), 0.0
        )

    def test_missing_reading_is_zero(self) -> None:
        for on in (False, True):
            with self.subTest(is_load_on=on):
                self.assertEqual(
                    load_compensated_battery_charge_w(None, 400.0, is_load_on=on), 0.0
                )


if __name__ == "__main__":
    unittest.main()
