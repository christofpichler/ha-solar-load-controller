"""Shared runtime and decision state for Solar Load Controller."""

from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.event import (
    async_track_state_change_event,
    async_track_point_in_time,
    async_track_time_change,
    async_track_time_interval,
)
from homeassistant.util import dt as dt_util

from .const import (
    BATTERY_MODE_PRESERVE,
    BATTERY_MODE_USE,
    CONF_BATTERY_MODE,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_LOAD_POWER_W,
    CONF_LOAD_SWITCH,
    CONF_MIN_BATTERY_SOC,
    CONF_MIN_DAILY_RUNTIME_MINUTES,
    CONF_MIN_ON_MINUTES,
    CONF_PV_CURRENT_POWER_SENSOR,
    DECISION_AUTOMATION_PAUSED,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DEFAULT_FORECAST_WAIT_MINUTES,
    DEFAULT_LOAD_POWER_W,
    DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
)
from .controller_metrics import ControllerMetricsMixin
from .decision_engine import DecisionResult, evaluate_decision
from .decision_debug import DecisionDebugMixin
from .decision_inputs import DecisionInputsMixin
from .forecast_tracker import (
    ForecastTrackerMixin,
    ForecastTracker,
)
from .grid_import_tracker import (
    GridImportMixin,
    GridImportTracker,
    start_margin_w,
)
from .load_controller import LoadControlMixin, LoadControlState
from .persisted_state import (
    PersistedControllerState,
    async_load_runtime_state,
    async_save_runtime_state,
)
from .runtime_tracker import RuntimeTracker
from .sensor_reader import SensorReader, SensorReaderMixin, as_float as _as_float
from .time_window import (
    _FALLBACK_TIME,
    parse_time as _parse_time,
    TimeWindowMixin,
    today,
)
from .high_mode import (
    allow_post_runtime_export_guard_restart,
    export_guard_run_available,
    should_prioritize_battery_after_runtime,
    HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO,
    no_grid_import_tolerance_w,
    HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC,
    HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W,
    HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO,
)
from .low_mode import (
    forecast_assisted_run_available as low_mode_forecast_assisted_run_available,
    should_wait_for_forecast as should_wait_for_low_mode_forecast,
    should_force_runtime as should_force_low_mode_runtime,
    LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
    LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
    LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
    LOW_FORECAST_ASSISTED_HOLD_MINUTES,
    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
    LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_SURPLUS_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_FORECAST_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_COLLAPSE_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_SUPPORT_TIME_CONSTANT_SECONDS,
)
from .mid_mode import (
    MID_FORECAST_ASSISTED_HOLD_MINUTES,
    forecast_assisted_run_available as mid_mode_forecast_assisted_run_available,
    should_wait_for_mid_forecast,
)

_LOGGER = logging.getLogger(__name__)

# Intentionally set to 0 (disabled). The cooldown infrastructure exists for
# future use but currently has no practical effect on restart behavior.
GRID_IMPORT_RESTART_COOLDOWN = timedelta(seconds=0)
GRID_IMPORT_SHUTDOWN_DELAY = timedelta(seconds=15)
BATTERY_CHARGING_EFFICIENCY = 0.9
PENDING_LOAD_STATE_TIMEOUT = timedelta(seconds=30)
# Storage schema version for the persistent runtime-latch state.
_PERSIST_STORE_VERSION = 1

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


class SolarLoadController(
    DecisionDebugMixin,
    DecisionInputsMixin,
    ForecastTrackerMixin,
    ControllerMetricsMixin,
    GridImportMixin,
    LoadControlMixin,
    SensorReaderMixin,
    TimeWindowMixin,
):
    """Track daily load statistics and calculate decision state."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the controller."""
        self.hass = hass
        self.entry = entry
        self.config = {**entry.data, **entry.options}
        self.load_entity_id = self.config[CONF_LOAD_SWITCH]
        self.automation_paused = False
        self._applying_decision = False
        self._last_logged_decision_signature: tuple[bool, str, str] | None = None

        self._sensor_reader = SensorReader(hass, self.config)
        self._load_control = LoadControlState()
        self._grid_import = GridImportTracker()
        self._forecast = ForecastTracker()
        self._tracker: RuntimeTracker = RuntimeTracker()
        self._runtime_force_latched = False
        self._low_assist_hold_support_w = 0.0
        self._low_assist_hold_support_updated_at: datetime | None = None
        self._last_turned_off_at: datetime | None = None
        self._last_turned_on_at: datetime | None = None
        self._runtime_completion_unsubscribe: Callable[[], None] | None = None

        self._listeners: set[Callable[[], None]] = set()
        self._unsubscribers: list[Callable[[], None]] = []

        # Persistent storage for state that must survive HA restarts (latch, timestamps).
        self._persisted = PersistedControllerState(
            hass,
            _PERSIST_STORE_VERSION,
            entry.entry_id,
        )
        # Keep _store available for existing focused tests and diagnostics.
        self._store = self._persisted.store

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

        # Restore latched runtime state from previous session before the first
        # decision so the forced-runtime latch survives a mid-day HA restart.
        await self.async_load_persist_state()

        if self.is_load_on:
            now = dt_util.utcnow()
            self._tracker.start_tracking(now)
            self._last_turned_on_at = now
            self._refresh_active_runtime_reason()
            self._async_schedule_runtime_completion_check(now)

        self.hass.async_create_task(self._async_apply_decision())

    def async_stop(self) -> None:
        """Stop tracking changes."""
        self._async_cancel_runtime_completion_check()
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
        self._load_control.set_automation_paused(paused, is_load_on=self.is_load_on)
        if paused:
            if self._runtime_force_latched:
                self._runtime_force_latched = False
                self.hass.async_create_task(self._async_save_persist_state())
            self._async_cancel_runtime_completion_check()
        if not paused and self.is_load_on:
            self._async_schedule_runtime_completion_check()
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def async_set_forecast_day_mode_override(self, mode: str) -> None:
        """Set a manual forecast day mode override for diagnostics."""
        if mode not in {
            FORECAST_DAY_MODE_AUTO,
            FORECAST_DAY_MODE_LOW,
            FORECAST_DAY_MODE_MID,
            FORECAST_DAY_MODE_HIGH,
        }:
            return
        self._forecast.set_mode_override(mode)
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def async_restore_stat(self, stat_key: str, value: float, stat_date: str) -> None:
        """Restore one daily statistic after Home Assistant restarts."""
        if stat_date != today().isoformat():
            return

        self._tracker.restore(stat_key, value)

        self._async_notify_listeners()

    async def async_load_persist_state(self) -> None:
        """Restore persisted runtime-latch state after a Home Assistant restart.

        Only restores data that belongs to the current calendar day.  Stale data
        from a previous day is discarded so a new day always starts clean.

        Restored fields
        ---------------
        * ``_runtime_force_latched`` – ensures an in-progress forced runtime
          run survives a mid-day HA restart.
        * ``_last_turned_off_at`` – preserves the min-off timer context so the
          pump does not turn on too soon immediately after restart.
        """
        if (
            hasattr(self, "_persisted")
            and getattr(self._persisted, "store", None) is self._store
        ):
            state = await self._persisted.async_load(today_iso=today().isoformat())
        else:
            state = await async_load_runtime_state(
                self._store,
                today_iso=today().isoformat(),
            )
        if state is None:
            return
        self._runtime_force_latched = state.runtime_force_latched
        self._last_turned_off_at = state.last_turned_off_at

    async def _async_save_persist_state(self) -> None:
        """Save runtime-latch state to persistent storage.

        Called whenever ``_runtime_force_latched`` or ``_last_turned_off_at``
        change so the state survives a Home Assistant restart.
        """
        if (
            hasattr(self, "_persisted")
            and getattr(self._persisted, "store", None) is self._store
        ):
            await self._persisted.async_save(
                today_iso=today().isoformat(),
                runtime_force_latched=self._runtime_force_latched,
                last_turned_off_at=self._last_turned_off_at,
            )
        else:
            await async_save_runtime_state(
                self._store,
                today_iso=today().isoformat(),
                runtime_force_latched=self._runtime_force_latched,
                last_turned_off_at=self._last_turned_off_at,
            )

    @property
    def is_load_on(self) -> bool:
        """Return whether the configured load is currently on."""
        state = self.hass.states.get(self.load_entity_id)
        return state is not None and state.state == STATE_ON

    @property
    def runtime_today_minutes(self) -> float:
        """Return total runtime today in minutes."""
        return round(self._tracker.runtime_today_seconds / 60, 1)

    @property
    def solar_runtime_today_minutes(self) -> float:
        """Return solar-surplus runtime today in minutes."""
        return round(self._tracker.solar_runtime_today_seconds / 60, 1)

    @property
    def forced_runtime_today_minutes(self) -> float:
        """Return forced runtime today in minutes."""
        return round(self._tracker.forced_runtime_today_seconds / 60, 1)

    @property
    def energy_today_kwh(self) -> float:
        """Return estimated energy used today in kWh."""
        load_power_w = _as_float(
            self.config.get(CONF_LOAD_POWER_W),
            DEFAULT_LOAD_POWER_W,
        )
        return round((self._tracker.runtime_today_seconds / 3600) * load_power_w / 1000, 3)

    @property
    def switch_cycles_today(self) -> int:
        """Return number of automatic on cycles today."""
        return self._tracker.switch_cycles

    @property
    def debug_state_config_keys(self) -> tuple[str, ...]:
        """Return config keys included in decision debug state snapshots."""
        return DEBUG_STATE_CONFIG_KEYS

    @callback
    def _async_record_automatic_switch_on(self) -> None:
        """Notify listeners that an automatic switch-on cycle was recorded."""
        self._async_notify_listeners()

    @property
    def grid_import_shutdown_delay_seconds(self) -> float:
        """Return grid-import shutdown delay in seconds."""
        return GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()

    @property
    def grid_import_start_margin_w(self) -> float:
        """Return margin subtracted from the import limit before starts."""
        return start_margin_w(self.load_power_w)

    @property
    def grid_import_restart_cooldown(self) -> timedelta:
        """Return the grid-import restart cooldown."""
        return GRID_IMPORT_RESTART_COOLDOWN

    @property
    def high_forecast_grid_import_shutdown_delay_seconds(self) -> float:
        """Return high-forecast grid-import shutdown delay in seconds."""
        return GRID_IMPORT_SHUTDOWN_DELAY.total_seconds()

    @property
    def battery_charging_efficiency(self) -> float:
        """Return configured internal battery charging efficiency constant."""
        return BATTERY_CHARGING_EFFICIENCY

    @property
    def pending_load_state_timeout(self) -> timedelta:
        """Return pending service-call timeout."""
        return PENDING_LOAD_STATE_TIMEOUT

    @property
    def decision(self) -> DecisionResult:
        """Return the current load decision state."""
        return evaluate_decision(self._decision_inputs)

    @callback
    def _async_state_changed(self, event: Event) -> None:
        """Handle tracked entity state changes."""
        if event.data.get("entity_id") == self.load_entity_id:
            self._async_load_state_changed(event)
        else:
            if self._tracker.is_tracking:
                self._tracker.commit(dt_util.utcnow())
            self._capture_daily_forecast_if_needed()
            self._async_update_grid_import_tracking()
            self._refresh_active_runtime_reason()
            self._async_update_low_assist_hold_support()
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
            if self._load_control.pending_automatic_turn_on:
                self._tracker.start_tracking(now, automatic=True)
                self._tracker.set_reason(self._load_control.pending_decision_reason)
                self._async_record_automatic_switch_on()
            else:
                self._tracker.start_tracking(now)
                self._tracker.set_reason(None)
            self._last_turned_on_at = now
            self._grid_import.clear_shutdown()
            self._async_schedule_runtime_completion_check(now)
        elif old_is_on and not new_is_on:
            self._tracker.commit(dt_util.utcnow())
            self._tracker.stop_tracking()
            self._tracker.set_reason(None)
            self._last_turned_off_at = dt_util.utcnow()
            self._async_cancel_runtime_completion_check()
            self._grid_import.reset_running_timers()
            if (
                change_source == "manual"
                or self.runtime_remaining_today_minutes <= 0
            ):
                self._runtime_force_latched = False
            # Persist the updated latch + turn-off time so a restart immediately
            # after the pump stops still sees the correct min-off / latch state.
            self.hass.async_create_task(self._async_save_persist_state())

        if old_is_on != new_is_on:
            self._async_clear_pending_load_state()
        else:
            self._async_clear_pending_load_state(new_is_on)
        self._async_update_grid_import_tracking()
        self._async_update_low_assist_hold_support()
        if old_is_on != new_is_on and change_source == "manual":
            self._async_log_manual_load_change(new_is_on)
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_periodic_update(self, now: datetime) -> None:
        """Commit active runtime while the load is running."""
        if self._tracker.is_tracking:
            self._tracker.commit(now)
        if self.is_load_on:
            self._async_schedule_runtime_completion_check(now)
        else:
            self._async_cancel_runtime_completion_check()
        self._capture_daily_forecast_if_needed()
        self._async_update_grid_import_tracking(now)
        self._refresh_active_runtime_reason()
        self._async_update_low_assist_hold_support(now)
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_midnight_reset(self, now: datetime) -> None:
        """Reset daily statistics at midnight."""
        midnight_now = dt_util.utcnow()
        self._tracker.midnight_reset(is_on=self.is_load_on, now=midnight_now)
        self._runtime_force_latched = False
        if self.is_load_on:
            self._last_turned_on_at = midnight_now
            self._last_turned_off_at = None
            self._refresh_active_runtime_reason()
            self._async_schedule_runtime_completion_check(now)
        else:
            self._async_cancel_runtime_completion_check()
        self._async_clear_pending_load_state(self.is_load_on)
        self._grid_import.reset_all()
        self._forecast.reset()
        self._low_assist_hold_support_w = 0.0
        self._low_assist_hold_support_updated_at = None
        # Persist the cleared latch immediately so the new day's storage is
        # written before any restart could replay yesterday's forced-run latch.
        self.hass.async_create_task(self._async_save_persist_state())
        self._async_notify_listeners()
        self.hass.async_create_task(self._async_apply_decision())

    @callback
    def _async_cancel_runtime_completion_check(self) -> None:
        """Cancel the exact runtime completion callback if one exists."""
        if self._runtime_completion_unsubscribe is not None:
            self._runtime_completion_unsubscribe()
            self._runtime_completion_unsubscribe = None

    @callback
    def _async_schedule_runtime_completion_check(
        self,
        now: datetime | None = None,
    ) -> None:
        """Schedule an exact callback for the current runtime completion moment."""
        self._async_cancel_runtime_completion_check()
        if self.automation_paused or not self.is_load_on:
            return

        runtime_remaining_minutes = self.runtime_remaining_today_minutes
        if runtime_remaining_minutes <= 0:
            return

        now = now or dt_util.utcnow()
        completion_at = now + timedelta(minutes=runtime_remaining_minutes)
        self._runtime_completion_unsubscribe = async_track_point_in_time(
            self.hass,
            self._async_runtime_completion_check,
            completion_at,
        )

    @callback
    def _async_runtime_completion_check(self, now: datetime) -> None:
        """Force a decision refresh when the exact runtime target is reached."""
        self._runtime_completion_unsubscribe = None
        if self._tracker.is_tracking:
            self._tracker.commit(now)
        self._async_update_grid_import_tracking(now)
        self._refresh_active_runtime_reason()
        self._async_update_low_assist_hold_support(now)
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
            # Capture latch state BEFORE self.decision is evaluated.
            # self.decision → _must_force_minimum_runtime can clear the latch
            # (runtime_remaining <= 0), so capturing after would miss the change.
            _latch_before = self._runtime_force_latched
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
            if self._runtime_force_latched != _latch_before:
                self.hass.async_create_task(self._async_save_persist_state())
            self._async_log_decision_if_changed(decision)
            if decision.reason == DECISION_AUTOMATION_PAUSED:
                if not self.is_load_on:
                    return  # pump already off, nothing to do
                if self._load_control.should_respect_manual_on_while_paused(
                    is_load_on=self.is_load_on,
                    timeout=PENDING_LOAD_STATE_TIMEOUT,
                ):
                    # Pump is on but we have no pending turn-off and the
                    # coordinator did not initiate this: the user manually
                    # turned on the load while paused.  Respect manual control.
                    return
                # Clear the flag so subsequent calls leave the pump alone
                # once the turn-off has been issued.
                self._load_control.consume_paused_turn_off()
                # Fall through to issue the turn_off service call.
            if decision.should_run == self.is_load_on:
                return
            if self._pending_load_state_matches(decision.should_run):
                return

            domain, _, _object_id = self.load_entity_id.partition(".")
            if domain not in {"switch", "input_boolean"}:
                _LOGGER.warning(
                    "Load entity '%s' has unsupported domain '%s'. "
                    "Only 'switch' and 'input_boolean' are supported. "
                    "No service call will be made.",
                    self.load_entity_id,
                    domain,
                )
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
                    self._grid_import.record_shutdown()
            except Exception:
                self._async_clear_pending_load_state()
                raise
        finally:
            self._applying_decision = False

    @callback
    def _async_notify_listeners(self) -> None:
        """Notify all subscribed entities."""
        for listener in list(self._listeners):
            listener()

    def _refresh_active_runtime_reason(self) -> None:
        """Refresh the source category for the current active runtime interval."""
        if not self.is_load_on:
            self._tracker.set_reason(None)
            return

        reason = self.decision.reason
        if reason in {
            DECISION_SOLAR_SURPLUS_AVAILABLE,
            DECISION_FORECAST_ASSISTED_RUN,
            DECISION_LOW_FORECAST_ASSISTED_RUN,
            DECISION_EXPORT_GUARD,
            DECISION_MINIMUM_RUNTIME_REQUIRED,
        }:
            self._tracker.set_reason(reason)

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
            if soc <= minimum_soc:
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
    def _mid_forecast_assisted_run_available(self) -> bool:
        """Return whether mid mode may start the load with partial solar coverage."""
        is_currently_assisting = (
            self.is_load_on
            and self._tracker.active_runtime_reason == DECISION_FORECAST_ASSISTED_RUN
            and self._last_turned_on_at is not None
        )
        minutes_since_turn_on = (
            self._minutes_since(self._last_turned_on_at)
            if self._last_turned_on_at is not None
            else None
        )
        return mid_mode_forecast_assisted_run_available(
            is_currently_assisting=is_currently_assisting,
            minutes_since_turn_on=minutes_since_turn_on,
            projected_grid_import_exceeds_limit=self._projected_grid_import_exceeds_limit,
            available_surplus_w=self.available_surplus_w,
            effective_solar_surplus_w=self.mid_mode_solar_surplus_w,
            load_power_w=self.load_power_w,
            battery_power_state=self.battery_power_state,
            is_load_on=self.is_load_on,
            battery_power_w=self.battery_power_w,
            assisted_hold_minutes=MID_FORECAST_ASSISTED_HOLD_MINUTES,
        )

    @property
    def _forecast_assisted_run_available(self) -> bool:
        """Return whether mid-day forecast assistance may run the load."""
        day_class = self.forecast_day_class
        if day_class not in (FORECAST_DAY_MODE_LOW, FORECAST_DAY_MODE_MID):
            return False

        runtime_remaining_minutes = self.runtime_remaining_today_minutes
        if runtime_remaining_minutes <= 0:
            return False
        # If the force-runtime window is already active, let the engine use
        # must_force_minimum_runtime (runtime_force) instead of forecast_run.
        # This prevents mid-mode from suppressing the latch that keeps the
        # load running even when solar later collapses.
        if self._must_force_minimum_runtime(runtime_remaining_minutes):
            return False

        if day_class == FORECAST_DAY_MODE_MID:
            return self._mid_forecast_assisted_run_available

        is_currently_assisting = (
            self.is_load_on
            and self._tracker.active_runtime_reason == DECISION_LOW_FORECAST_ASSISTED_RUN
            and self._last_turned_on_at is not None
        )
        minutes_since_turn_on = (
            self._minutes_since(self._last_turned_on_at)
            if self._last_turned_on_at is not None
            else None
        )
        min_on_minutes = _as_float(
            self.config.get(CONF_MIN_ON_MINUTES),
            DEFAULT_MIN_ON_MINUTES,
        )
        return low_mode_forecast_assisted_run_available(
            is_currently_assisting=is_currently_assisting,
            minutes_since_turn_on=minutes_since_turn_on,
            configured_min_on_minutes=min_on_minutes,
            assisted_hold_minutes=LOW_FORECAST_ASSISTED_HOLD_MINUTES,
            projected_grid_import_exceeds_limit=self._projected_grid_import_exceeds_limit,
            forecast_next_hour_kwh=self._forecast_next_hour_kwh,
            forecast_wait_threshold_kwh=self.low_mode_forecast_wait_threshold_kwh,
            effective_solar_surplus_w=self.low_mode_assisted_start_surplus_w,
            hold_support_w=self.low_mode_assisted_hold_support_w,
            required_surplus_w=self.low_mode_assisted_surplus_threshold_w,
            assist_priority=self.low_mode_assisted_priority,
            available_surplus_w=self.available_surplus_w,
            load_power_w=self.load_power_w,
            battery_power_state=self.battery_power_state,
            forecast_override_ratio_span=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
            forecast_override_exponent=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
            surplus_late_relief_ratio=LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
            forecast_late_relief_ratio=LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
            hold_surplus_ratio=LOW_FORECAST_ASSISTED_HOLD_SURPLUS_RATIO,
            hold_forecast_ratio=LOW_FORECAST_ASSISTED_HOLD_FORECAST_RATIO,
            collapse_floor_ratio=LOW_FORECAST_ASSISTED_HOLD_COLLAPSE_RATIO,
        )

    @property
    def _export_guard_run_available(self) -> bool:
        """Return whether forecast suggests running now to avoid clipping later."""
        return export_guard_run_available(
            forecast_day_class=self.forecast_day_class,
            high_forecast_day_class=FORECAST_DAY_MODE_HIGH,
            is_load_on=self.is_load_on,
            grid_import_w=self.grid_import_w,
            grid_import_no_grid_tolerance_w=no_grid_import_tolerance_w(
                self.load_power_w
            ),
            high_forecast_grid_import_active=self._high_forecast_grid_import_active,
            should_prioritize_battery=self._should_prioritize_battery_after_runtime(),
            allow_post_runtime_restart=self._allow_post_runtime_export_guard_restart(),
            available_surplus_w=self.available_surplus_w,
            usable_battery_charge_w=self.usable_battery_charge_w,
            load_power_w=self.load_power_w,
            battery_power_state=self.battery_power_state,
            pv_current_power_w=self.pv_current_power_w,
            forecast_remaining_kwh=self.forecast_remaining_today_kwh,
            battery_charge_required_kwh=self.battery_charge_required_kwh,
            curtailment_headroom_ratio=HIGH_FORECAST_CURTAILMENT_HEADROOM_RATIO,
        )

    def _should_prioritize_battery_after_runtime(self) -> bool:
        """Return whether the battery should win over optional high-mode runtime."""
        battery_headroom_kwh = self._battery_headroom_to_target_kwh(
            HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC
        )
        battery_charge_required_kwh = self._charging_input_energy_for_storage(
            battery_headroom_kwh
        )
        return should_prioritize_battery_after_runtime(
            forecast_day_class=self.forecast_day_class,
            high_forecast_day_class=FORECAST_DAY_MODE_HIGH,
            runtime_remaining_minutes=self.runtime_remaining_today_minutes,
            battery_headroom_kwh=battery_headroom_kwh,
            battery_charge_required_kwh=battery_charge_required_kwh,
            battery_soc=self.battery_soc,
            battery_power_state=self.battery_power_state,
            forecast_remaining_kwh=self.forecast_remaining_today_kwh,
            household_reserve_kwh=self.high_mode_household_reserve_kwh,
            time_priority_buffer_kwh=self.high_mode_time_priority_buffer_kwh,
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
    def _forecast_is_insufficient_for_remaining_runtime(self) -> bool:
        """Return whether forecast energy cannot cover remaining runtime."""
        forecast_remaining_kwh = self._forecast_remaining_kwh
        if forecast_remaining_kwh is None:
            return False
        return forecast_remaining_kwh < self.required_remaining_energy_kwh

    @property
    def _should_wait_for_forecast(self) -> bool:
        """Return whether good forecast justifies waiting instead of forcing."""
        if self._forecast_is_insufficient_for_remaining_runtime:
            return False

        day_class = self.forecast_day_class

        if day_class == FORECAST_DAY_MODE_LOW:
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

        if day_class == FORECAST_DAY_MODE_MID:
            return should_wait_for_mid_forecast(
                forecast_remaining_kwh=self._forecast_remaining_kwh,
                forecast_next_hour_kwh=self._forecast_next_hour_kwh,
                slack_minutes=self.runtime_slack_minutes,
                load_power_w=self.load_power_w,
                wait_minutes=DEFAULT_FORECAST_WAIT_MINUTES,
            )

        # High mode: wait if next-hour forecast is strong enough.
        next_hour_kwh = self._forecast_next_hour_kwh
        if next_hour_kwh is None:
            return self._forecast_remaining_kwh is not None

        load_power_w = _as_float(
            self.config.get(CONF_LOAD_POWER_W),
            DEFAULT_LOAD_POWER_W,
        )
        needed_next_hour_kwh = load_power_w * DEFAULT_FORECAST_WAIT_MINUTES / 60 / 1000
        return next_hour_kwh >= needed_next_hour_kwh
