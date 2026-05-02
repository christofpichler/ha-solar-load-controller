"""Tests for battery value helpers."""

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

from custom_components.solar_load_controller.battery import (
    classify_battery_power,
    normalize_battery_power,
)
from custom_components.solar_load_controller.const import (
    BATTERY_POWER_CHARGING_POSITIVE,
    BATTERY_POWER_DISCHARGING_POSITIVE,
)


class BatteryHelperTest(unittest.TestCase):
    """Unit tests for raw battery power normalization."""

    def test_positive_charging_direction_keeps_sign(self) -> None:
        """Sensors with positive charging values should be unchanged."""
        power = normalize_battery_power(320.0, BATTERY_POWER_CHARGING_POSITIVE)

        self.assertEqual(power, 320.0)
        self.assertEqual(classify_battery_power(power), "charging")

    def test_positive_discharging_direction_inverts_sign(self) -> None:
        """Sensors with positive discharging values should be inverted."""
        power = normalize_battery_power(320.0, BATTERY_POWER_DISCHARGING_POSITIVE)

        self.assertEqual(power, -320.0)
        self.assertEqual(classify_battery_power(power), "discharging")

    def test_neutral_threshold(self) -> None:
        """Small values around zero should be neutral."""
        self.assertEqual(classify_battery_power(20.0), "neutral")
        self.assertEqual(classify_battery_power(-20.0), "neutral")


if __name__ == "__main__":
    unittest.main()
