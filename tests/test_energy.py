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
    household_energy_reserve_kwh,
    required_input_energy,
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


if __name__ == "__main__":
    unittest.main()
