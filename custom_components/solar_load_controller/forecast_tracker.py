"""Daily forecast classification state for Solar Load Controller."""

from __future__ import annotations

from datetime import date, datetime, time

from homeassistant.util import dt as dt_util

from .const import (
    CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    CONF_FORECAST_LOW_THRESHOLD_KWH_PER_KWP,
    CONF_PV_SIZE_KWP,
    DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
    DEFAULT_FORECAST_LOW_THRESHOLD_KWH_PER_KWP,
    FORECAST_DAY_MODE_AUTO,
    FORECAST_DAY_MODE_HIGH,
    FORECAST_DAY_MODE_LOW,
    FORECAST_DAY_MODE_MID,
)
from .sensor_reader import as_float
from .time_window import today


class ForecastTracker:
    """Keep today's captured forecast mode stable after the morning cutoff."""

    def __init__(self) -> None:
        self.date: date | None = None
        self.captured_at: datetime | None = None
        self.today_kwh: float | None = None
        self.kwh_per_kwp: float | None = None
        self.day_class: str = "unknown"
        self.mode_override = FORECAST_DAY_MODE_AUTO

    def set_mode_override(self, mode: str) -> bool:
        """Set a manual day-mode override. Return False for invalid values."""
        if mode not in {
            FORECAST_DAY_MODE_AUTO,
            FORECAST_DAY_MODE_LOW,
            FORECAST_DAY_MODE_MID,
            FORECAST_DAY_MODE_HIGH,
        }:
            return False
        self.mode_override = mode
        return True

    def captured_at_iso(self) -> str | None:
        """Return the capture timestamp as ISO string."""
        if self.captured_at is None:
            return None
        return self.captured_at.isoformat()

    def forecast_today_kwh(self, live_forecast_today_kwh: float | None) -> float | None:
        """Return captured forecast for today or the live sensor fallback."""
        if self.date == today():
            return self.today_kwh
        return live_forecast_today_kwh

    def forecast_kwh_per_kwp(
        self,
        live_forecast_today_kwh: float | None,
        pv_size_kwp: float | None,
    ) -> float | None:
        """Return captured or live forecast normalized by PV size."""
        if self.date == today():
            return self.kwh_per_kwp
        return live_forecast_kwh_per_kwp(live_forecast_today_kwh, pv_size_kwp)

    def forecast_day_class(
        self,
        live_forecast_today_kwh: float | None,
        pv_size_kwp: float | None,
        *,
        high_threshold: float | None,
        low_threshold: float | None,
    ) -> str:
        """Return the effective low/mid/high forecast class."""
        if self.mode_override != FORECAST_DAY_MODE_AUTO:
            return self.mode_override
        if self.date == today():
            return self.day_class
        return classify_forecast_kwh_per_kwp(
            live_forecast_kwh_per_kwp(live_forecast_today_kwh, pv_size_kwp),
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )

    def capture_if_needed(
        self,
        now: datetime,
        live_forecast_today_kwh: float | None,
        pv_size_kwp: float | None,
        *,
        high_threshold: float | None,
        low_threshold: float | None,
    ) -> None:
        """Capture today's forecast once after the morning cutoff."""
        if self.date == now.date() and self.day_class != "unknown":
            return
        if now.time() < time(6, 0):
            return
        self.capture(
            now,
            live_forecast_today_kwh,
            pv_size_kwp,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )

    def capture(
        self,
        now: datetime,
        live_forecast_today_kwh: float | None,
        pv_size_kwp: float | None,
        *,
        high_threshold: float | None,
        low_threshold: float | None,
        kwh_per_kwp: float | None = None,
    ) -> None:
        """Store today's forecast class so the day mode stays stable."""
        if kwh_per_kwp is None:
            kwh_per_kwp = live_forecast_kwh_per_kwp(
                live_forecast_today_kwh,
                pv_size_kwp,
            )
        if kwh_per_kwp is None:
            return
        self.date = now.date()
        self.captured_at = now
        self.today_kwh = live_forecast_today_kwh
        self.kwh_per_kwp = kwh_per_kwp
        self.day_class = classify_forecast_kwh_per_kwp(
            kwh_per_kwp,
            high_threshold=high_threshold,
            low_threshold=low_threshold,
        )

    def reset(self) -> None:
        """Clear captured forecast state."""
        self.date = None
        self.captured_at = None
        self.today_kwh = None
        self.kwh_per_kwp = None
        self.day_class = "unknown"


class ForecastTrackerMixin:
    """Controller forecast properties backed by ForecastTracker."""

    @property
    def forecast_day_mode_override(self) -> str:
        """Return the selected forecast day mode override."""
        return self._forecast.mode_override

    @property
    def _daily_forecast_date(self) -> date | None:
        """Compatibility access to the captured forecast date."""
        return self._forecast.date

    @_daily_forecast_date.setter
    def _daily_forecast_date(self, value: date | None) -> None:
        self._forecast.date = value

    @property
    def _daily_forecast_captured_at(self) -> datetime | None:
        """Compatibility access to the captured forecast timestamp."""
        return self._forecast.captured_at

    @_daily_forecast_captured_at.setter
    def _daily_forecast_captured_at(self, value: datetime | None) -> None:
        self._forecast.captured_at = value

    @property
    def _daily_forecast_today_kwh(self) -> float | None:
        """Compatibility access to the captured forecast energy."""
        return self._forecast.today_kwh

    @_daily_forecast_today_kwh.setter
    def _daily_forecast_today_kwh(self, value: float | None) -> None:
        self._forecast.today_kwh = value

    @property
    def _daily_forecast_kwh_per_kwp(self) -> float | None:
        """Compatibility access to the captured normalized forecast."""
        return self._forecast.kwh_per_kwp

    @_daily_forecast_kwh_per_kwp.setter
    def _daily_forecast_kwh_per_kwp(self, value: float | None) -> None:
        self._forecast.kwh_per_kwp = value

    @property
    def _daily_forecast_day_class(self) -> str:
        """Compatibility access to the captured forecast class."""
        return self._forecast.day_class

    @_daily_forecast_day_class.setter
    def _daily_forecast_day_class(self, value: str) -> None:
        self._forecast.day_class = value

    @property
    def forecast_today_kwh(self) -> float | None:
        """Return forecast energy for the whole day in kWh."""
        return self._forecast.forecast_today_kwh(self._forecast_today_kwh)

    @property
    def forecast_remaining_today_kwh(self) -> float | None:
        """Return forecast energy remaining today in kWh."""
        return self._forecast_remaining_kwh

    @property
    def forecast_next_hour_kwh(self) -> float | None:
        """Return forecast energy for the next hour in kWh."""
        return self._forecast_next_hour_kwh

    @property
    def forecast_kwh_per_kwp(self) -> float | None:
        """Return today's forecast normalized by PV array size."""
        return self._forecast.forecast_kwh_per_kwp(
            self._forecast_today_kwh,
            as_float(self.config.get(CONF_PV_SIZE_KWP), 0),
        )

    @property
    def forecast_day_class(self) -> str:
        """Return a coarse forecast class for today's solar yield."""
        return self._forecast.forecast_day_class(
            self._forecast_today_kwh,
            as_float(self.config.get(CONF_PV_SIZE_KWP), 0),
            high_threshold=as_float(
                self.config.get(CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
            ),
            low_threshold=as_float(
                self.config.get(CONF_FORECAST_LOW_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_LOW_THRESHOLD_KWH_PER_KWP,
            ),
        )

    @property
    def daily_forecast_captured_at(self) -> str | None:
        """Return the timestamp used for today's forecast classification."""
        return self._forecast.captured_at_iso()

    def _capture_daily_forecast_if_needed(self) -> None:
        """Capture today's forecast once after the morning cutoff."""
        self._forecast.capture_if_needed(
            dt_util.now(),
            self._forecast_today_kwh,
            as_float(self.config.get(CONF_PV_SIZE_KWP), 0),
            high_threshold=as_float(
                self.config.get(CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
            ),
            low_threshold=as_float(
                self.config.get(CONF_FORECAST_LOW_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_LOW_THRESHOLD_KWH_PER_KWP,
            ),
        )

    def _live_forecast_kwh_per_kwp(self) -> float | None:
        """Return current forecast normalized by configured PV size."""
        return live_forecast_kwh_per_kwp(
            self._forecast_today_kwh,
            as_float(self.config.get(CONF_PV_SIZE_KWP), 0),
        )

    def _classify_forecast_kwh_per_kwp(self, kwh_per_kwp: float | None) -> str:
        """Classify the daily forecast into low, mid, or high."""
        return classify_forecast_kwh_per_kwp(
            kwh_per_kwp,
            high_threshold=as_float(
                self.config.get(CONF_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_HIGH_THRESHOLD_KWH_PER_KWP,
            ),
            low_threshold=as_float(
                self.config.get(CONF_FORECAST_LOW_THRESHOLD_KWH_PER_KWP),
                DEFAULT_FORECAST_LOW_THRESHOLD_KWH_PER_KWP,
            ),
        )


def live_forecast_kwh_per_kwp(
    forecast_today_kwh: float | None,
    pv_size_kwp: float | None,
) -> float | None:
    """Return current forecast normalized by configured PV size."""
    if forecast_today_kwh is None or pv_size_kwp is None or pv_size_kwp <= 0:
        return None
    return round(forecast_today_kwh / pv_size_kwp, 2)


def classify_forecast_kwh_per_kwp(
    kwh_per_kwp: float | None,
    *,
    high_threshold: float | None,
    low_threshold: float | None,
) -> str:
    """Classify the daily forecast into low, mid, or high."""
    if kwh_per_kwp is None:
        return "unknown"

    if high_threshold is not None and kwh_per_kwp >= high_threshold:
        return FORECAST_DAY_MODE_HIGH

    low_threshold = as_float(low_threshold, 0)
    if low_threshold is not None and kwh_per_kwp >= low_threshold:
        return FORECAST_DAY_MODE_MID
    return FORECAST_DAY_MODE_LOW
