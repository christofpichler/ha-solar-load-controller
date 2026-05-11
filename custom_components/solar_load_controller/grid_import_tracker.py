"""Grid-import tracking state for Solar Load Controller."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util

from .const import (
    CONF_GRID_IMPORT_LIMIT_W,
    DEFAULT_GRID_IMPORT_LIMIT_W,
    FORECAST_DAY_MODE_HIGH,
)
from .high_mode import HIGH_FORECAST_NO_GRID_TOLERANCE_W
from .sensor_reader import as_float


class GridImportTracker:
    """Track sustained import excess and restart cooldown state."""

    def __init__(self) -> None:
        self.over_limit_since: datetime | None = None
        self.high_forecast_over_tolerance_since: datetime | None = None
        self.last_shutdown_at: datetime | None = None

    def over_limit_duration_seconds(self, now: datetime | None = None) -> float:
        """Return how long running import has exceeded the configured limit."""
        if self.over_limit_since is None:
            return 0.0
        now = now or dt_util.utcnow()
        return round(max(0.0, (now - self.over_limit_since).total_seconds()), 1)

    def high_forecast_duration_seconds(self, now: datetime | None = None) -> float:
        """Return how long high mode has seen grid import above tolerance."""
        if self.high_forecast_over_tolerance_since is None:
            return 0.0
        now = now or dt_util.utcnow()
        return round(
            max(0.0, (now - self.high_forecast_over_tolerance_since).total_seconds()),
            1,
        )

    def cooldown_remaining_seconds(
        self,
        cooldown: timedelta,
        now: datetime | None = None,
    ) -> float:
        """Return remaining grid-import cooldown in seconds."""
        if self.last_shutdown_at is None:
            return 0.0
        now = now or dt_util.utcnow()
        elapsed = now - self.last_shutdown_at
        return round(
            max(0.0, cooldown.total_seconds() - elapsed.total_seconds()),
            1,
        )

    def cooldown_active(
        self,
        *,
        is_load_on: bool,
        cooldown: timedelta,
        now: datetime | None = None,
    ) -> bool:
        """Return whether a grid-import restart cooldown is active."""
        if is_load_on or self.last_shutdown_at is None:
            return False
        return self.cooldown_remaining_seconds(cooldown, now) > 0

    def record_shutdown(self, now: datetime | None = None) -> None:
        """Record a grid-import shutdown timestamp."""
        self.last_shutdown_at = now or dt_util.utcnow()

    def clear_shutdown(self) -> None:
        """Clear the last grid-import shutdown timestamp."""
        self.last_shutdown_at = None

    def reset_running_timers(self) -> None:
        """Clear timers that only apply while the load is running."""
        self.over_limit_since = None
        self.high_forecast_over_tolerance_since = None

    def reset_all(self) -> None:
        """Clear all grid-import tracking state."""
        self.reset_running_timers()
        self.last_shutdown_at = None

    def update(
        self,
        *,
        now: datetime | None,
        is_load_on: bool,
        grid_import_w: float | None,
        grid_import_limit_w: float,
        forecast_day_class: str,
        high_forecast_day_class: str,
        high_grid_import_tolerance_w: float,
    ) -> None:
        """Track sustained grid import excess while the load is running."""
        now = now or dt_util.utcnow()
        over_limit = (
            is_load_on
            and grid_import_w is not None
            and grid_import_w > grid_import_limit_w
        )
        if over_limit:
            if self.over_limit_since is None:
                self.over_limit_since = now
        else:
            self.over_limit_since = None

        high_over_tolerance = (
            is_load_on
            and forecast_day_class == high_forecast_day_class
            and grid_import_w is not None
            and grid_import_w > high_grid_import_tolerance_w
        )
        if high_over_tolerance:
            if self.high_forecast_over_tolerance_since is None:
                self.high_forecast_over_tolerance_since = now
            return
        self.high_forecast_over_tolerance_since = None


class GridImportMixin:
    """Controller grid-import properties backed by GridImportTracker."""

    @property
    def grid_import_limit_w(self) -> float:
        """Return configured allowed grid import in watts."""
        return as_float(
            self.config.get(CONF_GRID_IMPORT_LIMIT_W),
            DEFAULT_GRID_IMPORT_LIMIT_W,
        )

    @property
    def grid_import_start_limit_w(self) -> float:
        """Return import limit used before starting the load."""
        return max(0.0, self.grid_import_limit_w - self.grid_import_start_margin_w)

    @property
    def grid_import_over_limit_duration_seconds(self) -> float:
        """Return how long running import has exceeded the limit."""
        return self._grid_import.over_limit_duration_seconds()

    @property
    def grid_import_shutdown_allowed(self) -> bool:
        """Return whether sustained import excess may shut the load down."""
        return (
            self.grid_import_over_limit_duration_seconds
            >= self.grid_import_shutdown_delay_seconds
        )

    @property
    def high_forecast_grid_import_duration_seconds(self) -> float:
        """Return how long high mode has seen grid import above tolerance."""
        return self._grid_import.high_forecast_duration_seconds()

    @property
    def grid_import_cooldown_active(self) -> bool:
        """Return whether a grid-import restart cooldown is active."""
        return self._grid_import.cooldown_active(
            is_load_on=self.is_load_on,
            cooldown=self.grid_import_restart_cooldown,
        )

    @property
    def grid_import_cooldown_remaining_seconds(self) -> float:
        """Return remaining grid-import cooldown in seconds."""
        return self._grid_import.cooldown_remaining_seconds(
            self.grid_import_restart_cooldown,
        )

    @property
    def _high_forecast_grid_import_active(self) -> bool:
        """Return whether high mode import has exceeded the shutdown delay."""
        return (
            self.high_forecast_grid_import_duration_seconds
            >= self.grid_import_shutdown_delay_seconds
        )

    def _async_update_grid_import_tracking(
        self,
        now: datetime | None = None,
    ) -> None:
        """Track sustained grid import excess while the load is running."""
        self._grid_import.update(
            now=now,
            is_load_on=self.is_load_on,
            grid_import_w=self.grid_import_w,
            grid_import_limit_w=self.grid_import_limit_w,
            forecast_day_class=self.forecast_day_class,
            high_forecast_day_class=FORECAST_DAY_MODE_HIGH,
            high_grid_import_tolerance_w=HIGH_FORECAST_NO_GRID_TOLERANCE_W,
        )
