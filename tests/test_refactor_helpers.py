"""Focused tests for coordinator helper modules introduced by the refactor."""

from __future__ import annotations

import sys
import types
import unittest
from datetime import datetime, timedelta, timezone
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

homeassistant = sys.modules.setdefault("homeassistant", types.ModuleType("homeassistant"))
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers_storage = sys.modules.setdefault(
    "homeassistant.helpers.storage",
    types.ModuleType("homeassistant.helpers.storage"),
)
util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
dt_module = sys.modules.setdefault(
    "homeassistant.util.dt",
    types.ModuleType("homeassistant.util.dt"),
)


def _callback(func):
    return func


def _utcnow():
    return datetime.now(timezone.utc)


core.callback = _callback
dt_module.utcnow = _utcnow
dt_module.now = _utcnow
dt_module.parse_datetime = datetime.fromisoformat
util.dt = dt_module


class _FakeStore:
    def __init__(self, *_args) -> None:
        pass


helpers_storage.Store = _FakeStore

from custom_components.solar_load_controller.const import FORECAST_DAY_MODE_HIGH
from custom_components.solar_load_controller.forecast_tracker import ForecastTracker
from custom_components.solar_load_controller.grid_import_tracker import (
    GRID_IMPORT_START_MARGIN_W,
    GridImportTracker,
    start_margin_w,
)
from custom_components.solar_load_controller.load_controller import LoadControlState
from custom_components.solar_load_controller.sensor_reader import SensorReader
from custom_components.solar_load_controller.time_window import parse_time


class _State:
    def __init__(self, state: str, unit: str | None = None) -> None:
        self.state = state
        self.attributes = {"unit_of_measurement": unit} if unit else {}
        self.last_changed = _utcnow()
        self.last_updated = _utcnow()


class _States:
    def __init__(self) -> None:
        self._values: dict[str, _State] = {}

    def set(self, entity_id: str, state: str, unit: str | None = None) -> None:
        self._values[entity_id] = _State(state, unit)

    def get(self, entity_id: str):
        return self._values.get(entity_id)


class _Hass:
    def __init__(self) -> None:
        self.states = _States()


class SensorReaderTest(unittest.TestCase):
    def test_energy_sensor_converts_wh_to_kwh(self) -> None:
        hass = _Hass()
        hass.states.set("sensor.forecast", "750", "Wh")

        reader = SensorReader(hass, {})

        self.assertEqual(reader.energy_sensor_kwh("sensor.forecast"), 0.75)

    def test_unknown_numeric_sensor_logs_and_returns_none(self) -> None:
        hass = _Hass()
        hass.states.set("sensor.grid", "unknown", "W")

        reader = SensorReader(hass, {})

        with self.assertLogs(
            "custom_components.solar_load_controller.coordinator",
            level="DEBUG",
        ) as captured:
            self.assertIsNone(reader.positive_state_value("sensor.grid"))

        self.assertIn("Numeric sensor 'sensor.grid' is unknown", captured.output[0])


class TimeWindowHelperTest(unittest.TestCase):
    def test_parse_time_falls_back_when_value_is_invalid(self) -> None:
        self.assertEqual(parse_time("bad", "08:30").hour, 8)
        self.assertEqual(parse_time("bad", "08:30").minute, 30)


class ForecastTrackerTest(unittest.TestCase):
    def test_capture_if_needed_keeps_first_daily_class(self) -> None:
        tracker = ForecastTracker()
        morning = datetime(2026, 5, 11, 6, 1, tzinfo=timezone.utc)

        tracker.capture_if_needed(
            morning,
            8.0,
            2.0,
            high_threshold=3.0,
            low_threshold=1.0,
        )
        tracker.capture_if_needed(
            morning + timedelta(hours=2),
            1.0,
            2.0,
            high_threshold=3.0,
            low_threshold=1.0,
        )

        self.assertEqual(tracker.today_kwh, 8.0)
        self.assertEqual(tracker.day_class, FORECAST_DAY_MODE_HIGH)


class GridImportTrackerTest(unittest.TestCase):
    def test_update_resets_running_timers_when_load_is_off(self) -> None:
        tracker = GridImportTracker()
        now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)

        tracker.update(
            now=now,
            is_load_on=True,
            grid_import_w=900.0,
            grid_import_limit_w=800.0,
            forecast_day_class=FORECAST_DAY_MODE_HIGH,
            high_forecast_day_class=FORECAST_DAY_MODE_HIGH,
            high_grid_import_tolerance_w=25.0,
        )
        tracker.update(
            now=now + timedelta(seconds=10),
            is_load_on=False,
            grid_import_w=900.0,
            grid_import_limit_w=800.0,
            forecast_day_class=FORECAST_DAY_MODE_HIGH,
            high_forecast_day_class=FORECAST_DAY_MODE_HIGH,
            high_grid_import_tolerance_w=25.0,
        )

        self.assertEqual(tracker.over_limit_duration_seconds(now), 0.0)
        self.assertEqual(tracker.high_forecast_duration_seconds(now), 0.0)


class LoadControlStateTest(unittest.TestCase):
    def test_pause_mode_manual_on_is_respected_after_initial_turn_off(self) -> None:
        state = LoadControlState()
        state.set_automation_paused(True, is_load_on=True)
        state.consume_paused_turn_off()

        self.assertTrue(
            state.should_respect_manual_on_while_paused(
                is_load_on=True,
                timeout=timedelta(seconds=30),
            )
        )


class StartMarginTest(unittest.TestCase):
    """The pre-start safety margin must scale with the load being switched on."""

    def test_small_load_keeps_historical_floor(self) -> None:
        self.assertEqual(start_margin_w(400.0), GRID_IMPORT_START_MARGIN_W)

    def test_large_load_scales_with_ratio(self) -> None:
        self.assertEqual(start_margin_w(3000.0), 150.0)
        self.assertEqual(start_margin_w(2000.0), 100.0)

    def test_floor_wins_up_to_one_kilowatt(self) -> None:
        self.assertEqual(start_margin_w(1000.0), GRID_IMPORT_START_MARGIN_W)

    def test_zero_or_negative_load_falls_back_to_floor(self) -> None:
        self.assertEqual(start_margin_w(0.0), GRID_IMPORT_START_MARGIN_W)
        self.assertEqual(start_margin_w(-50.0), GRID_IMPORT_START_MARGIN_W)

    def test_margin_is_never_below_the_floor(self) -> None:
        for load_w in (1.0, 500.0, 999.0, 1000.0, 1001.0, 5000.0):
            with self.subTest(load_power_w=load_w):
                self.assertGreaterEqual(
                    start_margin_w(load_w), GRID_IMPORT_START_MARGIN_W
                )


if __name__ == "__main__":
    unittest.main()
