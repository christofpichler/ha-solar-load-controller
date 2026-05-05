"""Shared runtime and decision state for Solar Load Controller."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .battery import classify_battery_power, normalize_battery_power
from .const import (
    BATTERY_MODE_PRESERVE,
    BATTERY_MODE_USE,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MODE,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_DEBUG_SENSOR_ENABLED,
    CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_LIMIT_W,
    CONF_GRID_IMPORT_SENSOR,
    CONF_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
    CONF_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
    CONF_INVERTER_LIMIT_W,
    CONF_EARLIEST_START_TIME,
    CONF_LATEST_FINISH_TIME,
    CONF_LOAD_POWER_W,
    CONF_LOAD_SWITCH,
    CONF_MIN_BATTERY_SOC,
    CONF_MIN_DAILY_RUNTIME_MINUTES,
    CONF_MIN_RUNTIME_BATTERY_OVERRIDE,
    CONF_MIN_RUNTIME_GRID_OVERRIDE,
    CONF_MIN_OFF_MINUTES,
    CONF_MIN_ON_MINUTES,
    CONF_PV_CURRENT_POWER_SENSOR,
    CONF_PV_SIZE_KWP,
    DECISION_AUTOMATION_PAUSED,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_EARLIEST_START_TIME,
    DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    DEFAULT_FORECAST_WAIT_MINUTES,
    DEFAULT_GRID_IMPORT_LIMIT_W,
    DEFAULT_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
    DEFAULT_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
    DEFAULT_LATEST_FINISH_TIME,
    DEFAULT_LOAD_POWER_W,
    DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
    DEFAULT_MIN_OFF_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
)
from .decision_engine import DecisionInputs, DecisionResult, evaluate_decision
from .energy import (
    household_energy_reserve_kwh,
    required_input_energy,
    time_priority_buffer_kwh,
    usable_battery_charge_for_ac_surplus,
)
from .high_mode import allow_post_runtime_export_guard_restart
from .low_mode import (
    assisted_run_effective_surplus_threshold_w as low_mode_assisted_effective_surplus_threshold_w,
    assisted_run_forecast_threshold_kwh as low_mode_assisted_run_forecast_threshold_kwh,
    assisted_run_priority as low_mode_assisted_run_priority,
    assisted_run_strength_ratio as low_mode_assisted_run_strength_ratio,
    assisted_run_surplus_threshold_w as low_mode_assisted_surplus_threshold_w,
    should_allow_assisted_run as should_allow_low_mode_assisted_run,
    should_keep_assisted_run as should_keep_low_mode_assisted_run,
    forecast_wait_threshold_kwh as low_mode_forecast_wait_threshold_kwh,
    runtime_pressure as low_mode_runtime_pressure,
    runtime_wait_buffer_minutes as low_mode_runtime_wait_buffer_minutes,
    should_wait_for_forecast as should_wait_for_low_mode_forecast,
    should_force_runtime as should_force_low_mode_runtime,
)

_LOGGER = logging.getLogger(__name__)

GRID_IMPORT_RESTART_COOLDOWN = timedelta(seconds=0)
GRID_IMPORT_SHUTDOWN_DELAY = timedelta(seconds=15)
GRID_IMPORT_START_MARGIN_W = 50
HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO = 0.8
HIGH_FORECAST_NO_GRID_TOLERANCE_W = 25
BATTERY_CHARGING_EFFICIENCY = 0.9
HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC = 99
HIGH_FORECAST_POST_RUNTIME_BATTERY_HEADROOM_KWH = 0.05
HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W = 75
HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO = 1.5
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS = 2.0
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS = 8.0
HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT = 1.6
LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO = 0.15
LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO = 0.75
LOW_FORECAST_RUNTIME_BUFFER_EXPONENT = 1.6
LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER = 1.0
LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER = 1.75
LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO = 0.85
LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO = 0.35
LOW_FORECAST_ASSISTED_HOLD_MINUTES = 3.0
LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT = 3.0
LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO = 0.6
LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN = 1.0
LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT = 2.4
LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO = 0.9
PENDING_LOAD_STATE_TIMEOUT = timedelta(seconds=30)
DEBUG_DECISION_LOG_FILENAME = "solar_load_controller_decisions.jsonl"
DEBUG_DECISION_LOG_RETENTION_DAYS = 7
DEBUG_DECISION_LOG_MAX_ENTRIES = 2000

DEBUG_STATE_CONFIG_KEYS = (
    CONF_LOAD_SWITCH,
    CONF_GRID_IMPORT_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_BATTERY_POWER_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_PV_CURRENT_POWER_SENSOR,
)


class SolarLoadController:
    """Track daily load statistics and calculate decision state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.load_entity_id = self.config[CONF_LOAD_SWITCH]
        self.automation_paused = False
        self._applying_decision = False
        self._pending_automatic_turn_on = False
        self._pending_load_state: bool | None = None
        self._pending_decision_reason: str | None = None
        self._pending_load_state_set_at: datetime | None = None
        self._grid_import_over_limit_since: datetime | None = None
        self._high_forecast_grid_import_since: datetime | None = None
        self._last_grid_import_shutdown_at: datetime | None = None
        self._last_logged_decision_signature: tuple[bool, str, str] | None = None

        self._runtime_seconds = 0.0
        self._solar_runtime_seconds = 0.0
        self._forced_runtime_seconds = 0.0
        self._runtime_force_latched = False
        self._active_runtime_reason: str | None = None
        self._switch_cycles = 0
        self._last_runtime_update: datetime | None = None
        self._last_turned_off_at: datetime | None = None
        self._last_turned_on_at: datetime | None = None
        self._daily_forecast_date: date | None = None
        self._daily_forecast_captured_at: datetime | None = None
        self._daily_forecast_today_kwh: float | None = None
        self._daily_forecast_kwh_per_kwp: float | None = None
        self._daily_forecast_day_class: str = "unknown"
        self._forecast_day_mode_override = FORECAST_DAY_MODE_AUTO

        self._listeners: set[Callable[[], None]] = set()
        self._unsubscribers: list[Callable[[], None]] = []

    async def async_start(self) -> None:
        """Start tracking load and input sensor changes."""
        tracked_entities = {self.load_entity_id}
        for key in (
            CONF_GRID_IMPORT_SENSOR,
            CONF_GRID_EXPORT_SENSOR,
            CONF_BATTERY_SOC_SENSOR,
            CONF_BATTERY_POWER_SENSOR,
            CONF_FORECAST_NEXT_HOUR_SENSOR,
            CONF_FORECAST_REMAINING_TODAY_SENSOR,
            CONF_FORECAST_TODAY_SENSOR,
        ):
            if entity_id := self.config.get(key):
                tracked_entities.add(entity_id)

        self._unsubscribers.append(
            async_track_state_change_event(
                self.hass,
                list(tracked_entities),
                self._async_state_changed,
            )
        )
        self._unsubscribers.append(
            async_track_time_interval(
                self.hass,
                self._async_periodic_update,
                timedelta(minutes=1),
            )
        )
        self._unsubscribers.append(
            async_track_time_change(
                self.hass,
                self._async_midnight_reset,
                hour=0,
                minute=0,
                second=0,
            )
        )
        self._unsubscribers.append(
            async_track_time_change(
                self.hass,
                self._async_daily_forecast_capture,
                hour=6,
                minute=0,
                second=0,
            )
        )

        self._capture_daily_forecast_if_needed()

        if self.is_load_on:
            now = dt_util.utcnow()
            self._last_runtime_update = now
            self._last_turned_on_at = now
            self._refresh_active_runtime_reason()

        self.hass.async_create_task(self._async_apply_decision())

    def async_stop(self) -> None:
        """Stop tracking changes."""
        for unsubscribe in self._unsubscribers:
            unsubscribe()
        self._unsubscribers.clear()
        self._listeners.clear()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Subscribe to controller updates."""
        self._listeners.add(listener)
        return lambda: self._listeners.discard(listener)

    @callback
    def async_set_automation_paused(self, paused: bool) -> None:
        """Set whether automatic control is paused."""
        self.automation_paused = paused
        if paused:
            self._runtime_force_latched = False
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def async_set_forecast_day_mode_override(self, mode: str) -> None:
        """Set a manual forecast day mode override for diagnostics."""
        if mode not in {
            FORECAST_DAY_MODE_AUTO,
            FORECAST_DAY_MODE_LOW,
            FORECAST_DAY_MODE_HIGH,
        }:
            return
        self._forecast_day_mode_override = mode
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @property
    def forecast_day_mode_override(self) -> str:
        """Return the selected forecast day mode override."""
        return self._forecast_day_mode_override

    @callback
    def async_restore_stat(self, stat_key: str, value: float, stat_date: str) -> None:
        """Restore one daily statistic after Home Assistant restarts."""
        if stat_date != today().isoformat():
            return

        if stat_key == "runtime_today":
            self._runtime_seconds = max(0.0, value * 60)
        elif stat_key == "solar_runtime_today":
            self._solar_runtime_seconds = max(0.0, value * 60)
        elif stat_key == "forced_runtime_today":
            self._forced_runtime_seconds = max(0.0, value * 60)
        elif stat_key == "switch_cycles_today":
            self._switch_cycles = max(0, int(value))

        self._async_notify_listeners()

    @property
    def is_load_on(self) -> bool:
        """Return whether the configured load is currently on."""
        state = self.hass.states.get(self.load_entity_id)
        return state is not None and state.state == STATE_ON

    @property
    def runtime_today_minutes(self) -> float:
        """Return total runtime today in minutes."""
        return round(self._runtime_today_seconds() / 60, 1)

    @property
    def solar_runtime_today_minutes(self) -> float:
        """Return solar-surplus runtime today in minutes."""
        return round(self._solar_runtime_today_seconds() / 60, 1)

    @property
    def forced_runtime_today_minutes(self) -> float:
        """Return forced runtime today in minutes."""
        return round(self._forced_runtime_today_seconds() / 60, 1)

    @property
    def energy_today_kwh(self) -> float:
        """Return estimated energy used today in kWh."""
        load_power_w = _as_float(
            self.config.get(CONF_LOAD_POWER_W),
            DEFAULT_LOAD_POWER_W,
        )
        return round((self._runtime_today_seconds() / 3600) * load_power_w / 1000, 3)

    @property
    def switch_cycles_today(self) -> int:
        """Return number of automatic on cycles today."""
        return self._switch_cycles

    @callback
    def _async_record_automatic_switch_on(self) -> None:
        """Record one automatic switch-on cycle."""
        self._switch_cycles += 1
        self._async_notify_listeners()

    @property
    def available_surplus_w(self) -> float:
        """Return currently available export surplus in watts."""
        export_w = self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))
        import_w = self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR))
        if export_w is None or import_w is None:
            return 0.0
        return round(max(0.0, export_w - import_w), 1)

    @property
    def effective_solar_surplus_w(self) -> float:
        """Return export plus battery charge power that can feed the load."""
        battery_charge_w = self.usable_battery_charge_w
        active_load_w = self.load_power_w if self.is_load_on else 0.0
        return round(self.available_surplus_w + battery_charge_w + active_load_w, 1)

    @property
    def usable_battery_charge_w(self) -> float:
        """Return battery charge power that is usable for AC surplus decisions."""
        return usable_battery_charge_for_ac_surplus(
            max(0.0, self.battery_power_w or 0.0),
            self.pv_current_power_w,
            self.inverter_limit_w,
        )

    @property
    def grid_export_w(self) -> float | None:
        """Return current grid export in watts."""
        return self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))

    @property
    def grid_import_w(self) -> float | None:
        """Return current grid import in watts."""
        return self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR))

    @property
    def pv_current_power_w(self) -> float | None:
        """Return current PV production in watts."""
        return self._positive_state_value(self.config.get(CONF_PV_CURRENT_POWER_SENSOR))

    @property
    def inverter_limit_w(self) -> float | None:
        """Return configured AC inverter limit in watts, if any."""
        return _as_float(self.config.get(CONF_INVERTER_LIMIT_W))

    @property
    def high_mode_base_household_load_w(self) -> float:
        """Return configured expected household base load for late-day reserve."""
        return _as_float(
            self.config.get(CONF_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W),
            DEFAULT_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
        )

    @property
    def high_mode_household_reserve_margin_percent(self) -> float:
        """Return configured margin on top of the household base load."""
        return _as_float(
            self.config.get(CONF_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT),
            DEFAULT_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
        )

    @property
    def high_mode_household_reserve_kwh(self) -> float:
        """Return forecast reserve for remaining household consumption today."""
        return household_energy_reserve_kwh(
            self.high_mode_base_household_load_w,
            self.high_mode_household_reserve_margin_percent,
            max(0.0, self.minutes_until_finish) / 60,
        )

    @property
    def high_mode_time_priority_buffer_kwh(self) -> float:
        """Return a late-day High-mode battery priority buffer."""
        total_window_minutes = self._total_window_minutes
        if total_window_minutes <= 0:
            progress = 0.0
        else:
            elapsed_window_minutes = max(
                0.0,
                min(total_window_minutes, total_window_minutes - self.minutes_until_finish),
            )
            progress = elapsed_window_minutes / total_window_minutes

        return time_priority_buffer_kwh(
            self.high_mode_base_household_load_w,
            self.high_mode_household_reserve_margin_percent,
            progress,
            min_hours=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS,
            max_hours=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS,
            exponent=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT,
        )

    @property
    def low_mode_runtime_progress(self) -> float:
        """Return low-mode day progress inside the active time window."""
        total_window_minutes = self._total_window_minutes
        if total_window_minutes <= 0:
            return 0.0
        elapsed_window_minutes = max(
            0.0,
            min(total_window_minutes, total_window_minutes - self.minutes_until_finish),
        )
        return round(elapsed_window_minutes / total_window_minutes, 3)

    @property
    def low_mode_runtime_pressure(self) -> float:
        """Return how strongly low mode should already prioritize runtime."""
        return round(
            low_mode_runtime_pressure(
                self.low_mode_runtime_progress,
                exponent=LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
            ),
            3,
        )

    @property
    def low_mode_runtime_slack_minutes(self) -> float:
        """Return remaining free slack between finish time and runtime target."""
        return round(
            max(
                0.0,
                self.minutes_until_finish - self.runtime_remaining_today_minutes,
            ),
            1,
        )

    @property
    def low_mode_runtime_wait_buffer_minutes(self) -> float:
        """Return low-mode slack still tolerated before forcing runtime."""
        min_daily_runtime_minutes = _as_float(
            self.config.get(CONF_MIN_DAILY_RUNTIME_MINUTES),
            DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
        )
        return low_mode_runtime_wait_buffer_minutes(
            min_daily_runtime_minutes,
            self.low_mode_runtime_progress,
            min_ratio=LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
            max_ratio=LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
            exponent=LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
        )

    @property
    def low_mode_forecast_wait_threshold_kwh(self) -> float:
        """Return the next-hour forecast needed to justify waiting in low mode."""
        return low_mode_forecast_wait_threshold_kwh(
            self.load_power_w,
            DEFAULT_FORECAST_WAIT_MINUTES,
            self.low_mode_runtime_pressure,
            min_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
            max_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
        )

    @property
    def low_mode_assisted_surplus_threshold_w(self) -> float:
        """Return the current solar contribution needed for low assisted starts."""
        return low_mode_assisted_surplus_threshold_w(
            self.load_power_w,
            self.low_mode_runtime_pressure,
            early_ratio=LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO,
            late_ratio=LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO,
        )

    @property
    def low_mode_assisted_start_surplus_w(self) -> float:
        """Return current solar support usable for low-assist start decisions."""
        return round(self.available_surplus_w + self.usable_battery_charge_w, 1)

    @property
    def low_mode_assisted_strength_ratio(self) -> float:
        """Return how strongly the current low-assist threshold is exceeded."""
        return low_mode_assisted_run_strength_ratio(
            self.low_mode_assisted_start_surplus_w,
            self.low_mode_assisted_surplus_threshold_w,
        )

    @property
    def low_mode_assisted_priority(self) -> float:
        """Return how strongly low assist should favor earlier PV usage."""
        return low_mode_assisted_run_priority(
            self.low_mode_runtime_progress,
            exponent=LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT,
        )

    @property
    def low_mode_assisted_effective_surplus_threshold_w(self) -> float:
        """Return the effective low-assist surplus threshold after late relief."""
        return low_mode_assisted_effective_surplus_threshold_w(
            self.low_mode_assisted_surplus_threshold_w,
            self.low_mode_assisted_priority,
            late_relief_ratio=LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
        )

    @property
    def low_mode_assisted_forecast_threshold_kwh(self) -> float:
        """Return the effective forecast threshold for low assisted starts."""
        return low_mode_assisted_run_forecast_threshold_kwh(
            self.low_mode_forecast_wait_threshold_kwh,
            self.low_mode_assisted_start_surplus_w,
            self.low_mode_assisted_effective_surplus_threshold_w,
            assist_priority=self.low_mode_assisted_priority,
            ratio_span=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
            exponent=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
            late_relief_ratio=LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
        )

    @property
    def grid_import_limit_w(self) -> float:
        """Return configured allowed grid import in watts."""
        return _as_float(
            self.config.get(CONF_GRID_IMPORT_LIMIT_W),
            DEFAULT_GRID_IMPORT_LIMIT_W,
        )

    @property
    def grid_import_start_limit_w(self) -> float:
        """Return import limit used before starting the load."""
        return max(0.0, self.grid_import_limit_w - GRID_IMPORT_START_MARGIN_W)

    @property
    def grid_import_over_limit_duration_seconds(self) -> float:
        """Return how long running import has exceeded the limit."""
        if self._grid_import_over_limit_since is None:
            return 0.0
        return round(
            max(
                0.0,
                (dt_util.utcnow() - self._grid_import_over_limit_since).total_seconds(),
            ),
            1,
        )

    @property
    def grid_import_shutdown_allowed(self) -> bool:
        """Return whether sustained import excess may shut the load down."""
        return (
            self.grid_import_over_limit_duration_seconds
            >= GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()
        )

    @property
    def high_forecast_grid_import_duration_seconds(self) -> float:
        """Return how long high mode has seen grid import above tolerance."""
        if self._high_forecast_grid_import_since is None:
            return 0.0
        return round(
            max(
                0.0,
                (
                    dt_util.utcnow() - self._high_forecast_grid_import_since
                ).total_seconds(),
            ),
            1,
        )

    @property
    def grid_import_cooldown_active(self) -> bool:
        """Return whether a grid-import restart cooldown is active."""
        if self.is_load_on or self._last_grid_import_shutdown_at is None:
            return False
        return self.grid_import_cooldown_remaining_seconds > 0

    @property
    def grid_import_cooldown_remaining_seconds(self) -> float:
        """Return remaining grid-import cooldown in seconds."""
        if self._last_grid_import_shutdown_at is None:
            return 0.0
        elapsed = dt_util.utcnow() - self._last_grid_import_shutdown_at
        return round(
            max(0.0, GRID_IMPORT_RESTART_COOLDOWN.total_seconds() - elapsed.total_seconds()),
            1,
        )

    @property
    def projected_grid_import_w(self) -> float | None:
        """Return estimated grid import after switching the load on."""
        import_w = self.grid_import_w
        export_w = self.grid_export_w
        if import_w is None or export_w is None:
            return None
        if self.is_load_on:
            return import_w
        return round(max(0.0, import_w - export_w + self.load_power_w), 1)

    @property
    def projected_grid_import_formula(self) -> str:
        """Return the formula used for projected grid import."""
        if self.is_load_on:
            return "current_grid_import"
        return "current_grid_import - current_grid_export + load_power"

    @property
    def load_power_w(self) -> float:
        """Return configured load power in watts."""
        return _as_float(
            self.config.get(CONF_LOAD_POWER_W),
            DEFAULT_LOAD_POWER_W,
        )

    @property
    def min_runtime_grid_override(self) -> bool:
        """Return whether guaranteed runtime may exceed grid import limits."""
        return bool(self.config.get(CONF_MIN_RUNTIME_GRID_OVERRIDE, True))

    @property
    def min_runtime_battery_override(self) -> bool:
        """Return whether guaranteed runtime may exceed battery protection."""
        return bool(
            self.config.get(
                CONF_MIN_RUNTIME_BATTERY_OVERRIDE,
                self.min_runtime_grid_override,
            )
        )

    @property
    def runtime_remaining_today_minutes(self) -> float:
        """Return remaining runtime target for today."""
        minimum_minutes = _as_float(
            self.config.get(CONF_MIN_DAILY_RUNTIME_MINUTES),
            DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
        )
        return round(max(0.0, minimum_minutes - self.runtime_today_minutes), 1)

    @property
    def required_remaining_energy_kwh(self) -> float:
        """Return estimated remaining energy needed to meet runtime target."""
        return round(self.load_power_w * self.runtime_remaining_today_minutes / 60 / 1000, 3)

    @property
    def battery_soc(self) -> float | None:
        """Return battery state of charge in percent."""
        return self._positive_state_value(self.config.get(CONF_BATTERY_SOC_SENSOR))

    @property
    def battery_power_w(self) -> float | None:
        """Return signed battery power normalized to positive charging values."""
        return normalize_battery_power(
            self.battery_power_raw_w,
            self.battery_power_direction,
        )

    @property
    def battery_power_raw_w(self) -> float | None:
        """Return raw signed battery power from the configured sensor."""
        return self._state_as_float(self.config.get(CONF_BATTERY_POWER_SENSOR))

    @property
    def battery_power_direction(self) -> str:
        """Return configured raw battery power direction."""
        return str(
            self.config.get(
                CONF_BATTERY_POWER_DIRECTION,
                DEFAULT_BATTERY_POWER_DIRECTION,
            )
        )

    @property
    def battery_power_state(self) -> str:
        """Return a coarse battery power direction."""
        return classify_battery_power(self.battery_power_w)

    @property
    def battery_mode(self) -> str:
        """Return configured battery mode."""
        return str(self.config.get(CONF_BATTERY_MODE, BATTERY_MODE_PRESERVE))

    @property
    def inside_time_window(self) -> bool:
        """Return whether automatic control is inside the allowed time window."""
        return self._is_inside_time_window

    @property
    def min_on_active(self) -> bool:
        """Return whether the minimum on timer is active."""
        return self._minimum_on_time_active

    @property
    def min_on_remaining_minutes(self) -> float:
        """Return remaining minimum on time in minutes."""
        if self._last_turned_on_at is None:
            return 0.0
        min_on_minutes = _as_float(
            self.config.get(CONF_MIN_ON_MINUTES),
            DEFAULT_MIN_ON_MINUTES,
        )
        return round(max(0.0, min_on_minutes - self._minutes_since(self._last_turned_on_at)), 1)

    @property
    def min_off_active(self) -> bool:
        """Return whether the minimum off timer is active."""
        return self._minimum_off_time_active

    @property
    def min_off_remaining_minutes(self) -> float:
        """Return remaining minimum off time in minutes."""
        if self._last_turned_off_at is None:
            return 0.0
        min_off_minutes = _as_float(
            self.config.get(CONF_MIN_OFF_MINUTES),
            DEFAULT_MIN_OFF_MINUTES,
        )
        return round(max(0.0, min_off_minutes - self._minutes_since(self._last_turned_off_at)), 1)

    @property
    def minutes_until_finish(self) -> float:
        """Return minutes until the configured finish time."""
        return round(self._minutes_until_finish, 1)

    @property
    def forecast_today_kwh(self) -> float | None:
        """Return forecast energy for the whole day in kWh."""
        if self._daily_forecast_date == today():
            return self._daily_forecast_today_kwh
        return self._forecast_today_kwh

    @property
    def forecast_remaining_today_kwh(self) -> float | None:
        """Return forecast energy remaining today in kWh."""
        return self._forecast_remaining_kwh

    @property
    def forecast_next_hour_kwh(self) -> float | None:
        """Return forecast energy for the next hour in kWh."""
        return self._forecast_next_hour_kwh

    @property
    def forecast_kwh_per_kwp(self) -> float | None:
        """Return today's forecast normalized by PV array size."""
        if self._daily_forecast_date == today():
            return self._daily_forecast_kwh_per_kwp
        return self._live_forecast_kwh_per_kwp()

    @property
    def forecast_day_class(self) -> str:
        """Return a coarse forecast class for today's solar yield."""
        if self._forecast_day_mode_override != FORECAST_DAY_MODE_AUTO:
            return self._forecast_day_mode_override
        if self._daily_forecast_date == today():
            return self._daily_forecast_day_class
        return self._classify_forecast_kwh_per_kwp(self._live_forecast_kwh_per_kwp())

    @property
    def daily_forecast_captured_at(self) -> str | None:
        """Return the timestamp used for today's forecast classification."""
        if self._daily_forecast_captured_at is None:
            return None
        return self._daily_forecast_captured_at.isoformat()

    @property
    def battery_headroom_kwh(self) -> float | None:
        """Return estimated free battery capacity in kWh."""
        capacity_kwh = _as_float(self.config.get(CONF_BATTERY_CAPACITY_KWH))
        soc = self.battery_soc
        if capacity_kwh is None or capacity_kwh <= 0 or soc is None:
            return None
        return round(capacity_kwh * max(0.0, 100.0 - soc) / 100, 3)

    @property
    def forecast_excess_after_battery_kwh(self) -> float | None:
        """Return forecast energy likely to exceed battery charging demand."""
        forecast_remaining_kwh = self.forecast_remaining_today_kwh
        battery_charge_required_kwh = self.battery_charge_required_kwh
        if (
            forecast_remaining_kwh is None
            or battery_charge_required_kwh is None
        ):
            return None
        return round(forecast_remaining_kwh - battery_charge_required_kwh, 3)

    @property
    def battery_charge_required_kwh(self) -> float | None:
        """Return solar energy needed to fill the current battery headroom."""
        return self._charging_input_energy_for_storage(self.battery_headroom_kwh)

    @property
    def high_forecast_post_runtime_battery_charge_required_kwh(self) -> float | None:
        """Return charging input needed to reach the high-mode target SOC."""
        return self._charging_input_energy_for_storage(
            self._battery_headroom_to_target_kwh(
                HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC
            )
        )

    def _battery_headroom_to_target_kwh(self, target_soc: float) -> float | None:
        """Return estimated battery headroom in kWh up to the requested SOC target."""
        capacity_kwh = _as_float(self.config.get(CONF_BATTERY_CAPACITY_KWH))
        soc = self.battery_soc
        if capacity_kwh is None or capacity_kwh <= 0 or soc is None:
            return None
        return round(
            capacity_kwh * max(0.0, target_soc - min(100.0, soc)) / 100.0,
            3,
        )

    def _charging_input_energy_for_storage(
        self, storage_kwh: float | None
    ) -> float | None:
        """Return the PV energy required to store the requested energy."""
        return required_input_energy(storage_kwh, BATTERY_CHARGING_EFFICIENCY)

    def _capture_daily_forecast_if_needed(self) -> None:
        """Capture today's forecast once after the morning cutoff."""
        now = dt_util.now()
        if (
            self._daily_forecast_date == now.date()
            and self._daily_forecast_day_class != "unknown"
        ):
            return
        if now.time() >= time(6, 0):
            kwh_per_kwp = self._live_forecast_kwh_per_kwp()
            if kwh_per_kwp is None:
                return
            self._capture_daily_forecast(now, kwh_per_kwp)

    def _capture_daily_forecast(
        self, now: datetime, kwh_per_kwp: float | None = None
    ) -> None:
        """Store today's forecast class so the day mode stays stable."""
        forecast_today_kwh = self._forecast_today_kwh
        if kwh_per_kwp is None:
            kwh_per_kwp = self._live_forecast_kwh_per_kwp()
        if kwh_per_kwp is None:
            return
        self._daily_forecast_date = now.date()
        self._daily_forecast_captured_at = now
        self._daily_forecast_today_kwh = forecast_today_kwh
        self._daily_forecast_kwh_per_kwp = kwh_per_kwp
        self._daily_forecast_day_class = self._classify_forecast_kwh_per_kwp(
            kwh_per_kwp
        )

    def _live_forecast_kwh_per_kwp(self) -> float | None:
        """Return current forecast normalized by configured PV size."""
        forecast_today_kwh = self._forecast_today_kwh
        pv_size_kwp = _as_float(self.config.get(CONF_PV_SIZE_KWP), 0)
        if forecast_today_kwh is None or pv_size_kwp is None or pv_size_kwp <= 0:
            return None
        return round(forecast_today_kwh / pv_size_kwp, 2)

    def _classify_forecast_kwh_per_kwp(self, kwh_per_kwp: float | None) -> str:
        """Classify the daily forecast into low or high."""
        if kwh_per_kwp is None:
            return "unknown"

        high_threshold = _as_float(
            self.config.get(CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP),
            DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
        )
        if kwh_per_kwp >= high_threshold:
            return FORECAST_DAY_MODE_HIGH
        return FORECAST_DAY_MODE_LOW

    @property
    def decision_debug(self) -> dict[str, Any]:
        """Return a detailed decision trace for diagnostics."""
        return self.decision.as_debug_dict()

    @property
    def decision_debug_summary(self) -> str:
        """Return a compact human-readable decision summary."""
        return self.decision.summary

    @property
    def decision_debug_log_info(self) -> dict[str, Any]:
        """Return decision debug log metadata."""
        return {
            "enabled": bool(self.config.get(CONF_DEBUG_SENSOR_ENABLED)),
            "path": self.hass.config.path(DEBUG_DECISION_LOG_FILENAME),
            "format": "jsonl",
            "retention_days": DEBUG_DECISION_LOG_RETENTION_DAYS,
            "max_entries": DEBUG_DECISION_LOG_MAX_ENTRIES,
        }

    @property
    def decision(self) -> DecisionResult:
        """Return the current load decision state."""
        return evaluate_decision(self._decision_inputs)

    @property
    def _decision_inputs(self) -> DecisionInputs:
        """Return a pure snapshot for the decision engine."""
        runtime_remaining = self.runtime_remaining_today_minutes
        return DecisionInputs(
            is_load_on=self.is_load_on,
            automation_paused=self.automation_paused,
            inside_time_window=self.inside_time_window,
            missing_required_grid_sensor_value=self._missing_required_grid_sensor_value,
            grid_import_w=self.grid_import_w,
            grid_export_w=self.grid_export_w,
            grid_import_limit_w=self.grid_import_limit_w,
            grid_import_start_limit_w=self.grid_import_start_limit_w,
            grid_import_over_limit_duration_seconds=(
                self.grid_import_over_limit_duration_seconds
            ),
            grid_import_shutdown_delay_seconds=(
                GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()
            ),
            grid_import_shutdown_allowed=self.grid_import_shutdown_allowed,
            grid_import_cooldown_active=self.grid_import_cooldown_active,
            grid_import_cooldown_remaining_seconds=(
                self.grid_import_cooldown_remaining_seconds
            ),
            projected_grid_import_w=self.projected_grid_import_w,
            projected_grid_import_formula=self.projected_grid_import_formula,
            available_surplus_w=self.available_surplus_w,
            effective_solar_surplus_w=self.effective_solar_surplus_w,
            load_power_w=self.load_power_w,
            runtime_today_minutes=self.runtime_today_minutes,
            runtime_remaining_minutes=runtime_remaining,
            required_remaining_energy_kwh=self.required_remaining_energy_kwh,
            minutes_until_finish=self.minutes_until_finish,
            low_mode_runtime_progress=self.low_mode_runtime_progress,
            low_mode_runtime_pressure=self.low_mode_runtime_pressure,
            low_mode_runtime_slack_minutes=self.low_mode_runtime_slack_minutes,
            low_mode_runtime_wait_buffer_minutes=(
                self.low_mode_runtime_wait_buffer_minutes
            ),
            low_mode_forecast_wait_threshold_kwh=(
                self.low_mode_forecast_wait_threshold_kwh
            ),
            low_mode_assisted_surplus_threshold_w=(
                self.low_mode_assisted_surplus_threshold_w
            ),
            low_mode_assisted_effective_surplus_threshold_w=(
                self.low_mode_assisted_effective_surplus_threshold_w
            ),
            low_mode_assisted_start_surplus_w=(
                self.low_mode_assisted_start_surplus_w
            ),
            low_mode_assisted_strength_ratio=(
                self.low_mode_assisted_strength_ratio
            ),
            low_mode_assisted_priority=self.low_mode_assisted_priority,
            low_mode_assisted_forecast_threshold_kwh=(
                self.low_mode_assisted_forecast_threshold_kwh
            ),
            min_on_active=self.min_on_active,
            min_on_remaining_minutes=self.min_on_remaining_minutes,
            min_off_active=self.min_off_active,
            min_off_remaining_minutes=self.min_off_remaining_minutes,
            export_guard_run_available=(
                self._export_guard_run_available
            ),
            battery_priority_after_runtime=(
                self._should_prioritize_battery_after_runtime()
            ),
            battery_headroom_kwh=self.battery_headroom_kwh,
            battery_charge_required_kwh=self.battery_charge_required_kwh,
            high_forecast_post_runtime_battery_charge_required_kwh=(
                self.high_forecast_post_runtime_battery_charge_required_kwh
            ),
            high_mode_base_household_load_w=(
                self.high_mode_base_household_load_w
            ),
            high_mode_household_reserve_margin_percent=(
                self.high_mode_household_reserve_margin_percent
            ),
            high_mode_household_reserve_kwh=(
                self.high_mode_household_reserve_kwh
            ),
            forecast_excess_after_battery_kwh=(
                self.forecast_excess_after_battery_kwh
            ),
            forecast_assisted_run_available=self._forecast_assisted_run_available,
            high_forecast_grid_import_active=self._high_forecast_grid_import_active,
            high_forecast_grid_import_duration_seconds=(
                self.high_forecast_grid_import_duration_seconds
            ),
            high_forecast_grid_import_shutdown_delay_seconds=(
                GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()
            ),
            runtime_force_latched=self._runtime_force_latched,
            must_force_minimum_runtime=self._must_force_minimum_runtime(
                runtime_remaining
            ),
            min_runtime_battery_override=self.min_runtime_battery_override,
            min_runtime_grid_override=self.min_runtime_grid_override,
            projected_grid_import_exceeds_limit=(
                self._projected_grid_import_exceeds_limit
            ),
            battery_can_support_forced_runtime=(
                self._battery_can_support_forced_runtime(runtime_remaining)
            ),
            should_wait_for_forecast=self._should_wait_for_forecast,
            battery_mode=self.battery_mode,
            battery_soc=self.battery_soc,
            battery_power_w=self.battery_power_w,
            battery_power_state=self.battery_power_state,
            forecast_today_kwh=self.forecast_today_kwh,
            forecast_remaining_today_kwh=self.forecast_remaining_today_kwh,
            forecast_next_hour_kwh=self.forecast_next_hour_kwh,
            forecast_kwh_per_kwp=self.forecast_kwh_per_kwp,
            forecast_day_class=self.forecast_day_class,
        )

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Handle tracked entity state changes."""
        if event.data.get("entity_id") == self.load_entity_id:
            self._async_load_state_changed(event)
        else:
            if self._last_runtime_update is not None:
                self._commit_active_runtime()
            self._capture_daily_forecast_if_needed()
            self._async_update_grid_import_tracking()
            self._refresh_active_runtime_reason()
            self._async_notify_listeners()
            self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_load_state_changed(self, event: Event) -> None:
        """Handle load switch state changes."""
        old_state = event.data.get("old_state")
        new_state = event.data.get("new_state")
        old_is_on = old_state is not None and old_state.state == STATE_ON
        new_is_on = new_state is not None and new_state.state == STATE_ON
        change_source = self._load_change_source(new_is_on)

        if not old_is_on and new_is_on:
            now = dt_util.utcnow()
            self._last_runtime_update = now
            self._last_turned_on_at = now
            self._last_grid_import_shutdown_at = None
            if self._pending_automatic_turn_on:
                self._active_runtime_reason = self._pending_decision_reason
                self._async_record_automatic_switch_on()
            else:
                self._active_runtime_reason = None
        elif old_is_on and not new_is_on:
            self._commit_active_runtime()
            self._last_runtime_update = None
            self._active_runtime_reason = None
            self._last_turned_off_at = dt_util.utcnow()
            self._grid_import_over_limit_since = None
            self._high_forecast_grid_import_since = None
            if (
                change_source == "manual"
                or self.runtime_remaining_today_minutes <= 0
            ):
                self._runtime_force_latched = False

        self._async_clear_pending_load_state(new_is_on)
        self._async_update_grid_import_tracking()
        if old_is_on != new_is_on and change_source == "manual":
            self._async_log_manual_load_change(new_is_on)
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_periodic_update(self, now: datetime) -> None:
        """Commit active runtime while the load is running."""
        if self._last_runtime_update is not None:
            self._commit_active_runtime(now)
        self._capture_daily_forecast_if_needed()
        self._async_update_grid_import_tracking(now)
        self._refresh_active_runtime_reason()
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_midnight_reset(self, now: datetime) -> None:
        """Reset daily statistics at midnight."""
        self._runtime_seconds = 0.0
        self._solar_runtime_seconds = 0.0
        self._forced_runtime_seconds = 0.0
        self._runtime_force_latched = False
        self._switch_cycles = 0
        self._last_runtime_update = dt_util.utcnow() if self.is_load_on else None
        if self.is_load_on:
            self._last_turned_on_at = self._last_runtime_update
            self._last_turned_off_at = None
            self._refresh_active_runtime_reason()
        else:
            self._active_runtime_reason = None
        self._async_clear_pending_load_state(self.is_load_on)
        self._grid_import_over_limit_since = None
        self._high_forecast_grid_import_since = None
        self._last_grid_import_shutdown_at = None
        self._daily_forecast_date = None
        self._daily_forecast_captured_at = None
        self._daily_forecast_today_kwh = None
        self._daily_forecast_kwh_per_kwp = None
        self._daily_forecast_day_class = "unknown"
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_daily_forecast_capture(self, now: datetime) -> None:
        """Capture today's forecast classification once in the morning."""
        self._capture_daily_forecast_if_needed()
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    async def _async_apply_decision(self) -> None:
        """Apply the current decision to the configured load switch."""
        if self._applying_decision:
            return

        self._applying_decision = True
        try:
            decision = self.decision
            if (
                decision.should_run
                and decision.reason == DECISION_MINIMUM_RUNTIME_REQUIRED
            ):
                self._runtime_force_latched = True
            elif (
                not decision.should_run
                and decision.reason in {
                    DECISION_AUTOMATION_PAUSED,
                    DECISION_MINIMUM_RUNTIME_REACHED,
                }
            ):
                self._runtime_force_latched = False
            self._async_log_decision_if_changed(decision)
            if decision.reason == DECISION_AUTOMATION_PAUSED:
                return
            if decision.should_run == self.is_load_on:
                return
            if self._pending_load_state_matches(decision.should_run):
                return

            domain, _, _object_id = self.load_entity_id.partition(".")
            if domain not in {"switch", "input_boolean"}:
                return

            service = "turn_on" if decision.should_run else "turn_off"
            self._async_set_pending_load_state(
                decision.should_run,
                automatic_turn_on=decision.should_run,
                decision_reason=decision.reason,
            )
            try:
                await self.hass.services.async_call(
                    domain,
                    service,
                    {"entity_id": self.load_entity_id},
                    blocking=False,
                )
                if (
                    not decision.should_run
                    and decision.reason == DECISION_GRID_IMPORT_LIMIT_EXCEEDED
                ):
                    self._last_grid_import_shutdown_at = dt_util.utcnow()
            except Exception:
                self._async_clear_pending_load_state()
                raise
        finally:
            self._applying_decision = False

    @callback
    def _async_log_decision_if_changed(
        self,
        decision: DecisionResult,
    ) -> None:
        """Write a debug log record when the decision state changes."""
        if not self.config.get(CONF_DEBUG_SENSOR_ENABLED):
            return

        signature = (decision.should_run, decision.reason, decision.summary)
        if signature == self._last_logged_decision_signature:
            return
        self._last_logged_decision_signature = signature

        record = self._decision_log_record(decision)
        self.hass.async_create_task(self._async_write_decision_log(record))

    @callback
    def _async_log_manual_load_change(self, is_on: bool) -> None:
        """Write an explicit debug record for a manual load state change."""
        if not self.config.get(CONF_DEBUG_SENSOR_ENABLED):
            return

        action = "turn_on" if is_on else "turn_off"
        decision = self.decision
        record = self._decision_log_record(
            decision,
            event={
                "type": "load_change",
                "source": "manual",
                "action": action,
            },
        )
        self.hass.async_create_task(self._async_write_decision_log(record))

    async def _async_write_decision_log(self, record: dict[str, Any]) -> None:
        """Write one debug decision record in the executor."""
        path = self.hass.config.path(DEBUG_DECISION_LOG_FILENAME)
        try:
            await self.hass.async_add_executor_job(
                _append_debug_decision_log,
                path,
                record,
            )
        except OSError as err:
            _LOGGER.warning("Could not write decision debug log: %s", err)

    def _decision_log_record(
        self,
        decision: DecisionResult,
        *,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return one JSON-serializable decision log record."""
        now_local = dt_util.now()
        now_utc = dt_util.utcnow()
        return {
            "timestamp": now_local.isoformat(),
            "timestamp_utc": now_utc.isoformat(),
            "timestamp_epoch": now_utc.timestamp(),
            "schema": 1,
            "event": event or {"type": "decision_change"},
            "entry": {
                "entry_id": self.entry.entry_id,
                "title": self.entry.title,
            },
            "retention": {
                "days": DEBUG_DECISION_LOG_RETENTION_DAYS,
                "max_entries": DEBUG_DECISION_LOG_MAX_ENTRIES,
            },
            "load": {
                "entity_id": self.load_entity_id,
                "is_on": self.is_load_on,
            },
            "settings": {
                "load_power_w": self.load_power_w,
                "grid_import_limit_w": self.grid_import_limit_w,
                "grid_import_shutdown_delay_seconds": (
                    GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()
                ),
                "high_grid_import_tolerance_w": HIGH_FORECAST_NO_GRID_TOLERANCE_W,
                "battery_charging_efficiency": BATTERY_CHARGING_EFFICIENCY,
                "high_forecast_post_runtime_battery_target_soc": (
                    HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC
                ),
                "high_forecast_post_runtime_restart_surplus_margin_w": (
                    HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W
                ),
                "high_forecast_post_runtime_next_hour_ratio": (
                    HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO
                ),
                "high_forecast_post_runtime_priority_buffer_min_hours": (
                    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS
                ),
                "high_forecast_post_runtime_priority_buffer_max_hours": (
                    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS
                ),
                "high_forecast_post_runtime_priority_buffer_exponent": (
                    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT
                ),
                "low_forecast_runtime_buffer_min_ratio": (
                    LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO
                ),
                "low_forecast_runtime_buffer_max_ratio": (
                    LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO
                ),
                "low_forecast_runtime_buffer_exponent": (
                    LOW_FORECAST_RUNTIME_BUFFER_EXPONENT
                ),
                "low_forecast_wait_threshold_min_multiplier": (
                    LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER
                ),
                "low_forecast_wait_threshold_max_multiplier": (
                    LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER
                ),
                "low_forecast_assisted_surplus_early_ratio": (
                    LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO
                ),
                "low_forecast_assisted_surplus_late_ratio": (
                    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO
                ),
                "low_forecast_assisted_hold_minutes": (
                    LOW_FORECAST_ASSISTED_HOLD_MINUTES
                ),
                "low_forecast_assisted_priority_exponent": (
                    LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT
                ),
                "low_forecast_assisted_surplus_late_relief_ratio": (
                    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO
                ),
                "low_forecast_assisted_forecast_override_ratio_span": (
                    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN
                ),
                "low_forecast_assisted_forecast_override_exponent": (
                    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT
                ),
                "low_forecast_assisted_forecast_late_relief_ratio": (
                    LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO
                ),
                "high_mode_base_household_load_w": (
                    self.high_mode_base_household_load_w
                ),
                "high_mode_household_reserve_margin_percent": (
                    self.high_mode_household_reserve_margin_percent
                ),
                "min_runtime_battery_override": self.min_runtime_battery_override,
                "min_runtime_grid_override": self.min_runtime_grid_override,
                "forecast_day_mode_override": self.forecast_day_mode_override,
            },
            "states": self._debug_input_states(),
            "decision": decision.as_debug_dict(),
        }

    @callback
    def _load_change_source(self, current_state: bool) -> str:
        """Return whether the current load state change is automatic or manual."""
        if self._pending_load_state_matches(current_state):
            return "automatic"
        return "manual"

    def _debug_input_states(self) -> dict[str, dict[str, Any]]:
        """Return the raw HA state for configured input entities."""
        states: dict[str, dict[str, Any]] = {}
        for key in DEBUG_STATE_CONFIG_KEYS:
            entity_id = self.config.get(key)
            if not isinstance(entity_id, str) or not entity_id:
                continue

            state = self.hass.states.get(entity_id)
            states[key] = {
                "entity_id": entity_id,
                "state": state.state if state is not None else None,
                "unit_of_measurement": (
                    state.attributes.get("unit_of_measurement")
                    if state is not None
                    else None
                ),
                "last_changed": (
                    state.last_changed.isoformat() if state is not None else None
                ),
                "last_updated": (
                    state.last_updated.isoformat() if state is not None else None
                ),
            }
        return states

    @callback
    def _async_notify_listeners(self) -> None:
        """Notify all subscribed entities."""
        for listener in list(self._listeners):
            listener()

    @callback
    def _async_set_pending_load_state(
        self,
        desired_state: bool,
        *,
        automatic_turn_on: bool,
        decision_reason: str,
    ) -> None:
        """Track an in-flight service call until HA reports the state change."""
        self._pending_load_state = desired_state
        self._pending_load_state_set_at = dt_util.utcnow()
        self._pending_automatic_turn_on = automatic_turn_on
        self._pending_decision_reason = decision_reason if automatic_turn_on else None

    @callback
    def _async_clear_pending_load_state(self, current_state: bool | None = None) -> None:
        """Clear pending state when it is completed or explicitly reset."""
        if current_state is not None and self._pending_load_state != current_state:
            return
        self._pending_load_state = None
        self._pending_load_state_set_at = None
        self._pending_automatic_turn_on = False
        self._pending_decision_reason = None

    def _pending_load_state_matches(self, desired_state: bool) -> bool:
        """Return whether the desired service call is already in flight."""
        if self._pending_load_state != desired_state:
            return False
        if self._pending_load_state_set_at is None:
            return False
        if dt_util.utcnow() - self._pending_load_state_set_at > PENDING_LOAD_STATE_TIMEOUT:
            self._async_clear_pending_load_state()
            return False
        return True

    @callback
    def _async_update_grid_import_tracking(
        self,
        now: datetime | None = None,
    ) -> None:
        """Track sustained grid import excess while the load is running."""
        now = now or dt_util.utcnow()
        grid_import_w = self.grid_import_w
        over_limit = (
            self.is_load_on
            and grid_import_w is not None
            and grid_import_w > self.grid_import_limit_w
        )
        if over_limit:
            if self._grid_import_over_limit_since is None:
                self._grid_import_over_limit_since = now
        else:
            self._grid_import_over_limit_since = None

        high_over_tolerance = (
            self.is_load_on
            and self.forecast_day_class == FORECAST_DAY_MODE_HIGH
            and grid_import_w is not None
            and grid_import_w > HIGH_FORECAST_NO_GRID_TOLERANCE_W
        )
        if high_over_tolerance:
            if self._high_forecast_grid_import_since is None:
                self._high_forecast_grid_import_since = now
            return
        self._high_forecast_grid_import_since = None

    def _runtime_today_seconds(self) -> float:
        """Return committed and active runtime in seconds."""
        return self._runtime_seconds + self._active_delta_seconds()

    def _solar_runtime_today_seconds(self) -> float:
        """Return committed and active solar runtime in seconds."""
        if self._active_runtime_reason not in {
            DECISION_SOLAR_SURPLUS_AVAILABLE,
            DECISION_FORECAST_ASSISTED_RUN,
            DECISION_LOW_FORECAST_ASSISTED_RUN,
            DECISION_EXPORT_GUARD,
        }:
            return self._solar_runtime_seconds
        return self._solar_runtime_seconds + self._active_delta_seconds()

    def _forced_runtime_today_seconds(self) -> float:
        """Return committed and active forced runtime in seconds."""
        if self._active_runtime_reason != DECISION_MINIMUM_RUNTIME_REQUIRED:
            return self._forced_runtime_seconds
        return self._forced_runtime_seconds + self._active_delta_seconds()

    def _active_delta_seconds(self, now: datetime | None = None) -> float:
        """Return active runtime since the last committed update."""
        if self._last_runtime_update is None:
            return 0.0
        now = now or dt_util.utcnow()
        return max(0.0, (now - self._last_runtime_update).total_seconds())

    def _commit_active_runtime(self, now: datetime | None = None) -> None:
        """Commit active runtime into the daily counters."""
        if self._last_runtime_update is None:
            return

        now = now or dt_util.utcnow()
        delta_seconds = self._active_delta_seconds(now)
        reason = self._active_runtime_reason

        self._runtime_seconds += delta_seconds
        if reason in {
            DECISION_SOLAR_SURPLUS_AVAILABLE,
            DECISION_FORECAST_ASSISTED_RUN,
            DECISION_LOW_FORECAST_ASSISTED_RUN,
            DECISION_EXPORT_GUARD,
        }:
            self._solar_runtime_seconds += delta_seconds
        elif reason == DECISION_MINIMUM_RUNTIME_REQUIRED:
            self._forced_runtime_seconds += delta_seconds

        self._last_runtime_update = now

    def _refresh_active_runtime_reason(self) -> None:
        """Refresh the source category for the current active runtime interval."""
        if not self.is_load_on:
            self._active_runtime_reason = None
            return

        reason = self.decision.reason
        if reason in {
            DECISION_SOLAR_SURPLUS_AVAILABLE,
            DECISION_FORECAST_ASSISTED_RUN,
            DECISION_LOW_FORECAST_ASSISTED_RUN,
            DECISION_EXPORT_GUARD,
            DECISION_MINIMUM_RUNTIME_REQUIRED,
        }:
            self._active_runtime_reason = reason

    def _must_force_minimum_runtime(self, runtime_remaining_minutes: float) -> bool:
        """Return whether the runtime target must be forced now."""
        if runtime_remaining_minutes <= 0:
            self._runtime_force_latched = False
            return False

        if self._runtime_force_latched and not self.automation_paused:
            return True

        if self._forecast_is_insufficient_for_remaining_runtime:
            return True

        if (
            self.forecast_day_class == FORECAST_DAY_MODE_LOW
            and should_force_low_mode_runtime(
                runtime_remaining_minutes,
                self._minutes_until_finish,
                _as_float(
                    self.config.get(CONF_MIN_DAILY_RUNTIME_MINUTES),
                    DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
                ),
                self.low_mode_runtime_progress,
                min_ratio=LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
                max_ratio=LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
                exponent=LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
            )
        ):
            return True

        return self._runtime_deadline_reached(runtime_remaining_minutes)

    @property
    def _minutes_until_finish(self) -> float:
        """Return minutes until the configured finish time."""
        finish_time = _parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        now = dt_util.now()
        finish_at = datetime.combine(now.date(), finish_time, tzinfo=now.tzinfo)
        if finish_at < now and self._window_crosses_midnight:
            finish_at += timedelta(days=1)
        return max(0.0, (finish_at - now).total_seconds() / 60)

    @property
    def _total_window_minutes(self) -> float:
        """Return total minutes in the configured active window."""
        start_time = _parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = _parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        start_dt = datetime.combine(today(), start_time)
        finish_dt = datetime.combine(today(), finish_time)
        if finish_dt <= start_dt:
            finish_dt += timedelta(days=1)
        return max(0.0, (finish_dt - start_dt).total_seconds() / 60)

    def _runtime_deadline_reached(self, runtime_remaining_minutes: float) -> bool:
        """Return whether runtime has to start now to finish in time."""
        minutes_until_finish = self._minutes_until_finish
        return runtime_remaining_minutes >= minutes_until_finish

    @property
    def _window_crosses_midnight(self) -> bool:
        """Return whether the configured time window crosses midnight."""
        start_time = _parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = _parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        return start_time > finish_time

    @property
    def _is_inside_time_window(self) -> bool:
        """Return whether automatic control is allowed by the daily time window."""
        start_time = _parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = _parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        now_time = dt_util.now().time()

        if not self._window_crosses_midnight:
            return start_time <= now_time <= finish_time

        return now_time >= start_time or now_time <= finish_time

    def _state_as_float(self, entity_id: str | None) -> float | None:
        """Return a state value as float, if possible."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return _as_float(state.state)

    def _state_unit(self, entity_id: str | None) -> str | None:
        """Return a state's unit of measurement."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        return str(unit) if unit is not None else None

    def _positive_state_value(self, entity_id: str | None) -> float | None:
        """Return a positive sensor state value."""
        if not entity_id:
            return None
        value = self._state_as_float(entity_id)
        if value is None:
            return None
        return max(0.0, value)

    def _energy_sensor_kwh(self, entity_id: str | None) -> float | None:
        """Return an energy forecast sensor value in kWh."""
        if not entity_id:
            return None
        value = self._state_as_float(entity_id)
        if value is None:
            return None

        unit = (self._state_unit(entity_id) or "").lower()
        if unit in {"wh", "w h"}:
            return max(0.0, value / 1000)
        return max(0.0, value)

    @property
    def _missing_required_grid_sensor_value(self) -> bool:
        """Return whether required sensor values are unavailable."""
        pv_size_kwp = _as_float(self.config.get(CONF_PV_SIZE_KWP), 0)
        return (
            self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR)) is None
            or self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))
            is None
            or self._forecast_today_kwh is None
            or pv_size_kwp is None
            or pv_size_kwp <= 0
        )

    @property
    def _minimum_on_time_active(self) -> bool:
        """Return whether the configured minimum on time is active."""
        if self._last_turned_on_at is None:
            return False
        min_on_minutes = _as_float(
            self.config.get(CONF_MIN_ON_MINUTES),
            DEFAULT_MIN_ON_MINUTES,
        )
        return self._minutes_since(self._last_turned_on_at) < min_on_minutes

    @property
    def _minimum_off_time_active(self) -> bool:
        """Return whether the configured minimum off time is active."""
        if self.is_load_on or self._last_turned_off_at is None:
            return False
        min_off_minutes = _as_float(
            self.config.get(CONF_MIN_OFF_MINUTES),
            DEFAULT_MIN_OFF_MINUTES,
        )
        return self._minutes_since(self._last_turned_off_at) < min_off_minutes

    def _battery_can_support_forced_runtime(self, runtime_remaining_minutes: float) -> bool:
        """Return whether battery settings allow forced runtime.

        If the projected grid import stays within the configured limit, the
        guaranteed runtime is supplied by grid budget and must not be blocked by
        a low battery SOC on low forecast days.
        """
        if not self._projected_grid_import_exceeds_limit:
            return True

        battery_mode = self.config.get(CONF_BATTERY_MODE, BATTERY_MODE_PRESERVE)
        if battery_mode == BATTERY_MODE_PRESERVE:
            return self.battery_power_state != "discharging"

        if battery_mode != BATTERY_MODE_USE:
            return False

        soc_entity = self.config.get(CONF_BATTERY_SOC_SENSOR)
        if soc_entity:
            soc = self.battery_soc
            if soc is None:
                return False

            minimum_soc = _as_float(self.config.get(CONF_MIN_BATTERY_SOC), 0)
            if soc < minimum_soc:
                return False

        if (
            self.battery_power_state == "discharging"
            and not self._runtime_deadline_reached(runtime_remaining_minutes)
        ):
            return False

        return True

    @property
    def _projected_grid_import_exceeds_limit(self) -> bool:
        """Return whether starting the load would exceed allowed grid import."""
        projected_import_w = self.projected_grid_import_w
        if self.is_load_on:
            limit_w = self.grid_import_limit_w
        else:
            limit_w = self.grid_import_start_limit_w
        return (
            projected_import_w is not None
            and projected_import_w > limit_w
        )

    @property
    def _forecast_assisted_run_available(self) -> bool:
        """Return whether future mid-day forecast assistance may run the load."""
        if self.forecast_day_class != FORECAST_DAY_MODE_LOW:
            return False

        runtime_remaining_minutes = self.runtime_remaining_today_minutes
        if runtime_remaining_minutes <= 0:
            return False
        if self._must_force_minimum_runtime(runtime_remaining_minutes):
            return False
        if (
            self.is_load_on
            and self._active_runtime_reason == DECISION_LOW_FORECAST_ASSISTED_RUN
            and self._last_turned_on_at is not None
        ):
            min_on_minutes = _as_float(
                self.config.get(CONF_MIN_ON_MINUTES),
                DEFAULT_MIN_ON_MINUTES,
            )
            return should_keep_low_mode_assisted_run(
                minutes_since_turn_on=self._minutes_since(self._last_turned_on_at),
                configured_min_on_minutes=min_on_minutes,
                assisted_hold_minutes=LOW_FORECAST_ASSISTED_HOLD_MINUTES,
                projected_grid_import_exceeds_limit=self._projected_grid_import_exceeds_limit,
                forecast_next_hour_kwh=self._forecast_next_hour_kwh,
                forecast_wait_threshold_kwh=self.low_mode_forecast_wait_threshold_kwh,
                effective_solar_surplus_w=self.low_mode_assisted_start_surplus_w,
                required_surplus_w=self.low_mode_assisted_surplus_threshold_w,
                assist_priority=self.low_mode_assisted_priority,
                forecast_override_ratio_span=(
                    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN
                ),
                forecast_override_exponent=(
                    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT
                ),
                surplus_late_relief_ratio=(
                    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO
                ),
                forecast_late_relief_ratio=(
                    LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO
                ),
            )
        if self.available_surplus_w >= self.load_power_w:
            return False

        return should_allow_low_mode_assisted_run(
            effective_solar_surplus_w=self.low_mode_assisted_start_surplus_w,
            projected_grid_import_exceeds_limit=self._projected_grid_import_exceeds_limit,
            battery_power_state=self.battery_power_state,
            forecast_next_hour_kwh=self._forecast_next_hour_kwh,
            forecast_wait_threshold_kwh=self.low_mode_forecast_wait_threshold_kwh,
            required_surplus_w=self.low_mode_assisted_surplus_threshold_w,
            assist_priority=self.low_mode_assisted_priority,
            forecast_override_ratio_span=(
                LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN
            ),
            forecast_override_exponent=(
                LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT
            ),
            surplus_late_relief_ratio=(
                LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO
            ),
            forecast_late_relief_ratio=(
                LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO
            ),
        )

    @property
    def _export_guard_run_available(self) -> bool:
        """Return whether forecast suggests running now to avoid clipping later."""
        if not self._forecast_enabled:
            return False
        if self.forecast_day_class != FORECAST_DAY_MODE_HIGH:
            return False
        if (
            not self.is_load_on
            and self.grid_import_w is not None
            and self.grid_import_w > HIGH_FORECAST_NO_GRID_TOLERANCE_W
        ):
            return False
        if self._high_forecast_grid_import_active:
            return False
        if self._should_prioritize_battery_after_runtime():
            return False
        if self.available_surplus_w >= self.load_power_w:
            return True
        if not self._allow_post_runtime_export_guard_restart():
            return False
        if (
            (
                self.available_surplus_w + self.usable_battery_charge_w
            ) >= self.load_power_w
            and (self.is_load_on or self.battery_power_state == "charging")
        ):
            return True

        forecast_remaining_kwh = self.forecast_remaining_today_kwh
        battery_charge_required_kwh = self.battery_charge_required_kwh
        if (
            forecast_remaining_kwh is None
            or battery_charge_required_kwh is None
        ):
            return False

        return (
            forecast_remaining_kwh
            >= battery_charge_required_kwh * HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO
            and self.available_surplus_w >= self.load_power_w
        )

    def _should_prioritize_battery_after_runtime(self) -> bool:
        """Return whether the battery should win over optional high-mode runtime."""
        if self.runtime_remaining_today_minutes > 0:
            return False

        battery_headroom_kwh = self._battery_headroom_to_target_kwh(
            HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC
        )
        battery_charge_required_kwh = self._charging_input_energy_for_storage(
            battery_headroom_kwh
        )
        if (
            battery_headroom_kwh is not None
            and battery_headroom_kwh <= HIGH_FORECAST_POST_RUNTIME_BATTERY_HEADROOM_KWH
        ):
            return False

        battery_soc = self.battery_soc
        if battery_soc is None:
            return self.battery_power_state == "charging"

        if battery_soc >= HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC:
            return False

        forecast_remaining_kwh = self.forecast_remaining_today_kwh
        if (
            forecast_remaining_kwh is None
            or battery_charge_required_kwh is None
        ):
            return True

        household_reserve_kwh = self.high_mode_household_reserve_kwh
        return (
            forecast_remaining_kwh
            < battery_charge_required_kwh
            + household_reserve_kwh
            + self.high_mode_time_priority_buffer_kwh
        )

    def _allow_post_runtime_export_guard_restart(self) -> bool:
        """Return whether a post-runtime high-mode restart is justified."""
        return allow_post_runtime_export_guard_restart(
            is_load_on=self.is_load_on,
            runtime_remaining_minutes=self.runtime_remaining_today_minutes,
            available_surplus_w=self.available_surplus_w,
            effective_solar_surplus_w=self.effective_solar_surplus_w,
            load_power_w=self.load_power_w,
            forecast_next_hour_kwh=self.forecast_next_hour_kwh,
            restart_surplus_margin_w=(
                HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W
            ),
            next_hour_ratio=HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO,
        )

    @property
    def _high_forecast_grid_import_active(self) -> bool:
        """Return whether high mode import has exceeded the shutdown delay."""
        return (
            self.high_forecast_grid_import_duration_seconds
            >= GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()
        )

    @property
    def _forecast_enabled(self) -> bool:
        """Return whether forecast logic is enabled."""
        return True

    @property
    def _forecast_remaining_kwh(self) -> float | None:
        """Return remaining forecast energy today in kWh."""
        if not self._forecast_enabled:
            return None
        return self._energy_sensor_kwh(self.config.get(CONF_FORECAST_REMAINING_TODAY_SENSOR))

    @property
    def _forecast_today_kwh(self) -> float | None:
        """Return forecast energy for today in kWh."""
        if not self._forecast_enabled:
            return None
        return self._energy_sensor_kwh(self.config.get(CONF_FORECAST_TODAY_SENSOR))

    @property
    def _forecast_next_hour_kwh(self) -> float | None:
        """Return forecast energy for the next hour in kWh."""
        if not self._forecast_enabled:
            return None
        return self._energy_sensor_kwh(self.config.get(CONF_FORECAST_NEXT_HOUR_SENSOR))

    @property
    def _forecast_is_insufficient_for_remaining_runtime(self) -> bool:
        """Return whether forecast energy cannot cover remaining runtime."""
        forecast_remaining_kwh = self._forecast_remaining_kwh
        if forecast_remaining_kwh is None:
            return False
        return forecast_remaining_kwh < self.required_remaining_energy_kwh

    @property
    def _should_wait_for_forecast(self) -> bool:
        """Return whether good forecast justifies waiting instead of forcing."""
        if not self._forecast_enabled:
            return False
        if self._forecast_is_insufficient_for_remaining_runtime:
            return False

        if self.forecast_day_class == FORECAST_DAY_MODE_LOW:
            return should_wait_for_low_mode_forecast(
                forecast_remaining_kwh=self._forecast_remaining_kwh,
                forecast_next_hour_kwh=self._forecast_next_hour_kwh,
                slack_minutes=self.low_mode_runtime_slack_minutes,
                wait_buffer_minutes=self.low_mode_runtime_wait_buffer_minutes,
                load_power_w=self.load_power_w,
                wait_minutes=DEFAULT_FORECAST_WAIT_MINUTES,
                pressure=self.low_mode_runtime_pressure,
                min_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
                max_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
            )

        next_hour_kwh = self._forecast_next_hour_kwh
        if next_hour_kwh is None:
            return self._forecast_remaining_kwh is not None

        load_power_w = _as_float(
            self.config.get(CONF_LOAD_POWER_W),
            DEFAULT_LOAD_POWER_W,
        )
        needed_next_hour_kwh = load_power_w * DEFAULT_FORECAST_WAIT_MINUTES / 60 / 1000
        return next_hour_kwh >= needed_next_hour_kwh

    def _minutes_since(self, started_at: datetime) -> float:
        """Return minutes since a UTC timestamp."""
        return max(0.0, (dt_util.utcnow() - started_at).total_seconds() / 60)


def today() -> date:
    """Return today's date in the Home Assistant timezone."""
    return dt_util.now().date()


def _as_float(value: Any, default: float | None = None) -> float | None:
    """Return value as float if possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _parse_time(value: Any, default: str) -> time:
    """Parse a Home Assistant time selector value."""
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            parts = [int(part) for part in value.split(":")]
            return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
        except (TypeError, ValueError, IndexError):
            pass
    return _parse_time(default, "21:00")


def _append_debug_decision_log(path: str, record: dict[str, Any]) -> None:
    """Append a decision debug record and prune old history."""
    cutoff_epoch = (
        float(record["timestamp_epoch"]) - DEBUG_DECISION_LOG_RETENTION_DAYS * 86400
    )
    records: list[dict[str, Any]] = []

    try:
        with open(path, encoding="utf-8") as file:
            for line in file:
                try:
                    existing = json.loads(line)
                except json.JSONDecodeError:
                    continue

                timestamp_epoch = existing.get("timestamp_epoch")
                if not isinstance(timestamp_epoch, int | float):
                    records.append(existing)
                elif timestamp_epoch >= cutoff_epoch:
                    records.append(existing)
    except FileNotFoundError:
        pass

    records.append(record)
    records = records[-DEBUG_DECISION_LOG_MAX_ENTRIES:]

    with open(path, "w", encoding="utf-8") as file:
        for item in records:
            file.write(json.dumps(item, separators=(",", ":")))
            file.write("\n")
