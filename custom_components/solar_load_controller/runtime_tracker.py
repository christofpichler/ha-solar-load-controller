"""Runtime accounting for Solar Load Controller.

RuntimeTracker owns the per-day counters (total, solar, forced, switch
cycles), the active-runtime reference timestamp, and the active-reason
label.  The coordinator holds the tracker and delegates all runtime
arithmetic to it so coordinator.py stays focused on orchestration.

The coordinator keeps _last_turned_on_at and _last_turned_off_at as its
own fields because they serve min-on/min-off logic and persist state -
not runtime accounting.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    DECISION_EXPORT_GUARD,
    DECISION_FORECAST_ASSISTED_RUN,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DECISION_MINIMUM_RUNTIME_REQUIRED,
    DECISION_SOLAR_SURPLUS_AVAILABLE,
)

# Reasons whose elapsed time counts as solar runtime.
_SOLAR_RUNTIME_REASONS: frozenset[str] = frozenset(
    {
        DECISION_SOLAR_SURPLUS_AVAILABLE,
        DECISION_FORECAST_ASSISTED_RUN,
        DECISION_LOW_FORECAST_ASSISTED_RUN,
        DECISION_EXPORT_GUARD,
    }
)


class RuntimeTracker:
    """Accumulates daily runtime statistics for the configured load.

    All time values are in seconds internally; callers convert to minutes
    or kWh as needed.
    """

    def __init__(self) -> None:
        self._runtime_seconds: float = 0.0
        self._solar_runtime_seconds: float = 0.0
        self._forced_runtime_seconds: float = 0.0
        self._switch_cycles: int = 0
        self._last_runtime_update: datetime | None = None
        self._active_runtime_reason: str | None = None

    # ------------------------------------------------------------------
    # State queries
    # ------------------------------------------------------------------

    @property
    def is_tracking(self) -> bool:
        """Return True while the load is on and tracking is active."""
        return self._last_runtime_update is not None

    @property
    def switch_cycles(self) -> int:
        """Return the number of automatic switch-on cycles today."""
        return self._switch_cycles

    @property
    def active_runtime_reason(self) -> str | None:
        """Return the decision reason for the current active interval."""
        return self._active_runtime_reason

    # ------------------------------------------------------------------
    # Live second counters (include the running interval)
    # ------------------------------------------------------------------

    def active_delta_seconds(self, now: datetime | None = None) -> float:
        """Return seconds elapsed since the last committed update."""
        if self._last_runtime_update is None:
            return 0.0
        now = now or dt_util.utcnow()
        return max(0.0, (now - self._last_runtime_update).total_seconds())

    @property
    def runtime_today_seconds(self) -> float:
        """Return total runtime today including the running interval."""
        return self._runtime_seconds + self.active_delta_seconds()

    @property
    def solar_runtime_today_seconds(self) -> float:
        """Return solar-attributed runtime today including the running interval."""
        if self._active_runtime_reason not in _SOLAR_RUNTIME_REASONS:
            return self._solar_runtime_seconds
        return self._solar_runtime_seconds + self.active_delta_seconds()

    @property
    def forced_runtime_today_seconds(self) -> float:
        """Return forced-runtime seconds today including the running interval."""
        if self._active_runtime_reason != DECISION_MINIMUM_RUNTIME_REQUIRED:
            return self._forced_runtime_seconds
        return self._forced_runtime_seconds + self.active_delta_seconds()

    # ------------------------------------------------------------------
    # Mutations
    # ------------------------------------------------------------------

    def commit(self, now: datetime) -> None:
        """Commit the running interval into the daily counters."""
        delta = self.active_delta_seconds(now)
        if delta <= 0:
            return
        self._runtime_seconds += delta
        if self._active_runtime_reason in _SOLAR_RUNTIME_REASONS:
            self._solar_runtime_seconds += delta
        elif self._active_runtime_reason == DECISION_MINIMUM_RUNTIME_REQUIRED:
            self._forced_runtime_seconds += delta
        self._last_runtime_update = now

    def start_tracking(self, now: datetime, *, automatic: bool = False) -> None:
        """Mark the load as on and start accumulating runtime.

        Pass ``automatic=True`` when the turn-on was triggered by the
        controller so the switch-cycle counter is incremented.
        """
        self._last_runtime_update = now
        if automatic:
            self._switch_cycles += 1

    def stop_tracking(self) -> None:
        """Mark the load as off; the next commit will be a no-op."""
        self._last_runtime_update = None

    def set_reason(self, reason: str | None) -> None:
        """Set the decision reason for the current active interval."""
        self._active_runtime_reason = reason

    def midnight_reset(self, *, is_on: bool, now: datetime) -> None:
        """Reset all daily counters at midnight.

        If the load is currently on, tracking resumes immediately from
        *now* so no runtime is lost across the day boundary.
        """
        self._runtime_seconds = 0.0
        self._solar_runtime_seconds = 0.0
        self._forced_runtime_seconds = 0.0
        self._switch_cycles = 0
        if is_on:
            self._last_runtime_update = now
        else:
            self._last_runtime_update = None
            self._active_runtime_reason = None

    def restore(self, key: str, value: float) -> None:
        """Restore one daily statistic from a persisted sensor state.

        *value* is in minutes for duration keys, raw count for cycles.
        """
        if key == "runtime_today":
            self._runtime_seconds = max(0.0, value * 60)
        elif key == "solar_runtime_today":
            self._solar_runtime_seconds = max(0.0, value * 60)
        elif key == "forced_runtime_today":
            self._forced_runtime_seconds = max(0.0, value * 60)
        elif key == "switch_cycles_today":
            self._switch_cycles = max(0, int(value))

    def as_debug_dict(self) -> dict[str, Any]:
        """Return a snapshot suitable for the debug sensor."""
        return {
            "runtime_today_seconds": self._runtime_seconds,
            "solar_runtime_today_seconds": self._solar_runtime_seconds,
            "forced_runtime_today_seconds": self._forced_runtime_seconds,
            "switch_cycles": self._switch_cycles,
            "is_tracking": self.is_tracking,
            "active_runtime_reason": self._active_runtime_reason,
        }
