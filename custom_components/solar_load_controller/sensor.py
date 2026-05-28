"""Sensor entities for the Solar Load Controller integration."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfEnergy, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    CONF_DEBUG_SENSOR_ENABLED,
    DATA_CONTROLLER,
    DECISION_AUTOMATION_PAUSED,
    DECISION_BATTERY_PROTECTED,
    DECISION_BATTERY_PRIORITY,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_FORECAST_WAIT,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_LOW_FORECAST_WAIT,
    DECISION_MINIMUM_OFF_TIME_ACTIVE,
    DECISION_MINIMUM_ON_TIME_ACTIVE,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_MISSING_REQUIRED_SENSOR,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DECISION_TIME_WINDOW_BLOCKED,
    DECISION_WAITING_FOR_SURPLUS,
    DOMAIN,
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
)
from .coordinator import SolarLoadController, today

DECISION_REASON_OPTIONS = [
    DECISION_SOLAR_SURPLUS_AVAILABLE,
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_FORECAST_WAIT,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_LOW_FORECAST_WAIT,
    DECISION_GRID_IMPORT_LIMIT_EXCEEDED,
    DECISION_BATTERY_PROTECTED,
    DECISION_BATTERY_PRIORITY,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_MINIMUM_RUNTIME_REACHED,
    DECISION_AUTOMATION_PAUSED,
    DECISION_WAITING_FOR_SURPLUS,
    DECISION_MISSING_REQUIRED_SENSOR,
    DECISION_MINIMUM_ON_TIME_ACTIVE,
    DECISION_MINIMUM_OFF_TIME_ACTIVE,
    DECISION_TIME_WINDOW_BLOCKED,
]

FORECAST_DAY_MODE_SENSOR_OPTIONS = [
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
    FORECAST_DAY_MODE_HIGH,
    "unknown",
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up sensor entities from a config entry."""
    controller: SolarLoadController = hass.data[DOMAIN][entry.entry_id][
        DATA_CONTROLLER
    ]
    entities: list[SensorEntity] = [
        SolarLoadRuntimeTodaySensor(controller),
        SolarLoadRuntimeRemainingTodaySensor(controller),
        SolarLoadEnergyTodaySensor(controller),
        SolarLoadSwitchCyclesTodaySensor(controller),
        SolarLoadSolarRuntimeTodaySensor(controller),
        SolarLoadForcedRuntimeTodaySensor(controller),
        SolarLoadAvailableSurplusSensor(controller),
        SolarLoadEffectiveSolarSurplusSensor(controller),
        SolarLoadForecastDayModeSensor(controller),
        SolarLoadDecisionReasonSensor(controller),
    ]
    if controller.config.get(CONF_DEBUG_SENSOR_ENABLED):
        entities.append(SolarLoadDecisionDebugSensor(controller))

    async_add_entities(entities)


class SolarLoadBaseSensor(SensorEntity):
    """Base sensor entity for Solar Load Controller."""

    _attr_has_entity_name = True

    def __init__(self, controller: SolarLoadController, key: str) -> None:
        """Initialize the sensor."""
        self.controller = controller
        self._attr_unique_id = f"{controller.entry.entry_id}_{key}"
        self._attr_translation_key = key
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name=controller.entry.title,
            manufacturer="Solar Load Controller",
        )

    async def async_added_to_hass(self) -> None:
        """Subscribe to controller updates."""
        self.async_on_remove(
            self.controller.async_add_listener(self._async_controller_updated)
        )

    @callback
    def _async_controller_updated(self) -> None:
        """Write updated state."""
        self.async_write_ha_state()


class SolarLoadRestoredStatSensor(SolarLoadBaseSensor, RestoreEntity):
    """Base sensor for restored daily statistics."""

    _stat_key: str

    async def async_added_to_hass(self) -> None:
        """Restore previous state and subscribe to updates."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is None:
            return

        stat_date = last_state.attributes.get("date")
        if not isinstance(stat_date, str):
            return

        try:
            value = float(last_state.state)
        except (TypeError, ValueError):
            return

        self.controller.async_restore_stat(self._stat_key, value, stat_date)
        self.async_write_ha_state()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return diagnostic attributes."""
        return {
            "date": today().isoformat(),
            "load_entity_id": self.controller.load_entity_id,
        }


class SolarLoadRuntimeTodaySensor(SolarLoadRestoredStatSensor):
    """Sensor that tracks how long the configured load ran today."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _stat_key = "runtime_today"

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, self._stat_key)

    @property
    def native_value(self) -> float:
        """Return today's runtime in minutes."""
        return self.controller.runtime_today_minutes


class SolarLoadRuntimeRemainingTodaySensor(SolarLoadBaseSensor):
    """Sensor that exposes remaining runtime target for today."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "runtime_remaining_today")

    @property
    def native_value(self) -> float:
        """Return remaining runtime target in minutes."""
        return self.controller.runtime_remaining_today_minutes

class SolarLoadEnergyTodaySensor(SolarLoadBaseSensor):
    """Sensor that estimates today's load energy use."""

    _attr_device_class = SensorDeviceClass.ENERGY
    _attr_native_unit_of_measurement = UnitOfEnergy.KILO_WATT_HOUR

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "energy_today")

    @property
    def native_value(self) -> float:
        """Return estimated energy use in kWh."""
        return self.controller.energy_today_kwh


class SolarLoadSwitchCyclesTodaySensor(SolarLoadRestoredStatSensor):
    """Sensor that counts automatic switch-on cycles today."""

    _stat_key = "switch_cycles_today"

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, self._stat_key)

    @property
    def native_value(self) -> int:
        """Return automatic switch cycles today."""
        return self.controller.switch_cycles_today


class SolarLoadSolarRuntimeTodaySensor(SolarLoadRestoredStatSensor):
    """Sensor that tracks runtime attributed to solar surplus."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _stat_key = "solar_runtime_today"

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, self._stat_key)

    @property
    def native_value(self) -> float:
        """Return solar runtime today in minutes."""
        return self.controller.solar_runtime_today_minutes


class SolarLoadForcedRuntimeTodaySensor(SolarLoadRestoredStatSensor):
    """Sensor that tracks runtime forced by the minimum runtime target."""

    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = UnitOfTime.MINUTES
    _stat_key = "forced_runtime_today"

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, self._stat_key)

    @property
    def native_value(self) -> float:
        """Return forced runtime today in minutes."""
        return self.controller.forced_runtime_today_minutes


class SolarLoadAvailableSurplusSensor(SolarLoadBaseSensor):
    """Sensor that exposes the currently available export surplus."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "available_surplus")

    @property
    def native_value(self) -> float:
        """Return available surplus in watts."""
        return self.controller.available_surplus_w

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return surplus calculation details."""
        return {
            "grid_export_w": self.controller.grid_export_w,
            "grid_import_w": self.controller.grid_import_w,
            "formula": "max(0, grid_export - grid_import)",
        }


class SolarLoadEffectiveSolarSurplusSensor(SolarLoadBaseSensor):
    """Sensor that exposes solar surplus usable for high forecast logic."""

    _attr_device_class = SensorDeviceClass.POWER
    _attr_native_unit_of_measurement = UnitOfPower.WATT

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "effective_solar_surplus")

    @property
    def native_value(self) -> float:
        """Return effective solar surplus in watts."""
        return self.controller.effective_solar_surplus_w

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return effective surplus calculation details."""
        return {
            "available_surplus_w": self.controller.available_surplus_w,
            "battery_charge_w": max(0.0, self.controller.battery_power_w or 0.0),
            "usable_battery_charge_w": self.controller.usable_battery_charge_w,
            "pv_current_power_w": self.controller.pv_current_power_w,
            "inverter_limit_w": self.controller.inverter_limit_w,
            "active_load_w": (
                self.controller.load_power_w if self.controller.is_load_on else 0.0
            ),
            "formula": "available_surplus + usable_battery_charge + active_load",
        }


class SolarLoadForecastDayModeSensor(SolarLoadBaseSensor):
    """Sensor that exposes the active forecast day mode."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = FORECAST_DAY_MODE_SENSOR_OPTIONS

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "forecast_day_mode")

    @property
    def native_value(self) -> str:
        """Return the active forecast day mode."""
        return self.controller.forecast_day_class

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return forecast mode context."""
        return {
            "forecast_day_mode_override": (
                self.controller.forecast_day_mode_override
            ),
            "forecast_today_kwh": self.controller.forecast_today_kwh,
            "forecast_kwh_per_kwp": self.controller.forecast_kwh_per_kwp,
            "daily_forecast_captured_at": (
                self.controller.daily_forecast_captured_at
            ),
        }


class SolarLoadDecisionReasonSensor(SolarLoadBaseSensor):
    """Sensor that exposes the current short decision reason."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = DECISION_REASON_OPTIONS

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "decision_reason")

    @property
    def native_value(self) -> str:
        """Return current decision reason."""
        return self.controller.decision.reason

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return decision context attributes."""
        decision = self.controller.decision
        return {
            "available_surplus_w": decision.available_surplus_w,
            "effective_solar_surplus_w": (
                self.controller.effective_solar_surplus_w
            ),
            "grid_import_w": self.controller.grid_import_w,
            "grid_export_w": self.controller.grid_export_w,
            "grid_import_limit_w": self.controller.grid_import_limit_w,
            "grid_import_start_limit_w": self.controller.grid_import_start_limit_w,
            "grid_import_over_limit_duration_seconds": (
                self.controller.grid_import_over_limit_duration_seconds
            ),
            "grid_import_shutdown_allowed": (
                self.controller.grid_import_shutdown_allowed
            ),
            "grid_import_cooldown_active": (
                self.controller.grid_import_cooldown_active
            ),
            "grid_import_cooldown_remaining_seconds": (
                self.controller.grid_import_cooldown_remaining_seconds
            ),
            "projected_grid_import_w": self.controller.projected_grid_import_w,
            "projected_grid_import_formula": (
                self.controller.projected_grid_import_formula
            ),
            "load_power_w": self.controller.load_power_w,
            "runtime_remaining_minutes": decision.runtime_remaining_minutes,
            "min_runtime_battery_override": (
                self.controller.min_runtime_battery_override
            ),
            "min_runtime_grid_override": self.controller.min_runtime_grid_override,
            "required_remaining_energy_kwh": self.controller.required_remaining_energy_kwh,
            "battery_soc": self.controller.battery_soc,
            "battery_power_raw_w": self.controller.battery_power_raw_w,
            "battery_power_w": self.controller.battery_power_w,
            "battery_power_direction": self.controller.battery_power_direction,
            "battery_power_state": self.controller.battery_power_state,
            "battery_mode": self.controller.battery_mode,
            "battery_headroom_kwh": self.controller.battery_headroom_kwh,
            "battery_charge_required_kwh": (
                self.controller.battery_charge_required_kwh
            ),
            "high_forecast_post_runtime_battery_charge_required_kwh": (
                self.controller.high_forecast_post_runtime_battery_charge_required_kwh
            ),
            "high_mode_base_household_load_w": (
                self.controller.high_mode_base_household_load_w
            ),
            "high_mode_household_reserve_margin_percent": (
                self.controller.high_mode_household_reserve_margin_percent
            ),
            "high_mode_household_reserve_kwh": (
                self.controller.high_mode_household_reserve_kwh
            ),
            "high_mode_time_priority_buffer_kwh": (
                self.controller.high_mode_time_priority_buffer_kwh
            ),
            "forecast_excess_after_battery_kwh": (
                self.controller.forecast_excess_after_battery_kwh
            ),
            "inside_time_window": self.controller.inside_time_window,
            "min_on_active": self.controller.min_on_active,
            "min_on_remaining_minutes": self.controller.min_on_remaining_minutes,
            "min_off_active": self.controller.min_off_active,
            "min_off_remaining_minutes": self.controller.min_off_remaining_minutes,
            "minutes_until_finish": self.controller.minutes_until_finish,
            "forecast_today_kwh": self.controller.forecast_today_kwh,
            "forecast_remaining_today_kwh": self.controller.forecast_remaining_today_kwh,
            "forecast_next_hour_kwh": self.controller.forecast_next_hour_kwh,
            "forecast_kwh_per_kwp": self.controller.forecast_kwh_per_kwp,
            "forecast_day_class": self.controller.forecast_day_class,
            "forecast_day_mode_override": (
                self.controller.forecast_day_mode_override
            ),
            "daily_forecast_captured_at": (
                self.controller.daily_forecast_captured_at
            ),
        }


class SolarLoadDecisionDebugSensor(SolarLoadBaseSensor):
    """Sensor that exposes a detailed decision trace."""

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the sensor."""
        super().__init__(controller, "decision_debug")

    @property
    def native_value(self) -> str:
        """Return the current debug summary."""
        return self.controller.decision_debug_summary

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return detailed decision trace attributes."""
        attributes = self.controller.decision_debug
        attributes["reason_key"] = self.controller.decision.reason
        attributes["summary"] = self.controller.decision_debug_summary
        attributes["debug_log"] = self.controller.decision_debug_log_info
        return attributes
