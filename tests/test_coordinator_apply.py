"""Tests for coordinator apply behavior around hard-off conditions."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from dataclasses import replace
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

config_entries = sys.modules.setdefault(
    "homeassistant.config_entries",
    types.ModuleType("homeassistant.config_entries"),
)
core = sys.modules.setdefault("homeassistant.core", types.ModuleType("homeassistant.core"))
const = sys.modules.setdefault("homeassistant.const", types.ModuleType("homeassistant.const"))
helpers = sys.modules.setdefault(
    "homeassistant.helpers",
    types.ModuleType("homeassistant.helpers"),
)
helpers_event = sys.modules.setdefault(
    "homeassistant.helpers.event",
    types.ModuleType("homeassistant.helpers.event"),
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


class _FakeStore:
    """Minimal Store stub: all async operations are no-ops."""

    def __init__(self, _hass, _version, _key) -> None:
        pass

    async def async_load(self):
        return None

    async def async_save(self, _data) -> None:
        pass

    async def async_remove(self) -> None:
        pass


helpers_storage.Store = _FakeStore


class _FakeConfigEntry:
    def __init__(self) -> None:
        self.entry_id = "test-entry"
        self.title = "Pool-Pumpe"
        self.data = {"load_switch": "switch.pool"}
        self.options = {}


class _FakeHomeAssistant:
    pass


class _FakeEvent(dict):
    pass


def _callback(func):
    return func


def _noop_unsub():
    return None


def _track_point_in_time(_hass, _action, _when):
    return _noop_unsub


def _track_state_change_event(_hass, _entities, _action):
    return _noop_unsub


def _track_time_change(_hass, _action, **_kwargs):
    return _noop_unsub


def _track_time_interval(_hass, _action, _interval):
    return _noop_unsub


config_entries.ConfigEntry = _FakeConfigEntry
core.HomeAssistant = _FakeHomeAssistant
core.Event = _FakeEvent
core.callback = _callback
const.STATE_ON = "on"
helpers_event.async_track_point_in_time = _track_point_in_time
helpers_event.async_track_state_change_event = _track_state_change_event
helpers_event.async_track_time_change = _track_time_change
helpers_event.async_track_time_interval = _track_time_interval

from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)


dt_module.utcnow = _utcnow
dt_module.now = _utcnow
util.dt = dt_module

from custom_components.solar_load_controller.const import (
    BATTERY_MODE_USE,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MODE,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_INVERTER_LIMIT_W,
    CONF_LOAD_POWER_W,
    CONF_MIN_DAILY_RUNTIME_MINUTES,
    CONF_MIN_BATTERY_SOC,
    CONF_PV_CURRENT_POWER_SENSOR,
    DECISION_AUTOMATION_PAUSED,
    DECISION_FORECAST_ASSISTED_RUN,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
)
from custom_components.solar_load_controller.coordinator import (
    SolarLoadController,
    today as coordinator_today,
)
from custom_components.solar_load_controller.decision_engine import (
    DecisionInputs,
    evaluate_decision,
)


def make_inputs(**overrides: object) -> DecisionInputs:
    """Return default decision inputs for coordinator-apply tests."""
    base = DecisionInputs(
        is_load_on=True,
        automation_paused=False,
        inside_time_window=True,
        missing_required_grid_sensor_value=False,
        grid_import_w=100.0,
        grid_export_w=0.0,
        grid_import_limit_w=800.0,
        grid_import_start_limit_w=750.0,
        grid_import_over_limit_duration_seconds=0.0,
        grid_import_shutdown_delay_seconds=60.0,
        grid_import_shutdown_allowed=False,
        grid_import_cooldown_active=False,
        grid_import_cooldown_remaining_seconds=0.0,
        projected_grid_import_w=100.0,
        projected_grid_import_formula="current_grid_import",
        available_surplus_w=0.0,
        effective_solar_surplus_w=0.0,
        load_power_w=400.0,
        runtime_today_minutes=0.0,
        runtime_remaining_minutes=180.0,
        required_remaining_energy_kwh=1.2,
        minutes_until_finish=60.0,
        low_mode_runtime_progress=0.0,
        low_mode_runtime_pressure=0.0,
        low_mode_runtime_slack_minutes=180.0,
        low_mode_runtime_wait_buffer_minutes=27.0,
        low_mode_forecast_wait_threshold_kwh=0.45,
        low_mode_assisted_surplus_threshold_w=300.0,
        low_mode_assisted_effective_surplus_threshold_w=300.0,
        low_mode_assisted_start_surplus_w=0.0,
        low_mode_assisted_strength_ratio=0.0,
        low_mode_assisted_priority=0.0,
        low_mode_assisted_forecast_threshold_kwh=0.45,
        min_on_active=False,
        min_on_remaining_minutes=0.0,
        min_off_active=False,
        min_off_remaining_minutes=0.0,
        export_guard_run_available=False,
        battery_priority_after_runtime=False,
        battery_headroom_kwh=4.0,
        battery_charge_required_kwh=4.0,
        high_forecast_post_runtime_battery_charge_required_kwh=4.0,
        high_mode_base_household_load_w=250.0,
        high_mode_household_reserve_margin_percent=20.0,
        high_mode_household_reserve_kwh=1.0,
        forecast_excess_after_battery_kwh=-1.0,
        forecast_assisted_run_available=False,
        high_forecast_grid_import_active=False,
        high_forecast_grid_import_duration_seconds=0.0,
        high_forecast_grid_import_shutdown_delay_seconds=15.0,
        runtime_force_latched=False,
        must_force_minimum_runtime=False,
        min_runtime_battery_override=True,
        min_runtime_grid_override=True,
        projected_grid_import_exceeds_limit=False,
        battery_can_support_forced_runtime=True,
        should_wait_for_forecast=False,
        mid_mode_assisted_surplus_threshold_w=220.0,
        mid_mode_solar_surplus_w=0.0,
        mid_mode_forecast_wait_threshold_kwh=0.3,
        battery_mode="use",
        battery_soc=50.0,
        battery_power_w=0.0,
        battery_power_state="neutral",
        forecast_today_kwh=1.0,
        forecast_remaining_today_kwh=0.0,
        forecast_next_hour_kwh=0.0,
        forecast_kwh_per_kwp=0.5,
        forecast_day_class="low",
    )
    return replace(base, **overrides)


class _FakeState:
    def __init__(self, state: str, attributes: dict[str, object] | None = None) -> None:
        self.state = state
        self.attributes = attributes or {}
        self.last_changed = datetime.now(timezone.utc)
        self.last_updated = self.last_changed


class _FakeStates:
    def __init__(self) -> None:
        self._states: dict[str, _FakeState] = {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)

    def set(
        self,
        entity_id: str,
        state: str,
        unit: str | None = None,
    ) -> None:
        attributes = {}
        if unit is not None:
            attributes["unit_of_measurement"] = unit
        self._states[entity_id] = _FakeState(state, attributes)


class _FakeServices:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict[str, str], bool]] = []

    async def async_call(
        self,
        domain: str,
        service: str,
        data: dict[str, str],
        *,
        blocking: bool,
    ) -> None:
        self.calls.append((domain, service, data, blocking))


class _FakeHassImpl:
    def __init__(self) -> None:
        self.states = _FakeStates()
        self.services = _FakeServices()
        self.data = {}
        self.created_tasks = []

    def async_create_task(self, coro):
        task = asyncio.create_task(coro)
        self.created_tasks.append(task)
        return task


class _TestController(SolarLoadController):
    def __init__(self, hass, entry) -> None:
        super().__init__(hass, entry)
        self._test_decision = evaluate_decision(make_inputs())

    @property
    def decision(self):
        return self._test_decision


class CoordinatorApplyTest(unittest.IsolatedAsyncioTestCase):
    """Exercise coordinator off-paths directly."""

    async def test_manual_on_outside_time_window_turns_off_even_with_missing_sensors(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "on")
        controller = _TestController(hass, _FakeConfigEntry())
        controller._test_decision = evaluate_decision(
            make_inputs(
                is_load_on=True,
                inside_time_window=False,
                missing_required_grid_sensor_value=True,
            )
        )

        await controller._async_apply_decision()

        self.assertEqual(
            hass.services.calls,
            [("switch", "turn_off", {"entity_id": "switch.pool"}, False)],
        )

    async def test_pause_while_running_turns_off(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "on")
        controller = _TestController(hass, _FakeConfigEntry())
        controller._test_decision = evaluate_decision(
            make_inputs(
                is_load_on=True,
                automation_paused=True,
            )
        )

        controller.async_set_automation_paused(True)
        await asyncio.sleep(0)

        self.assertEqual(
            hass.services.calls,
            [("switch", "turn_off", {"entity_id": "switch.pool"}, False)],
        )
        self.assertEqual(controller._test_decision.reason, DECISION_AUTOMATION_PAUSED)

    def test_export_guard_uses_forecast_headroom_path_on_coordinator(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "on")
        hass.states.set("sensor.grid_import", "200", "W")
        hass.states.set("sensor.grid_export", "0", "W")
        hass.states.set("sensor.battery_soc", "80", "%")
        hass.states.set("sensor.battery_power", "0", "W")
        hass.states.set("sensor.forecast_remaining", "10", "kWh")
        hass.states.set("sensor.forecast_next_hour", "0.1", "kWh")
        hass.states.set("sensor.forecast_today", "12", "kWh")

        entry = _FakeConfigEntry()
        controller = _TestController(hass, entry)
        controller.config.update(
            {
                CONF_GRID_IMPORT_SENSOR: "sensor.grid_import",
                CONF_GRID_EXPORT_SENSOR: "sensor.grid_export",
                CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
                CONF_BATTERY_POWER_SENSOR: "sensor.battery_power",
                CONF_BATTERY_CAPACITY_KWH: 5.0,
                CONF_FORECAST_REMAINING_TODAY_SENSOR: "sensor.forecast_remaining",
                CONF_FORECAST_NEXT_HOUR_SENSOR: "sensor.forecast_next_hour",
                CONF_FORECAST_TODAY_SENSOR: "sensor.forecast_today",
                CONF_MIN_DAILY_RUNTIME_MINUTES: 0.0,
            }
        )
        controller._daily_forecast_date = coordinator_today()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_HIGH
        controller._daily_forecast_today_kwh = 12.0

        self.assertTrue(controller._export_guard_run_available)

    def test_export_guard_stays_false_when_forecast_headroom_is_too_small(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "on")
        hass.states.set("sensor.grid_import", "200", "W")
        hass.states.set("sensor.grid_export", "0", "W")
        hass.states.set("sensor.battery_soc", "80", "%")
        hass.states.set("sensor.battery_power", "0", "W")
        hass.states.set("sensor.forecast_remaining", "0.5", "kWh")
        hass.states.set("sensor.forecast_next_hour", "0.1", "kWh")
        hass.states.set("sensor.forecast_today", "12", "kWh")

        entry = _FakeConfigEntry()
        controller = _TestController(hass, entry)
        controller.config.update(
            {
                CONF_GRID_IMPORT_SENSOR: "sensor.grid_import",
                CONF_GRID_EXPORT_SENSOR: "sensor.grid_export",
                CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
                CONF_BATTERY_POWER_SENSOR: "sensor.battery_power",
                CONF_BATTERY_CAPACITY_KWH: 5.0,
                CONF_FORECAST_REMAINING_TODAY_SENSOR: "sensor.forecast_remaining",
                CONF_FORECAST_NEXT_HOUR_SENSOR: "sensor.forecast_next_hour",
                CONF_FORECAST_TODAY_SENSOR: "sensor.forecast_today",
                CONF_MIN_DAILY_RUNTIME_MINUTES: 0.0,
            }
        )
        controller._daily_forecast_date = coordinator_today()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_HIGH
        controller._daily_forecast_today_kwh = 12.0

        self.assertFalse(controller._export_guard_run_available)

    def test_mid_mode_uses_ac_usable_charging_power_for_assist(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "off")
        hass.states.set("sensor.grid_import", "0", "W")
        hass.states.set("sensor.grid_export", "0", "W")
        hass.states.set("sensor.battery_power", "900", "W")
        hass.states.set("sensor.pv_power", "1400", "W")

        controller = _TestController(hass, _FakeConfigEntry())
        controller.config.update(
            {
                CONF_GRID_IMPORT_SENSOR: "sensor.grid_import",
                CONF_GRID_EXPORT_SENSOR: "sensor.grid_export",
                CONF_BATTERY_POWER_SENSOR: "sensor.battery_power",
                CONF_PV_CURRENT_POWER_SENSOR: "sensor.pv_power",
                CONF_INVERTER_LIMIT_W: 1000.0,
                CONF_LOAD_POWER_W: 400.0,
            }
        )
        controller._daily_forecast_date = coordinator_today()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_MID

        self.assertEqual(controller.available_surplus_w, 0.0)
        self.assertEqual(controller.mid_mode_solar_surplus_w, 500.0)
        self.assertTrue(controller._mid_forecast_assisted_run_available)

    def test_battery_force_rejects_soc_at_minimum_boundary(self) -> None:
        from unittest.mock import PropertyMock, patch

        hass = _FakeHassImpl()
        hass.states.set("sensor.battery_soc", "10", "%")
        controller = _TestController(hass, _FakeConfigEntry())
        controller.config.update(
            {
                CONF_BATTERY_MODE: BATTERY_MODE_USE,
                CONF_BATTERY_SOC_SENSOR: "sensor.battery_soc",
                CONF_MIN_BATTERY_SOC: 10,
            }
        )

        with patch.object(
            type(controller),
            "_projected_grid_import_exceeds_limit",
            new_callable=PropertyMock,
        ) as mock_exceeds_limit:
            mock_exceeds_limit.return_value = True
            self.assertFalse(controller._battery_can_support_forced_runtime(60.0))

    def test_energy_sensor_logs_unavailable_state(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("sensor.forecast_remaining", "unavailable", "kWh")
        controller = _TestController(hass, _FakeConfigEntry())

        with self.assertLogs(
            "custom_components.solar_load_controller.coordinator",
            level="DEBUG",
        ) as captured:
            result = controller._energy_sensor_kwh("sensor.forecast_remaining")

        self.assertIsNone(result)
        self.assertIn("Energy sensor 'sensor.forecast_remaining' is unavailable", captured.output[0])

    def test_positive_sensor_logs_unknown_state(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("sensor.battery_soc", "unknown", "%")
        controller = _TestController(hass, _FakeConfigEntry())

        with self.assertLogs(
            "custom_components.solar_load_controller.coordinator",
            level="DEBUG",
        ) as captured:
            result = controller._positive_state_value("sensor.battery_soc")

        self.assertIsNone(result)
        self.assertIn("Numeric sensor 'sensor.battery_soc' is unknown", captured.output[0])

    def test_decision_log_record_includes_debug_input_states(self) -> None:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "off")
        hass.states.set("sensor.grid_import", "100", "W")
        controller = _TestController(hass, _FakeConfigEntry())
        controller.config[CONF_GRID_IMPORT_SENSOR] = "sensor.grid_import"

        record = controller._decision_log_record(controller.decision)

        self.assertEqual(
            record["states"]["grid_import_sensor"]["entity_id"],
            "sensor.grid_import",
        )
        self.assertEqual(record["states"]["grid_import_sensor"]["state"], "100")


class MidModeHoldTest(unittest.TestCase):
    """Exercise the mid-mode hold window and battery_priority guard."""

    def _make_controller(self, load_on: bool = False) -> _TestController:
        hass = _FakeHassImpl()
        hass.states.set("switch.pool", "on" if load_on else "off")
        controller = _TestController(hass, _FakeConfigEntry())
        controller._daily_forecast_date = coordinator_today()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_MID
        controller._daily_forecast_today_kwh = 3.0
        return controller

    def test_hold_window_keeps_run_available_when_solar_collapses(self) -> None:
        """After a forecast_run start, hold window should return True even with zero surplus."""
        from datetime import timedelta
        from unittest.mock import patch, PropertyMock

        controller = self._make_controller(load_on=True)
        # Simulate load just turned on via forecast_run
        controller._tracker._active_runtime_reason = DECISION_FORECAST_ASSISTED_RUN
        controller._last_turned_on_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        # Solar has collapsed
        controller.config.update({"load_power_w": 400.0})

        # Within hold window (2 min < 5 min) and no grid import limit exceeded
        with patch.object(
            type(controller), "mid_mode_solar_surplus_w", new_callable=PropertyMock
        ) as mock_solar, patch.object(
            type(controller), "_projected_grid_import_exceeds_limit", new_callable=PropertyMock
        ) as mock_grid, patch.object(
            type(controller), "available_surplus_w", new_callable=PropertyMock
        ) as mock_surplus, patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem:
            mock_solar.return_value = 0.0
            mock_grid.return_value = False
            mock_surplus.return_value = 0.0
            mock_rem.return_value = 60.0
            self.assertTrue(controller._mid_forecast_assisted_run_available)

    def test_hold_window_releases_when_grid_import_exceeds_limit(self) -> None:
        """Grid import protection must override the hold window immediately."""
        from datetime import timedelta
        from unittest.mock import patch, PropertyMock

        controller = self._make_controller(load_on=True)
        controller._tracker._active_runtime_reason = DECISION_FORECAST_ASSISTED_RUN
        controller._last_turned_on_at = datetime.now(timezone.utc) - timedelta(minutes=1)
        controller.config.update({"load_power_w": 400.0})

        with patch.object(
            type(controller), "mid_mode_solar_surplus_w", new_callable=PropertyMock
        ) as mock_solar, patch.object(
            type(controller), "_projected_grid_import_exceeds_limit", new_callable=PropertyMock
        ) as mock_grid, patch.object(
            type(controller), "available_surplus_w", new_callable=PropertyMock
        ) as mock_surplus, patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem:
            mock_solar.return_value = 0.0
            mock_grid.return_value = True   # grid import exceeded
            mock_surplus.return_value = 0.0
            mock_rem.return_value = 60.0
            self.assertFalse(controller._mid_forecast_assisted_run_available)

    def test_hold_window_expires_after_hold_minutes(self) -> None:
        """After the hold window expires, normal threshold logic applies."""
        from datetime import timedelta
        from unittest.mock import patch, PropertyMock
        from custom_components.solar_load_controller.mid_mode import (
            MID_FORECAST_ASSISTED_HOLD_MINUTES,
        )

        controller = self._make_controller(load_on=True)
        controller._tracker._active_runtime_reason = DECISION_FORECAST_ASSISTED_RUN
        # Started more than hold_minutes ago
        controller._last_turned_on_at = datetime.now(timezone.utc) - timedelta(
            minutes=MID_FORECAST_ASSISTED_HOLD_MINUTES + 1
        )
        controller.config.update({"load_power_w": 400.0})

        with patch.object(
            type(controller), "mid_mode_solar_surplus_w", new_callable=PropertyMock
        ) as mock_solar, patch.object(
            type(controller), "_projected_grid_import_exceeds_limit", new_callable=PropertyMock
        ) as mock_grid, patch.object(
            type(controller), "available_surplus_w", new_callable=PropertyMock
        ) as mock_surplus, patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem, patch.object(
            type(controller), "battery_power_state", new_callable=PropertyMock
        ) as mock_batt:
            mock_solar.return_value = 0.0   # solar still zero
            mock_grid.return_value = False
            mock_surplus.return_value = 0.0
            mock_rem.return_value = 60.0
            mock_batt.return_value = "neutral"
            # Hold expired → normal check → surplus=0 < threshold → False
            self.assertFalse(controller._mid_forecast_assisted_run_available)

    def test_battery_priority_does_not_apply_on_mid_day(self) -> None:
        """battery_priority_after_runtime must return False on mid days."""
        from unittest.mock import patch, PropertyMock

        controller = self._make_controller()

        with patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem:
            mock_rem.return_value = 0.0
            self.assertFalse(controller._should_prioritize_battery_after_runtime())

    def test_battery_priority_does_not_apply_on_low_day(self) -> None:
        """battery_priority_after_runtime must return False on low days."""
        from unittest.mock import patch, PropertyMock

        controller = self._make_controller()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_LOW

        with patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem:
            mock_rem.return_value = 0.0
            self.assertFalse(controller._should_prioritize_battery_after_runtime())

    def test_battery_priority_can_apply_on_high_day(self) -> None:
        """battery_priority_after_runtime is still evaluated on high days."""
        from unittest.mock import patch, PropertyMock

        controller = self._make_controller()
        controller._daily_forecast_day_class = FORECAST_DAY_MODE_HIGH

        with patch.object(
            type(controller), "runtime_remaining_today_minutes", new_callable=PropertyMock
        ) as mock_rem, patch.object(
            type(controller), "battery_soc", new_callable=PropertyMock
        ) as mock_soc:
            mock_rem.return_value = 0.0
            mock_soc.return_value = None   # forces charging-state branch
            # Does not raise and reaches actual high-mode logic
            result = controller._should_prioritize_battery_after_runtime()
            self.assertIsInstance(result, bool)
