"""Anonymous installation heartbeat.

Posts ``{"installation_id": "<uuid4>", "version": "..."}`` once a day. The id is
generated on first run and stored in ``.storage``. Runs as a background task and
swallows every failure at debug level. Can be switched off in the options.
"""

from __future__ import annotations

import asyncio
import logging
import random
import uuid
from datetime import timedelta
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.storage import Store
from homeassistant.loader import async_get_integration

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

TELEMETRY_ENDPOINT = "https://telemetry.cloudpichler.net/heartbeat"

TELEMETRY_INTERVAL = timedelta(days=1)
TELEMETRY_TIMEOUT_SECONDS = 10
# Spreads a restart wave over an hour.
TELEMETRY_STARTUP_JITTER_SECONDS = 3600

_STORE_VERSION = 1
# Not keyed by entry_id: one id per installation, not per config entry.
_STORE_KEY = f"{DOMAIN}_installation_id"


async def async_get_installation_id(hass: HomeAssistant) -> str:
    """Return the persistent installation id, creating it on first run."""
    store: Store = Store(hass, _STORE_VERSION, _STORE_KEY)
    data: Any = await store.async_load()
    if isinstance(data, dict):
        stored = data.get("installation_id")
        if isinstance(stored, str) and stored:
            return stored

    installation_id = str(uuid.uuid4())
    await store.async_save({"installation_id": installation_id})
    _LOGGER.debug("Generated a new installation id for anonymous telemetry")
    return installation_id


async def async_current_version(hass: HomeAssistant) -> str:
    """Return the integration version from the manifest."""
    integration = await async_get_integration(hass, DOMAIN)
    return str(integration.version)


async def async_send_heartbeat(
    hass: HomeAssistant,
    *,
    installation_id: str,
    version: str,
    endpoint: str = TELEMETRY_ENDPOINT,
) -> bool:
    """Send one heartbeat and return whether it was accepted. Never raises."""
    session = async_get_clientsession(hass)
    payload = {"installation_id": installation_id, "version": version}
    try:
        async with asyncio.timeout(TELEMETRY_TIMEOUT_SECONDS):
            response = await session.post(endpoint, json=payload)
        if response.status >= 400:
            _LOGGER.debug(
                "Telemetry heartbeat rejected with status %s", response.status
            )
            return False
    except asyncio.CancelledError:
        raise
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Telemetry heartbeat failed: %s", err)
        return False

    _LOGGER.debug("Telemetry heartbeat sent")
    return True


class TelemetryHeartbeat:
    """Schedule the daily heartbeat for one Home Assistant instance."""

    def __init__(self, hass: HomeAssistant) -> None:
        """Initialize the heartbeat scheduler."""
        self.hass = hass
        self._unsubscribe: Any = None
        self._start_handle: asyncio.TimerHandle | None = None

    @callback
    def async_start(self, *, jitter_seconds: int | None = None) -> None:
        """Begin sending heartbeats after a random startup delay."""
        if self._unsubscribe is not None or self._start_handle is not None:
            return

        if jitter_seconds is None:
            jitter_seconds = random.randint(0, TELEMETRY_STARTUP_JITTER_SECONDS)

        self._start_handle = self.hass.loop.call_later(
            jitter_seconds, self._async_begin
        )

    @callback
    def _async_begin(self) -> None:
        """Send the first heartbeat and schedule the recurring one."""
        self._start_handle = None
        self._async_fire()
        self._unsubscribe = async_track_time_interval(
            self.hass,
            self._async_interval_fire,
            TELEMETRY_INTERVAL,
        )

    @callback
    def _async_interval_fire(self, _now: Any) -> None:
        """Handle the recurring timer."""
        self._async_fire()

    @callback
    def _async_fire(self) -> None:
        """Dispatch one heartbeat as a background task."""
        self.hass.async_create_background_task(
            self._async_heartbeat(),
            name=f"{DOMAIN}_telemetry_heartbeat",
        )

    async def _async_heartbeat(self) -> None:
        """Collect the two fields and send them."""
        try:
            installation_id = await async_get_installation_id(self.hass)
            version = await async_current_version(self.hass)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Could not prepare telemetry heartbeat: %s", err)
            return

        await async_send_heartbeat(
            self.hass,
            installation_id=installation_id,
            version=version,
        )

    @callback
    def async_stop(self) -> None:
        """Stop sending heartbeats."""
        if self._start_handle is not None:
            self._start_handle.cancel()
            self._start_handle = None
        if self._unsubscribe is not None:
            self._unsubscribe()
            self._unsubscribe = None
