"""Select entities for the Solar Load Controller integration."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import (
    DATA_CONTROLLER,
    DOMAIN,
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
)
from .coordinator import SolarLoadController

FORECAST_DAY_MODE_OPTIONS = [
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
    FORECAST_DAY_MODE_HIGH,
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up select entities from a config entry."""
    controller: SolarLoadController = hass.data[DOMAIN][entry.entry_id][
        DATA_CONTROLLER
    ]
    async_add_entities([SolarLoadForecastDayModeSelect(controller)])


class SolarLoadForecastDayModeSelect(SelectEntity, RestoreEntity):
    """Select entity that overrides the forecast day mode for diagnostics."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:weather-sunny-alert"
    _attr_options = FORECAST_DAY_MODE_OPTIONS
    _attr_translation_key = "forecast_day_mode_override"

    def __init__(self, controller: SolarLoadController) -> None:
        """Initialize the select entity."""
        self.controller = controller
        self._attr_unique_id = (
            f"{controller.entry.entry_id}_forecast_day_mode_override"
        )
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, controller.entry.entry_id)},
            name=controller.entry.title,
            manufacturer="Solar Load Controller",
        )

    @property
    def current_option(self) -> str:
        """Return selected forecast day mode override."""
        return self.controller.forecast_day_mode_override

    async def async_added_to_hass(self) -> None:
        """Restore the selected override after Home Assistant restarts."""
        if (last_state := await self.async_get_last_state()) is None:
            return
        if last_state.state in FORECAST_DAY_MODE_OPTIONS:
            self.controller.async_set_forecast_day_mode_override(last_state.state)

    async def async_select_option(self, option: str) -> None:
        """Select a forecast day mode override."""
        if option not in FORECAST_DAY_MODE_OPTIONS:
            return
        self.controller.async_set_forecast_day_mode_override(option)
        self.async_write_ha_state()
