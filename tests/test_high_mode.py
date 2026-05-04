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
)


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


if __name__ == "__main__":
    unittest.main()
