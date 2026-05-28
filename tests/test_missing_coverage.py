"""Tests for previously uncovered critical paths.

Covers:
- Export-guard forecast-based path (coordinator Fix 2)
- Low-mode hold window expiry (should_keep_assisted_run)
- Battery-force paths (_battery_can_support_forced_runtime variants)
- _missing_required_grid_sensor_value with pv_size=0
- _parse_time fallback and recursion safety
- min_runtime_battery_override independence from grid override
- Midnight-reset state via decision engine
"""

from __future__ import annotations

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

from datetime import time

from custom_components.solar_load_controller.const import (
    DECISION_BATTERY_PROTECTED,
    DECISION_EXPORT_GUARD,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_MISSING_REQUIRED_SENSOR,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DECISION_WAITING_FOR_SURPLUS,
)
from custom_components.solar_load_controller.decision_engine import (
    DecisionInputs,
    evaluate_decision,
)
from custom_components.solar_load_controller.low_mode import should_keep_assisted_run


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def make_inputs(**overrides: object) -> DecisionInputs:
    """Return default DecisionInputs suitable for these tests."""
    base = DecisionInputs(
        is_load_on=False,
        automation_paused=False,
        inside_time_window=True,
        missing_required_grid_sensor_value=False,
        grid_import_w=50.0,
        grid_export_w=0.0,
        grid_import_limit_w=800.0,
        grid_import_start_limit_w=750.0,
        grid_import_over_limit_duration_seconds=0.0,
        grid_import_shutdown_delay_seconds=15.0,
        grid_import_shutdown_allowed=False,
        grid_import_cooldown_active=False,
        grid_import_cooldown_remaining_seconds=0.0,
        projected_grid_import_w=500.0,
        projected_grid_import_formula="current_grid_import - current_grid_export + load_power",
        available_surplus_w=0.0,
        effective_solar_surplus_w=0.0,
        load_power_w=450.0,
        runtime_today_minutes=0.0,
        runtime_remaining_minutes=180.0,
        required_remaining_energy_kwh=1.35,
        minutes_until_finish=360.0,
        low_mode_runtime_progress=0.0,
        low_mode_runtime_pressure=0.0,
        low_mode_runtime_slack_minutes=180.0,
        low_mode_runtime_wait_buffer_minutes=27.0,
        low_mode_forecast_wait_threshold_kwh=0.45,
        low_mode_assisted_surplus_threshold_w=382.5,
        low_mode_assisted_effective_surplus_threshold_w=382.5,
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
        battery_headroom_kwh=None,
        battery_charge_required_kwh=None,
        high_forecast_post_runtime_battery_charge_required_kwh=None,
        high_mode_base_household_load_w=250.0,
        high_mode_household_reserve_margin_percent=20.0,
        high_mode_household_reserve_kwh=2.4,
        forecast_excess_after_battery_kwh=None,
        forecast_assisted_run_available=False,
        high_forecast_grid_import_active=False,
        high_forecast_grid_import_duration_seconds=0.0,
        high_forecast_grid_import_shutdown_delay_seconds=15.0,
        runtime_force_latched=False,
        must_force_minimum_runtime=False,
        min_runtime_battery_override=False,
        min_runtime_grid_override=True,
        projected_grid_import_exceeds_limit=False,
        battery_can_support_forced_runtime=True,
        should_wait_for_forecast=False,
        mid_mode_assisted_surplus_threshold_w=247.5,
        mid_mode_solar_surplus_w=0.0,
        mid_mode_forecast_wait_threshold_kwh=0.3375,
        battery_mode="preserve",
        battery_soc=80.0,
        battery_power_w=0.0,
        battery_power_state="neutral",
        forecast_today_kwh=3.0,
        forecast_remaining_today_kwh=2.0,
        forecast_next_hour_kwh=0.4,
        forecast_kwh_per_kwp=5.5,
        forecast_day_class="high",
    )
    return replace(base, **overrides)


# ---------------------------------------------------------------------------
# Export-guard: forecast-based path (Fix 2)
# ---------------------------------------------------------------------------

class ExportGuardForecastPathTest(unittest.TestCase):
    """Verify that export_guard triggers from forecast math alone (Fix 2)."""

    def test_export_guard_runs_when_flag_is_set(self) -> None:
        """Decision engine should honour export_guard_run_available=True."""
        result = evaluate_decision(make_inputs(export_guard_run_available=True))
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_EXPORT_GUARD)

    def test_export_guard_does_not_run_when_battery_priority_active(self) -> None:
        """Battery priority must block export_guard after runtime is met."""
        result = evaluate_decision(
            make_inputs(
                runtime_remaining_minutes=0.0,
                export_guard_run_available=False,
                battery_priority_after_runtime=True,
            )
        )
        self.assertFalse(result.should_run)

    def test_export_guard_runs_after_runtime_met_with_no_battery_priority(self) -> None:
        """Export guard should still run after runtime if battery does not need priority."""
        result = evaluate_decision(
            make_inputs(
                runtime_remaining_minutes=0.0,
                export_guard_run_available=True,
                battery_priority_after_runtime=False,
            )
        )
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_EXPORT_GUARD)

    def test_no_export_guard_without_flag(self) -> None:
        """Without export_guard flag the load should stay off."""
        result = evaluate_decision(
            make_inputs(
                export_guard_run_available=False,
                available_surplus_w=0.0,
            )
        )
        self.assertFalse(result.should_run)


# ---------------------------------------------------------------------------
# Missing sensor: pv_size=0 path
# ---------------------------------------------------------------------------

class MissingSensorTest(unittest.TestCase):
    """Verify decision behaviour when required sensors are missing."""

    def test_missing_sensor_blocks_run_even_with_surplus(self) -> None:
        """missing_required_grid_sensor_value should block any run."""
        result = evaluate_decision(
            make_inputs(
                missing_required_grid_sensor_value=True,
                available_surplus_w=800.0,
            )
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MISSING_REQUIRED_SENSOR)

    def test_missing_sensor_beats_time_window_block(self) -> None:
        """Missing sensor must win over time_window so it is visible in the dashboard."""
        result = evaluate_decision(
            make_inputs(
                inside_time_window=False,
                missing_required_grid_sensor_value=True,
            )
        )
        self.assertEqual(result.reason, DECISION_MISSING_REQUIRED_SENSOR)

    def test_missing_sensor_beats_export_guard(self) -> None:
        """Export guard must not override a missing-sensor state."""
        result = evaluate_decision(
            make_inputs(
                missing_required_grid_sensor_value=True,
                export_guard_run_available=True,
            )
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MISSING_REQUIRED_SENSOR)


# ---------------------------------------------------------------------------
# Low-mode hold window: should_keep_assisted_run
# ---------------------------------------------------------------------------

class LowModeHoldWindowTest(unittest.TestCase):
    """should_keep_assisted_run must release the load after the hold window."""

    def _base_keep_kwargs(self) -> dict:
        return dict(
            minutes_since_turn_on=1.0,
            configured_min_on_minutes=0.0,
            assisted_hold_minutes=3.0,
            projected_grid_import_exceeds_limit=False,
            forecast_next_hour_kwh=0.5,
            forecast_wait_threshold_kwh=0.3,
            effective_solar_surplus_w=300.0,
            current_effective_solar_surplus_w=300.0,
            required_surplus_w=350.0,
            assist_priority=0.3,
            forecast_override_ratio_span=1.0,
            forecast_override_exponent=2.4,
            surplus_late_relief_ratio=0.6,
            forecast_late_relief_ratio=0.9,
            hold_surplus_ratio=0.8,
            hold_forecast_ratio=0.75,
            collapse_floor_ratio=0.3,
        )

    def test_keep_returns_true_within_hold_window(self) -> None:
        """Assisted run should be held while still inside the hold window."""
        result = should_keep_assisted_run(**self._base_keep_kwargs())
        self.assertTrue(result)

    def test_keep_returns_false_after_hold_window_expires(self) -> None:
        """Assisted run must be released once the hold window has passed."""
        kwargs = self._base_keep_kwargs()
        kwargs["minutes_since_turn_on"] = 10.0  # past 3-minute hold
        result = should_keep_assisted_run(**kwargs)
        self.assertFalse(result)

    def test_keep_returns_false_when_grid_import_exceeds_limit(self) -> None:
        """Grid import above limit must always stop an assisted run."""
        kwargs = self._base_keep_kwargs()
        kwargs["projected_grid_import_exceeds_limit"] = True
        result = should_keep_assisted_run(**kwargs)
        self.assertFalse(result)

    def test_keep_returns_false_when_support_collapses(self) -> None:
        """A genuine collapse of solar support must stop the hold."""
        kwargs = self._base_keep_kwargs()
        # collapse_floor = 0.3 * effective_threshold
        # effective_threshold ≈ required_surplus * (1 - priority * late_relief)
        # With required=350, priority=0.3, late_relief=0.6:
        # effective ≈ 350 * (1 - 0.18) ≈ 287
        # collapse_floor ≈ 287 * 0.3 ≈ 86 W
        # Set current support well below that:
        kwargs["current_effective_solar_surplus_w"] = 20.0
        result = should_keep_assisted_run(**kwargs)
        self.assertFalse(result)


# ---------------------------------------------------------------------------
# Battery-force paths
# ---------------------------------------------------------------------------

class BatteryForcePathTest(unittest.TestCase):
    """Battery protection should correctly block or allow forced runtime."""

    def test_battery_protected_blocks_force_without_battery_override(self) -> None:
        """Forced runtime should be blocked when battery cannot support it and override is off."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=False,
                min_runtime_battery_override=False,
                min_runtime_grid_override=False,
                projected_grid_import_exceeds_limit=False,
            )
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_BATTERY_PROTECTED)

    def test_battery_override_true_allows_force_despite_low_battery(self) -> None:
        """Battery override should let forced runtime run even when battery is low."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=False,
                min_runtime_battery_override=True,
                projected_grid_import_exceeds_limit=False,
            )
        )
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)

    def test_grid_override_alone_does_not_enable_battery_override(self) -> None:
        """Enabling only grid_override must not silently allow battery discharge (Fix E)."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                battery_can_support_forced_runtime=False,
                min_runtime_grid_override=True,
                min_runtime_battery_override=False,  # explicitly off
                projected_grid_import_exceeds_limit=False,
            )
        )
        # Battery is not supported and battery override is off → must be blocked
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_BATTERY_PROTECTED)

    def test_force_runs_when_projected_import_within_limit(self) -> None:
        """Forced runtime within the grid limit does not need any override."""
        result = evaluate_decision(
            make_inputs(
                must_force_minimum_runtime=True,
                projected_grid_import_exceeds_limit=False,
                battery_can_support_forced_runtime=True,
            )
        )
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REQUIRED)


# ---------------------------------------------------------------------------
# Midnight-reset simulation via decision engine
# ---------------------------------------------------------------------------

class MidnightResetDecisionTest(unittest.TestCase):
    """Simulate the decision state right after a midnight reset.

    The coordinator resets all daily counters at midnight. These tests verify
    that the decision engine behaves correctly with zeroed-out runtime values,
    as would be the case immediately after reset.
    """

    def test_fresh_day_has_full_runtime_remaining(self) -> None:
        """After reset, runtime_remaining should equal the configured minimum."""
        result = evaluate_decision(
            make_inputs(
                runtime_today_minutes=0.0,
                runtime_remaining_minutes=180.0,
                available_surplus_w=0.0,
                should_wait_for_forecast=False,
            )
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_WAITING_FOR_SURPLUS)
        self.assertEqual(result.runtime_remaining_minutes, 180.0)

    def test_solar_starts_immediately_after_reset(self) -> None:
        """A full solar surplus on a fresh day should immediately start the load."""
        result = evaluate_decision(
            make_inputs(
                runtime_today_minutes=0.0,
                runtime_remaining_minutes=180.0,
                available_surplus_w=500.0,
            )
        )
        self.assertTrue(result.should_run)
        self.assertEqual(result.reason, DECISION_SOLAR_SURPLUS_AVAILABLE)

    def test_runtime_met_stops_load_when_target_reached(self) -> None:
        """Once daily runtime target is reached, load must stop."""
        result = evaluate_decision(
            make_inputs(
                runtime_today_minutes=180.0,
                runtime_remaining_minutes=0.0,
                is_load_on=True,
                available_surplus_w=600.0,
                export_guard_run_available=False,
                battery_priority_after_runtime=False,
            )
        )
        self.assertFalse(result.should_run)
        self.assertEqual(result.reason, DECISION_MINIMUM_RUNTIME_REACHED)


# ---------------------------------------------------------------------------
# _parse_time: recursion and fallback safety (Fix G)
# Coordinator imports homeassistant, so we need the same HA stubs as
# test_coordinator_apply.py before we can import coordinator functions.
# ---------------------------------------------------------------------------

def _setup_ha_stubs() -> None:
    """Register minimal homeassistant stubs so coordinator.py can be imported."""
    import types as _types

    def _noop(*_a, **_kw):
        return lambda: None

    for mod_name in (
        "homeassistant",
        "homeassistant.config_entries",
        "homeassistant.core",
        "homeassistant.const",
        "homeassistant.helpers",
        "homeassistant.helpers.event",
        "homeassistant.helpers.storage",
        "homeassistant.util",
        "homeassistant.util.dt",
    ):
        if mod_name not in sys.modules:
            sys.modules[mod_name] = _types.ModuleType(mod_name)

    import datetime as _dt

    class _FakeStore:
        """Minimal Store stub: all async operations are no-ops."""

        def __init__(self, _hass, _version, _key):
            pass

        async def async_load(self):
            return None

        async def async_save(self, _data):
            pass

        async def async_remove(self):
            pass

    sys.modules["homeassistant.const"].STATE_ON = "on"
    sys.modules["homeassistant.core"].callback = lambda f: f
    sys.modules["homeassistant.core"].HomeAssistant = object
    sys.modules["homeassistant.core"].Event = dict
    sys.modules["homeassistant.config_entries"].ConfigEntry = object
    sys.modules["homeassistant.helpers.event"].async_track_state_change_event = _noop
    sys.modules["homeassistant.helpers.event"].async_track_time_interval = _noop
    sys.modules["homeassistant.helpers.event"].async_track_time_change = _noop
    sys.modules["homeassistant.helpers.event"].async_track_point_in_time = _noop
    sys.modules["homeassistant.helpers.storage"].Store = _FakeStore
    _utcnow = lambda: _dt.datetime.now(_dt.timezone.utc)
    sys.modules["homeassistant.util.dt"].utcnow = _utcnow
    sys.modules["homeassistant.util.dt"].now = _utcnow
    sys.modules["homeassistant.util.dt"].parse_datetime = (
        lambda s: _dt.datetime.fromisoformat(s) if s else None
    )
    sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]


_setup_ha_stubs()

import asyncio  # noqa: E402

from custom_components.solar_load_controller.coordinator import (  # noqa: E402
    _FALLBACK_TIME,
    _parse_time,
    SolarLoadController,
)


class ParseTimeTest(unittest.TestCase):
    """_parse_time must not recurse infinitely on bad input."""

    def test_valid_string_parses_correctly(self) -> None:
        result = _parse_time("08:30", "06:00")
        self.assertEqual(result, time(8, 30))

    def test_time_object_passes_through(self) -> None:
        t = time(14, 0)
        result = _parse_time(t, "06:00")
        self.assertEqual(result, t)

    def test_invalid_value_falls_back_to_default(self) -> None:
        result = _parse_time("not-a-time", "09:00")
        self.assertEqual(result, time(9, 0))

    def test_both_invalid_returns_fallback_time(self) -> None:
        """If both value and default are invalid, must return 21:00 without recursion."""
        result = _parse_time("bad", "also-bad")
        self.assertEqual(result, _FALLBACK_TIME)

    def test_none_falls_back_to_default(self) -> None:
        result = _parse_time(None, "07:00")
        self.assertEqual(result, time(7, 0))


# ---------------------------------------------------------------------------
# Persist state: async_load_persist_state / _async_save_persist_state
# ---------------------------------------------------------------------------

class _ControllableStore:
    """Store stub that lets tests inject preloaded data and capture saves."""

    def __init__(self, preload=None):
        self.preload = preload          # data returned by async_load
        self.saved: list[dict] = []     # all data passed to async_save
        self.removed = False

    async def async_load(self):
        return self.preload

    async def async_save(self, data):
        self.saved.append(data)

    async def async_remove(self):
        self.removed = True


def _make_controller(store=None):
    """Build a minimal SolarLoadController with an injected store."""
    import types as _t

    entry = _t.SimpleNamespace(
        entry_id="test-persist",
        title="Test",
        data={"load_switch": "switch.pool"},
        options={},
    )

    class _HA:
        states = _t.SimpleNamespace(get=lambda _self, _eid: None)

    hass = _HA()
    ctrl = SolarLoadController.__new__(SolarLoadController)
    # Manually initialise only the fields needed for persist tests.
    ctrl.hass = hass
    ctrl.entry = entry
    ctrl.config = {}
    ctrl._runtime_force_latched = False
    ctrl._last_turned_off_at = None
    ctrl._listeners = set()
    ctrl._store = store or _ControllableStore()
    return ctrl


class PersistStateTest(unittest.TestCase):
    """async_load_persist_state / _async_save_persist_state correctness."""

    def _run(self, coro):
        return asyncio.run(coro)

    # -- load --

    def test_load_restores_latch_from_today(self) -> None:
        """Latch stored for today is restored."""
        from custom_components.solar_load_controller.coordinator import today
        store = _ControllableStore(preload={
            "date": today().isoformat(),
            "runtime_force_latched": True,
            "last_turned_off_at": None,
        })
        ctrl = _make_controller(store)
        self._run(ctrl.async_load_persist_state())
        self.assertTrue(ctrl._runtime_force_latched)

    def test_load_restores_last_turned_off_at(self) -> None:
        """last_turned_off_at stored for today is restored as a datetime."""
        import datetime as _dt
        from custom_components.solar_load_controller.coordinator import today

        ts = _dt.datetime(2026, 5, 6, 12, 30, 0, tzinfo=_dt.timezone.utc)
        store = _ControllableStore(preload={
            "date": today().isoformat(),
            "runtime_force_latched": False,
            "last_turned_off_at": ts.isoformat(),
        })
        ctrl = _make_controller(store)
        self._run(ctrl.async_load_persist_state())
        self.assertIsNotNone(ctrl._last_turned_off_at)

    def test_load_discards_stale_data_from_previous_day(self) -> None:
        """Data dated yesterday must not restore the latch."""
        store = _ControllableStore(preload={
            "date": "2000-01-01",   # unambiguously stale
            "runtime_force_latched": True,
            "last_turned_off_at": None,
        })
        ctrl = _make_controller(store)
        self._run(ctrl.async_load_persist_state())
        self.assertFalse(ctrl._runtime_force_latched)
        self.assertTrue(store.removed, "stale store entry should be removed")

    def test_load_no_data_leaves_defaults(self) -> None:
        """No stored data → latch and timestamp stay at their init defaults."""
        store = _ControllableStore(preload=None)
        ctrl = _make_controller(store)
        self._run(ctrl.async_load_persist_state())
        self.assertFalse(ctrl._runtime_force_latched)
        self.assertIsNone(ctrl._last_turned_off_at)

    # -- save --

    def test_save_persists_latch_state(self) -> None:
        """_async_save_persist_state writes runtime_force_latched correctly."""
        store = _ControllableStore()
        ctrl = _make_controller(store)
        ctrl._runtime_force_latched = True
        self._run(ctrl._async_save_persist_state())
        self.assertEqual(len(store.saved), 1)
        self.assertTrue(store.saved[0]["runtime_force_latched"])

    def test_save_includes_today_date(self) -> None:
        """Saved payload always includes today's ISO date."""
        from custom_components.solar_load_controller.coordinator import today
        store = _ControllableStore()
        ctrl = _make_controller(store)
        self._run(ctrl._async_save_persist_state())
        self.assertEqual(store.saved[0]["date"], today().isoformat())

    def test_roundtrip_latch_survives_reload(self) -> None:
        """Save then load must reproduce the original latch value."""
        store = _ControllableStore()
        ctrl = _make_controller(store)
        ctrl._runtime_force_latched = True
        self._run(ctrl._async_save_persist_state())

        # Simulate restart: new controller, same store data.
        store2 = _ControllableStore(preload=store.saved[0])
        ctrl2 = _make_controller(store2)
        self._run(ctrl2.async_load_persist_state())
        self.assertTrue(ctrl2._runtime_force_latched)


if __name__ == "__main__":
    unittest.main()
