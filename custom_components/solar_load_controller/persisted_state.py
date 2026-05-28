"""Persistent controller state helpers for Solar Load Controller."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime

from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger("custom_components.solar_load_controller.coordinator")


@dataclass(slots=True)
class PersistedRuntimeState:
    """Runtime state restored from Home Assistant storage."""

    runtime_force_latched: bool
    last_turned_off_at: datetime | None


class PersistedControllerState:
    """Load and save state that must survive Home Assistant restarts."""

    def __init__(self, hass, version: int, entry_id: str) -> None:
        self.store = Store(
            hass,
            version,
            f"solar_load_controller_{entry_id}_state",
        )

    async def async_load(self, *, today_iso: str) -> PersistedRuntimeState | None:
        """Restore persisted runtime-latch state for the current day."""
        return await async_load_runtime_state(self.store, today_iso=today_iso)

    async def async_save(
        self,
        *,
        today_iso: str,
        runtime_force_latched: bool,
        last_turned_off_at: datetime | None,
    ) -> None:
        """Save runtime-latch state to persistent storage."""
        await async_save_runtime_state(
            self.store,
            today_iso=today_iso,
            runtime_force_latched=runtime_force_latched,
            last_turned_off_at=last_turned_off_at,
        )


async def async_load_runtime_state(
    store,
    *,
    today_iso: str,
) -> PersistedRuntimeState | None:
    """Restore persisted runtime-latch state for the current day."""
    data = await store.async_load()
    if not isinstance(data, dict):
        return None
    if data.get("date") != today_iso:
        await store.async_remove()
        return None

    last_turned_off_at = None
    if (raw := data.get("last_turned_off_at")) is not None:
        try:
            parsed = dt_util.parse_datetime(raw)
            if parsed is not None:
                last_turned_off_at = parsed
        except (TypeError, ValueError):
            pass

    state = PersistedRuntimeState(
        runtime_force_latched=bool(data.get("runtime_force_latched", False)),
        last_turned_off_at=last_turned_off_at,
    )
    if state.runtime_force_latched:
        _LOGGER.debug(
            "Restored runtime_force_latched=True from persistent storage "
            "(last_turned_off_at=%s)",
            state.last_turned_off_at,
        )
    return state


async def async_save_runtime_state(
    store,
    *,
    today_iso: str,
    runtime_force_latched: bool,
    last_turned_off_at: datetime | None,
) -> None:
    """Save runtime-latch state to persistent storage."""
    await store.async_save(
        {
            "date": today_iso,
            "runtime_force_latched": runtime_force_latched,
            "last_turned_off_at": (
                last_turned_off_at.isoformat()
                if last_turned_off_at is not None
                else None
            ),
        }
    )
