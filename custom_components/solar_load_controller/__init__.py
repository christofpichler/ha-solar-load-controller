"""Solar Load Controller integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .const import DATA_AUTOMATION_PAUSED, DATA_CONTROLLER, DOMAIN
from .coordinator import SolarLoadController

SolarLoadControllerConfigEntry = ConfigEntry
PLATFORMS: tuple[Platform, ...] = (
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: SolarLoadControllerConfigEntry,
) -> bool:
    """Set up Solar Load Controller from a config entry."""
    controller = SolarLoadController(hass, entry)
    await controller.async_start()

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        DATA_AUTOMATION_PAUSED: False,
        DATA_CONTROLLER: controller,
        "config": entry.data,
        "options": entry.options,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(
    hass: HomeAssistant,
    entry: SolarLoadControllerConfigEntry,
) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if not unload_ok:
        return False

    entry_data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if entry_data is not None:
        entry_data[DATA_CONTROLLER].async_stop()
    return True


async def _async_update_listener(
    hass: HomeAssistant,
    entry: SolarLoadControllerConfigEntry,
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
