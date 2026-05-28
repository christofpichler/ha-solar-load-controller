"""Switch entities for the Solar Load Controller integration."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_ON
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DATA_AUTOMATION_PAUSED, DATA_CONTROLLER, DOMAIN
from .coordinator import SolarLoadController


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up switch entities from a config entry."""
    async_add_entities([SolarLoadAutomationEnabledSwitch(hass, entry)])


class SolarLoadAutomationEnabledSwitch(SwitchEntity, RestoreEntity):
    """Switch that enables automatic control for the load."""

    _attr_has_entity_name = True
    _attr_icon = "mdi:robot"
    _attr_translation_key = "automation_enabled"

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        """Initialize the automation-enabled switch."""
        self._hass = hass
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_automation_enabled_switch"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Solar Load Controller",
        )
        self._is_on = True

    @property
    def is_on(self) -> bool:
        """Return true if automatic control is enabled."""
        return self._is_on

    async def async_added_to_hass(self) -> None:
        """Restore the automation-enabled state after Home Assistant restarts."""
        if (last_state := await self.async_get_last_state()) is not None:
            self._is_on = last_state.state == STATE_ON
            self._set_shared_pause_state(not self._is_on)
        else:
            self._set_shared_pause_state(False)

    async def async_turn_on(self, **kwargs: object) -> None:
        """Enable automatic control."""
        self._is_on = True
        self._set_shared_pause_state(False)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: object) -> None:
        """Disable automatic control."""
        self._is_on = False
        self._set_shared_pause_state(True)
        self.async_write_ha_state()

    def _set_shared_pause_state(self, paused: bool) -> None:
        """Store the pause flag for the controller logic."""
        domain_data = self._hass.data.get(DOMAIN, {})
        entry_data = domain_data.get(self._entry.entry_id)
        if entry_data is not None:
            entry_data[DATA_AUTOMATION_PAUSED] = paused
            controller: SolarLoadController = entry_data[DATA_CONTROLLER]
            controller.async_set_automation_paused(paused)
