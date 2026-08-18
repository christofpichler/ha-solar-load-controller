"""Decision debug record assembly for Solar Load Controller."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .const import CONF_DEBUG_SENSOR_ENABLED
from .decision_log import (
    DECISION_LOG_FILENAME,
    DECISION_LOG_MAX_ENTRIES,
    DECISION_LOG_RETENTION_DAYS,
    append_decision_log,
)
from .high_mode import (
    no_grid_import_tolerance_w,
    HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC,
    HIGH_FORECAST_POST_RUNTIME_NEXT_HOUR_RATIO,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS,
    HIGH_FORECAST_POST_RUNTIME_RESTART_SURPLUS_MARGIN_W,
)
from .low_mode import (
    LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
    LOW_FORECAST_ASSISTED_HOLD_COLLAPSE_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_FORECAST_RATIO,
    LOW_FORECAST_ASSISTED_HOLD_MINUTES,
    LOW_FORECAST_ASSISTED_HOLD_SUPPORT_TIME_CONSTANT_SECONDS,
    LOW_FORECAST_ASSISTED_HOLD_SURPLUS_RATIO,
    LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT,
    LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO,
    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO,
    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
    LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
    LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
    LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
)

_LOGGER = logging.getLogger("custom_components.solar_load_controller.coordinator")


def build_decision_log_record(
    view,
    decision,
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
            "entry_id": view.entry.entry_id,
            "title": view.entry.title,
        },
        "retention": {
            "days": DECISION_LOG_RETENTION_DAYS,
            "max_entries": DECISION_LOG_MAX_ENTRIES,
        },
        "load": {
            "entity_id": view.load_entity_id,
            "is_on": view.is_load_on,
        },
        "settings": {
            "load_power_w": view.load_power_w,
            "grid_import_limit_w": view.grid_import_limit_w,
            "grid_import_shutdown_delay_seconds": (
                view.grid_import_shutdown_delay_seconds
            ),
            "high_grid_import_tolerance_w": no_grid_import_tolerance_w(
                view.load_power_w
            ),
            "battery_charging_efficiency": view.battery_charging_efficiency,
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
            "low_forecast_assisted_hold_surplus_ratio": (
                LOW_FORECAST_ASSISTED_HOLD_SURPLUS_RATIO
            ),
            "low_forecast_assisted_hold_forecast_ratio": (
                LOW_FORECAST_ASSISTED_HOLD_FORECAST_RATIO
            ),
            "low_forecast_assisted_hold_collapse_ratio": (
                LOW_FORECAST_ASSISTED_HOLD_COLLAPSE_RATIO
            ),
            "low_forecast_assisted_hold_support_time_constant_seconds": (
                LOW_FORECAST_ASSISTED_HOLD_SUPPORT_TIME_CONSTANT_SECONDS
            ),
            "high_mode_base_household_load_w": (
                view.high_mode_base_household_load_w
            ),
            "high_mode_household_reserve_margin_percent": (
                view.high_mode_household_reserve_margin_percent
            ),
            "min_runtime_battery_override": view.min_runtime_battery_override,
            "min_runtime_grid_override": view.min_runtime_grid_override,
            "forecast_day_mode_override": view.forecast_day_mode_override,
        },
        "states": view._debug_input_states(),
        "decision": decision.as_debug_dict(),
    }


class DecisionDebugMixin:
    """Controller debug-sensor and JSONL logging helpers."""

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
            "path": self.hass.config.path(DECISION_LOG_FILENAME),
            "format": "jsonl",
            "retention_days": DECISION_LOG_RETENTION_DAYS,
            "max_entries": DECISION_LOG_MAX_ENTRIES,
        }

    @callback
    def _async_log_decision_if_changed(self, decision) -> None:
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
        path = self.hass.config.path(DECISION_LOG_FILENAME)
        try:
            await self.hass.async_add_executor_job(
                append_decision_log,
                path,
                record,
            )
        except OSError as err:
            _LOGGER.warning("Could not write decision debug log: %s", err)

    def _decision_log_record(
        self,
        decision,
        *,
        event: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Return one JSON-serializable decision log record."""
        return build_decision_log_record(self, decision, event=event)
