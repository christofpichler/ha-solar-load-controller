"""Time-window helpers for Solar Load Controller."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from homeassistant.util import dt as dt_util

from .const import (
    CONF_EARLIEST_START_TIME,
    CONF_LATEST_FINISH_TIME,
    CONF_MIN_OFF_MINUTES,
    CONF_MIN_ON_MINUTES,
    DEFAULT_EARLIEST_START_TIME,
    DEFAULT_LATEST_FINISH_TIME,
    DEFAULT_MIN_OFF_MINUTES,
    DEFAULT_MIN_ON_MINUTES,
)
from .sensor_reader import as_float

_FALLBACK_TIME = time(21, 0)


def today() -> date:
    """Return today's date in the Home Assistant timezone."""
    return dt_util.now().date()


def parse_time(value: Any, default: str) -> time:
    """Parse a Home Assistant time selector value.

    Tries value first, then default, then falls back to 21:00 as an absolute
    last resort so the function can never recurse infinitely.
    """
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            parts = [int(part) for part in value.split(":")]
            return time(parts[0], parts[1], parts[2] if len(parts) > 2 else 0)
        except (TypeError, ValueError, IndexError):
            pass
    if value != default:
        return parse_time(default, default)
    return _FALLBACK_TIME


def window_crosses_midnight(start_time: time, finish_time: time) -> bool:
    """Return whether the configured time window crosses midnight."""
    return start_time > finish_time


def total_window_minutes(start_time: time, finish_time: time) -> float:
    """Return total minutes in the configured active window."""
    start_dt = datetime.combine(today(), start_time)
    finish_dt = datetime.combine(today(), finish_time)
    if finish_dt <= start_dt:
        finish_dt += timedelta(days=1)
    return max(0.0, (finish_dt - start_dt).total_seconds() / 60)


def minutes_until_finish(finish_time: time, crosses_midnight: bool) -> float:
    """Return minutes until the configured finish time."""
    now = dt_util.now()
    finish_at = datetime.combine(now.date(), finish_time, tzinfo=now.tzinfo)
    if finish_at < now and crosses_midnight:
        finish_at += timedelta(days=1)
    return max(0.0, (finish_at - now).total_seconds() / 60)


def is_inside_time_window(start_time: time, finish_time: time) -> bool:
    """Return whether automatic control is allowed by the daily time window."""
    now_time = dt_util.now().time()
    if not window_crosses_midnight(start_time, finish_time):
        return start_time <= now_time <= finish_time
    return now_time >= start_time or now_time <= finish_time


def minutes_since(started_at: datetime) -> float:
    """Return minutes since a UTC timestamp."""
    return max(0.0, (dt_util.utcnow() - started_at).total_seconds() / 60)


class TimeWindowMixin:
    """Controller time-window and minimum on/off helpers."""

    @property
    def inside_time_window(self) -> bool:
        """Return whether automatic control is inside the allowed time window."""
        return self._is_inside_time_window

    @property
    def min_on_active(self) -> bool:
        """Return whether the minimum on timer is active."""
        return self._minimum_on_time_active

    @property
    def min_on_remaining_minutes(self) -> float:
        """Return remaining minimum on time in minutes."""
        if self._last_turned_on_at is None:
            return 0.0
        min_on_minutes = as_float(
            self.config.get(CONF_MIN_ON_MINUTES),
            DEFAULT_MIN_ON_MINUTES,
        )
        return round(
            max(0.0, min_on_minutes - self._minutes_since(self._last_turned_on_at)),
            1,
        )

    @property
    def min_off_active(self) -> bool:
        """Return whether the minimum off timer is active."""
        return self._minimum_off_time_active

    @property
    def min_off_remaining_minutes(self) -> float:
        """Return remaining minimum off time in minutes."""
        if self._last_turned_off_at is None:
            return 0.0
        min_off_minutes = as_float(
            self.config.get(CONF_MIN_OFF_MINUTES),
            DEFAULT_MIN_OFF_MINUTES,
        )
        return round(
            max(0.0, min_off_minutes - self._minutes_since(self._last_turned_off_at)),
            1,
        )

    @property
    def minutes_until_finish(self) -> float:
        """Return minutes until the configured finish time."""
        return round(self._minutes_until_finish, 1)

    @property
    def _minutes_until_finish(self) -> float:
        """Return minutes until the configured finish time."""
        finish = parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        return minutes_until_finish(finish, self._window_crosses_midnight)

    @property
    def _total_window_minutes(self) -> float:
        """Return total minutes in the configured active window."""
        start_time = parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        return total_window_minutes(start_time, finish_time)

    def _runtime_deadline_reached(self, runtime_remaining_minutes: float) -> bool:
        """Return whether runtime has to start now to finish in time."""
        minutes_until_finish_value = self._minutes_until_finish
        return runtime_remaining_minutes >= minutes_until_finish_value

    @property
    def _window_crosses_midnight(self) -> bool:
        """Return whether the configured time window crosses midnight."""
        start_time = parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        return window_crosses_midnight(start_time, finish_time)

    @property
    def _is_inside_time_window(self) -> bool:
        """Return whether automatic control is allowed by the daily time window."""
        start_time = parse_time(
            self.config.get(CONF_EARLIEST_START_TIME),
            DEFAULT_EARLIEST_START_TIME,
        )
        finish_time = parse_time(
            self.config.get(CONF_LATEST_FINISH_TIME),
            DEFAULT_LATEST_FINISH_TIME,
        )
        return is_inside_time_window(start_time, finish_time)

    @property
    def _minimum_on_time_active(self) -> bool:
        """Return whether the configured minimum on time is active."""
        if self._last_turned_on_at is None:
            return False
        min_on_minutes = as_float(
            self.config.get(CONF_MIN_ON_MINUTES),
            DEFAULT_MIN_ON_MINUTES,
        )
        return self._minutes_since(self._last_turned_on_at) < min_on_minutes

    @property
    def _minimum_off_time_active(self) -> bool:
        """Return whether the configured minimum off time is active."""
        if self.is_load_on or self._last_turned_off_at is None:
            return False
        min_off_minutes = as_float(
            self.config.get(CONF_MIN_OFF_MINUTES),
            DEFAULT_MIN_OFF_MINUTES,
        )
        return self._minutes_since(self._last_turned_off_at) < min_off_minutes

    def _minutes_since(self, started_at: datetime) -> float:
        """Return minutes since a UTC timestamp."""
        return minutes_since(started_at)
