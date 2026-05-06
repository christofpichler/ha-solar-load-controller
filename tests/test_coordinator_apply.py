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
helpers_event = sys.modules.setdefault(
    "homeassistant.helpers.event",
    types.ModuleType("homeassistant.helpers.event"),
)
util = sys.modules.setdefault("homeassistant.util", types.ModuleType("homeassistant.util"))
dt_module = sys.modules.setdefault(
    "homeassistant.util.dt",
    types.ModuleType("homeassistant.util.dt"),
)


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

from custom_components.solar_load_controller.const import DECISION_AUTOMATION_PAUSED
from custom_components.solar_load_controller.coordinator import SolarLoadController
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
    def __init__(self, state: str) -> None:
        self.state = state


class _FakeStates:
    def __init__(self) -> None:
        self._states: dict[str, _FakeState] = {}

    def get(self, entity_id: str):
        return self._states.get(entity_id)

    def set(self, entity_id: str, state: str) -> None:
        self._states[entity_id] = _FakeState(state)


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
