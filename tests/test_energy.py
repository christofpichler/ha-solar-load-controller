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

from custom_components.solar_load_controller.energy import required_input_energy


class EnergyHelperTest(unittest.TestCase):
    """Unit tests for energy helper functions."""

    def test_required_input_energy_accounts_for_losses(self) -> None:
        """Stored energy should be scaled by charging efficiency."""
        self.assertEqual(required_input_energy(1.0, 0.9), 1.111)

    def test_required_input_energy_handles_zero_storage(self) -> None:
        """Zero storage target should require zero input energy."""
        self.assertEqual(required_input_energy(0.0, 0.9), 0.0)


if __name__ == "__main__":
    unittest.main()
