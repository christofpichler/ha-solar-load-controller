"""Sensor state reading helpers for Solar Load Controller."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_PV_SIZE_KWP,
)

_LOGGER = logging.getLogger("custom_components.solar_load_controller.coordinator")

# How long a sensor may report "unavailable"/"unknown" before its last known
# value stops being used. Cloud-backed sensors (inverter and forecast vendors)
# drop out for a single update cycle regularly; treating every blip as a missing
# sensor stops the load and then costs a full min_off window before it can come
# back. Only brief gaps are bridged - a genuinely dead sensor still surfaces as
# missing once the window expires.
SENSOR_UNAVAILABLE_GRACE_SECONDS: float = 180.0


def as_float(value: Any, default: float | None = None) -> float | None:
    """Return value as float if possible."""
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class SensorReader:
    """Read configured Home Assistant states with controller-specific coercion."""

    def __init__(self, hass, config: dict[str, Any]) -> None:
        self.hass = hass
        self.config = config
        self._last_known: dict[str, tuple[float, datetime]] = {}

    def _remember(self, entity_id: str, value: float) -> float:
        """Record a good reading so a later blip can be bridged."""
        self._last_known[entity_id] = (value, dt_util.utcnow())
        return value

    def _bridge_unavailable(
        self,
        entity_id: str,
        label: str,
        *,
        grace_seconds: float = SENSOR_UNAVAILABLE_GRACE_SECONDS,
    ) -> float | None:
        """Return the last known value while a sensor is briefly unavailable.

        Returns None when the sensor was never readable or the gap has grown
        past the grace window, so a real outage still reaches the missing-sensor
        decision path.
        """
        state = self.hass.states.get(entity_id)
        if state is None or str(state.state).lower() not in {
            "unknown",
            "unavailable",
        }:
            return None

        remembered = self._last_known.get(entity_id)
        if remembered is None:
            _LOGGER.debug(
                "%s '%s' is %s and has no previous value; treating as unavailable",
                label,
                entity_id,
                state.state,
            )
            return None

        value, seen_at = remembered
        age = (dt_util.utcnow() - seen_at).total_seconds()
        if age > grace_seconds:
            _LOGGER.debug(
                "%s '%s' is %s and its last value is %.0f s old; "
                "treating as unavailable",
                label,
                entity_id,
                state.state,
                age,
            )
            return None

        _LOGGER.debug(
            "%s '%s' is %s; bridging with last known value %s (%.0f s old)",
            label,
            entity_id,
            state.state,
            value,
            age,
        )
        return value

    def state_as_float(self, entity_id: str | None) -> float | None:
        """Return a state value as float, if possible."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        return as_float(state.state)

    def state_unit(self, entity_id: str | None) -> str | None:
        """Return a state's unit of measurement."""
        if not entity_id:
            return None
        state = self.hass.states.get(entity_id)
        if state is None:
            return None
        unit = state.attributes.get("unit_of_measurement")
        return str(unit) if unit is not None else None

    def positive_state_value(self, entity_id: str | None) -> float | None:
        """Return a positive sensor state value."""
        if not entity_id:
            return None
        value = self.state_as_float(entity_id)
        if value is None:
            value = self._bridge_unavailable(entity_id, "Numeric sensor")
            if value is None:
                return None
        else:
            self._remember(entity_id, value)
        return max(0.0, value)

    def energy_sensor_kwh(self, entity_id: str | None) -> float | None:
        """Return an energy forecast sensor value in kWh."""
        if not entity_id:
            return None
        value = self.state_as_float(entity_id)
        if value is None:
            value = self._bridge_unavailable(entity_id, "Energy sensor")
            if value is None:
                return None
        else:
            self._remember(entity_id, value)

        unit = (self.state_unit(entity_id) or "").lower()
        if unit in {"wh", "w h"}:
            return max(0.0, value / 1000)
        return max(0.0, value)

    def debug_input_states(self, config_keys: tuple[str, ...]) -> dict[str, dict[str, Any]]:
        """Return the raw HA state for configured input entities."""
        states: dict[str, dict[str, Any]] = {}
        for key in config_keys:
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


class SensorReaderMixin:
    """Controller methods backed by SensorReader."""

    def _debug_input_states(self) -> dict[str, dict[str, Any]]:
        """Return the raw HA state for configured input entities."""
        return self._sensor_reader.debug_input_states(self.debug_state_config_keys)

    def _state_as_float(self, entity_id: str | None) -> float | None:
        """Return a state value as float, if possible."""
        return self._sensor_reader.state_as_float(entity_id)

    def _state_unit(self, entity_id: str | None) -> str | None:
        """Return a state's unit of measurement."""
        return self._sensor_reader.state_unit(entity_id)

    def _positive_state_value(self, entity_id: str | None) -> float | None:
        """Return a positive sensor state value."""
        return self._sensor_reader.positive_state_value(entity_id)

    def _energy_sensor_kwh(self, entity_id: str | None) -> float | None:
        """Return an energy forecast sensor value in kWh."""
        return self._sensor_reader.energy_sensor_kwh(entity_id)

    @property
    def _missing_required_grid_sensor_value(self) -> bool:
        """Return whether required sensor values are unavailable."""
        pv_size_kwp = as_float(self.config.get(CONF_PV_SIZE_KWP), 0)
        return (
            self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR)) is None
            or self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))
            is None
            or self._forecast_today_kwh is None
            or pv_size_kwp is None
            or pv_size_kwp <= 0
        )

    @property
    def _forecast_remaining_kwh(self) -> float | None:
        """Return remaining forecast energy today in kWh."""
        return self._energy_sensor_kwh(
            self.config.get(CONF_FORECAST_REMAINING_TODAY_SENSOR)
        )

    @property
    def _forecast_today_kwh(self) -> float | None:
        """Return forecast energy for today in kWh."""
        return self._energy_sensor_kwh(self.config.get(CONF_FORECAST_TODAY_SENSOR))

    @property
    def _forecast_next_hour_kwh(self) -> float | None:
        """Return forecast energy for the next hour in kWh."""
        return self._energy_sensor_kwh(self.config.get(CONF_FORECAST_NEXT_HOUR_SENSOR))
