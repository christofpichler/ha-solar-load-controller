"""Solar Load Controller integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback

from .const import (
    CONF_TELEMETRY_ENABLED,
    DATA_AUTOMATION_PAUSED,
    DATA_CONTROLLER,
    DEFAULT_TELEMETRY_ENABLED,
    DOMAIN,
)
from .coordinator import SolarLoadController
from .telemetry import TelemetryHeartbeat

SolarLoadControllerConfigEntry = ConfigEntry
PLATFORMS: tuple[Platform, ...] = (
    Platform.SELECT,
    Platform.SENSOR,
    Platform.SWITCH,
)

# The heartbeat identifies the installation, so it is shared by all config
# entries rather than started once per entry.
DATA_TELEMETRY = "telemetry"


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
    _async_setup_telemetry(hass, entry)
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

    _async_stop_telemetry_if_last_entry(hass)
    return True


@callback
def _telemetry_enabled(entry: SolarLoadControllerConfigEntry) -> bool:
    """Return whether this entry allows the anonymous heartbeat."""
    merged = {**entry.data, **entry.options}
    return bool(merged.get(CONF_TELEMETRY_ENABLED, DEFAULT_TELEMETRY_ENABLED))


@callback
def _async_setup_telemetry(
    hass: HomeAssistant,
    entry: SolarLoadControllerConfigEntry,
) -> None:
    """Start the shared heartbeat unless every entry has it switched off."""
    if not _telemetry_enabled(entry):
        return
    if hass.data[DOMAIN].get(DATA_TELEMETRY) is not None:
        return

    heartbeat = TelemetryHeartbeat(hass)
    hass.data[DOMAIN][DATA_TELEMETRY] = heartbeat
    heartbeat.async_start()


@callback
def _async_stop_telemetry_if_last_entry(hass: HomeAssistant) -> None:
    """Stop the heartbeat once no config entry is left to justify it."""
    domain_data = hass.data.get(DOMAIN, {})
    if any(key != DATA_TELEMETRY for key in domain_data):
        return

    heartbeat = domain_data.pop(DATA_TELEMETRY, None)
    if heartbeat is not None:
        heartbeat.async_stop()


async def _async_update_listener(
    hass: HomeAssistant,
    entry: SolarLoadControllerConfigEntry,
) -> None:
    """Reload the integration when options change."""
    await hass.config_entries.async_reload(entry.entry_id)
