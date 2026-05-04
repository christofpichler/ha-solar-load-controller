"""Config flow for the Solar Load Controller integration."""

from __future__ import annotations

from datetime import time
from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.const import CONF_NAME
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    BATTERY_MODE_PRESERVE,
    BATTERY_MODE_USE,
    BATTERY_POWER_CHARGING_POSITIVE,
    BATTERY_POWER_DISCHARGING_POSITIVE,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MODE,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_DEBUG_SENSOR_ENABLED,
    CONF_EARLIEST_START_TIME,
    CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    CONF_FORECAST_NEXT_HOUR_SENSOR,
    CONF_FORECAST_REMAINING_TODAY_SENSOR,
    CONF_FORECAST_TODAY_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_LIMIT_W,
    CONF_GRID_IMPORT_SENSOR,
    CONF_INVERTER_LIMIT_W,
    CONF_LATEST_FINISH_TIME,
    CONF_LOAD_POWER_W,
    CONF_LOAD_SWITCH,
    CONF_MIN_BATTERY_SOC,
    CONF_MIN_DAILY_RUNTIME_MINUTES,
    CONF_MIN_RUNTIME_GRID_OVERRIDE,
    CONF_MIN_OFF_MINUTES,
    CONF_MIN_ON_MINUTES,
    CONF_PV_CURRENT_POWER_SENSOR,
    CONF_PV_SIZE_KWP,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_GRID_IMPORT_LIMIT_W,
    DEFAULT_EARLIEST_START_TIME,
    DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    DEFAULT_LATEST_FINISH_TIME,
    DEFAULT_LOAD_POWER_W,
    DEFAULT_MIN_BATTERY_SOC,
    DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
    DEFAULT_MIN_OFF_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
    DOMAIN,
)

class SolarLoadControllerConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solar Load Controller."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize config flow state."""
        self._config_data: dict[str, Any] = {}

    async def async_step_user(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle load settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            await self.async_set_unique_id(user_input[CONF_LOAD_SWITCH])
            self._abort_if_unique_id_configured()
            self._config_data.update(user_input)
            return await self.async_step_runtime()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(_load_schema({})),
        )

    async def async_step_runtime(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle runtime settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._config_data.update(user_input)
            return await self.async_step_energy()

        return self.async_show_form(
            step_id="runtime",
            data_schema=vol.Schema(_runtime_schema({})),
        )

    async def async_step_energy(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle grid, PV, and forecast settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._config_data.update(user_input)
            return await self.async_step_battery()

        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(_energy_schema({})),
        )

    async def async_step_battery(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle optional battery settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._config_data.update(user_input)
            return await self.async_step_advanced()

        return self.async_show_form(
            step_id="battery",
            data_schema=vol.Schema(_battery_schema({})),
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Handle optional battery and diagnostic settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._config_data.update(user_input)
            return self.async_create_entry(
                title=self._config_data[CONF_NAME],
                data=self._config_data,
            )

        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(_advanced_schema({})),
        )

    @staticmethod
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> SolarLoadControllerOptionsFlow:
        """Create the options flow."""
        return SolarLoadControllerOptionsFlow(config_entry)


class SolarLoadControllerOptionsFlow(config_entries.OptionsFlow):
    """Handle options for Solar Load Controller."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow."""
        self._config_entry = config_entry
        self._options_data: dict[str, Any] = {}

    async def async_step_init(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage load options."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._options_data.update(user_input)
            return await self.async_step_runtime()

        merged = _merged_flow_defaults(
            self._config_entry.data,
            self._config_entry.options,
            self._options_data,
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(_load_schema(merged)),
        )

    async def async_step_runtime(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage runtime options."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._options_data.update(user_input)
            return await self.async_step_energy()

        merged = _merged_flow_defaults(
            self._config_entry.data,
            self._config_entry.options,
            self._options_data,
        )
        return self.async_show_form(
            step_id="runtime",
            data_schema=vol.Schema(_runtime_schema(merged)),
        )

    async def async_step_energy(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage grid, PV, and forecast options."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._options_data.update(user_input)
            return await self.async_step_battery()

        merged = _merged_flow_defaults(
            self._config_entry.data,
            self._config_entry.options,
            self._options_data,
        )
        return self.async_show_form(
            step_id="energy",
            data_schema=vol.Schema(_energy_schema(merged)),
        )

    async def async_step_battery(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage optional battery settings."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._options_data.update(user_input)
            return await self.async_step_advanced()

        merged = _merged_flow_defaults(
            self._config_entry.data,
            self._config_entry.options,
            self._options_data,
        )
        return self.async_show_form(
            step_id="battery",
            data_schema=vol.Schema(_battery_schema(merged)),
        )

    async def async_step_advanced(
        self,
        user_input: dict[str, Any] | None = None,
    ) -> FlowResult:
        """Manage optional battery and diagnostic options."""
        if user_input is not None:
            user_input = _normalize_flow_input(user_input)
            self._options_data.update(user_input)
            return self.async_create_entry(title="", data=self._options_data)

        merged = _merged_flow_defaults(
            self._config_entry.data,
            self._config_entry.options,
            self._options_data,
        )
        return self.async_show_form(
            step_id="advanced",
            data_schema=vol.Schema(_advanced_schema(merged)),
        )


def _load_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return load settings schema."""
    return {
        vol.Required(
            CONF_NAME,
            default=defaults.get(CONF_NAME, "Solar Load"),
        ): selector.TextSelector(),
        _required(CONF_LOAD_SWITCH, defaults): selector.EntitySelector(
            selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
        ),
        vol.Required(
            CONF_LOAD_POWER_W,
            default=defaults.get(CONF_LOAD_POWER_W, DEFAULT_LOAD_POWER_W),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=10000,
                step=1,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }


def _runtime_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return runtime settings schema."""
    return {
        vol.Required(
            CONF_MIN_DAILY_RUNTIME_MINUTES,
            default=defaults.get(
                CONF_MIN_DAILY_RUNTIME_MINUTES,
                DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1440,
                step=5,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_MIN_ON_MINUTES,
            default=defaults.get(CONF_MIN_ON_MINUTES, DEFAULT_MIN_ON_MINUTES),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=240,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_MIN_OFF_MINUTES,
            default=defaults.get(CONF_MIN_OFF_MINUTES, DEFAULT_MIN_OFF_MINUTES),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=240,
                step=1,
                unit_of_measurement="min",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_EARLIEST_START_TIME,
            default=defaults.get(
                CONF_EARLIEST_START_TIME,
                DEFAULT_EARLIEST_START_TIME,
            ),
        ): selector.TimeSelector(),
        vol.Required(
            CONF_LATEST_FINISH_TIME,
            default=defaults.get(
                CONF_LATEST_FINISH_TIME,
                DEFAULT_LATEST_FINISH_TIME,
            ),
        ): selector.TimeSelector(),
    }


def _grid_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return grid settings schema."""
    return {
        _required(CONF_GRID_IMPORT_SENSOR, defaults): _measurement_entity_selector(),
        _required(CONF_GRID_EXPORT_SENSOR, defaults): _measurement_entity_selector(),
        vol.Required(
            CONF_GRID_IMPORT_LIMIT_W,
            default=defaults.get(
                CONF_GRID_IMPORT_LIMIT_W,
                DEFAULT_GRID_IMPORT_LIMIT_W,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=10000,
                step=1,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
    }


def _energy_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return combined grid, PV, and forecast settings schema."""
    return {
        **_grid_schema(defaults),
        **_pv_schema(defaults),
    }


def _pv_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return PV settings schema."""
    return {
        _optional(CONF_PV_CURRENT_POWER_SENSOR, defaults): _measurement_entity_selector(),
        _required(CONF_PV_SIZE_KWP, defaults): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0.1,
                max=1000,
                step=0.1,
                unit_of_measurement="kWp",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        _optional(CONF_INVERTER_LIMIT_W, defaults): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=100000,
                step=1,
                unit_of_measurement="W",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        _required(CONF_FORECAST_TODAY_SENSOR, defaults): _measurement_entity_selector(),
        vol.Required(
            CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
            default=defaults.get(
                CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
                DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
            ),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=20,
                step=0.1,
                unit_of_measurement="kWh/kWp",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        _optional(CONF_FORECAST_NEXT_HOUR_SENSOR, defaults): _measurement_entity_selector(),
        _optional(
            CONF_FORECAST_REMAINING_TODAY_SENSOR,
            defaults,
        ): _measurement_entity_selector(),
    }


def _battery_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return battery settings schema."""
    return {
        _optional(CONF_BATTERY_SOC_SENSOR, defaults): _measurement_entity_selector(),
        _optional(CONF_BATTERY_POWER_SENSOR, defaults): _measurement_entity_selector(),
        vol.Required(
            CONF_BATTERY_POWER_DIRECTION,
            default=defaults.get(
                CONF_BATTERY_POWER_DIRECTION,
                DEFAULT_BATTERY_POWER_DIRECTION,
            ),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    BATTERY_POWER_CHARGING_POSITIVE,
                    BATTERY_POWER_DISCHARGING_POSITIVE,
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_BATTERY_POWER_DIRECTION,
            )
        ),
        _optional(CONF_BATTERY_CAPACITY_KWH, defaults): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=1000,
                step=0.1,
                unit_of_measurement="kWh",
                mode=selector.NumberSelectorMode.BOX,
            )
        ),
        vol.Required(
            CONF_BATTERY_MODE,
            default=defaults.get(CONF_BATTERY_MODE, BATTERY_MODE_PRESERVE),
        ): selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=[
                    BATTERY_MODE_PRESERVE,
                    BATTERY_MODE_USE,
                ],
                mode=selector.SelectSelectorMode.DROPDOWN,
                translation_key=CONF_BATTERY_MODE,
            )
        ),
        vol.Required(
            CONF_MIN_BATTERY_SOC,
            default=defaults.get(CONF_MIN_BATTERY_SOC, DEFAULT_MIN_BATTERY_SOC),
        ): selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=0,
                max=100,
                step=1,
                unit_of_measurement="%",
                mode=selector.NumberSelectorMode.SLIDER,
            )
        ),
    }


def _control_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return controller settings schema."""
    return {
        vol.Required(
            CONF_DEBUG_SENSOR_ENABLED,
            default=defaults.get(CONF_DEBUG_SENSOR_ENABLED, False),
        ): selector.BooleanSelector(),
        vol.Required(
            CONF_MIN_RUNTIME_GRID_OVERRIDE,
            default=defaults.get(CONF_MIN_RUNTIME_GRID_OVERRIDE, True),
        ): selector.BooleanSelector(),
    }

def _advanced_schema(defaults: dict[str, Any]) -> dict[Any, Any]:
    """Return diagnostics and fallback settings schema."""
    return _control_schema(defaults)


def _required(key: str, defaults: dict[str, Any]) -> vol.Required:
    """Return a required schema key with a default only when one exists."""
    if key in defaults and defaults[key] not in (None, ""):
        return vol.Required(key, default=defaults[key])
    return vol.Required(key)


def _optional(key: str, defaults: dict[str, Any]) -> vol.Optional:
    """Return an optional schema key with a default only when one exists."""
    if key in defaults and defaults[key] not in (None, ""):
        return vol.Optional(key, default=defaults[key])
    return vol.Optional(key)


def _measurement_entity_selector() -> selector.EntitySelector:
    """Return a flexible entity selector for numeric measurement entities."""
    return selector.EntitySelector(selector.EntitySelectorConfig())


def _normalize_flow_input(data: dict[str, Any]) -> dict[str, Any]:
    """Normalize config-flow values into JSON-serializable types."""
    normalized: dict[str, Any] = {}
    for key, value in data.items():
        if isinstance(value, time):
            normalized[key] = value.isoformat()
        else:
            normalized[key] = value
    return normalized


def _merged_flow_defaults(*parts: dict[str, Any]) -> dict[str, Any]:
    """Merge flow defaults and normalize them for selector defaults."""
    merged: dict[str, Any] = {}
    for part in parts:
        merged.update(part)
    return _normalize_flow_input(merged)
