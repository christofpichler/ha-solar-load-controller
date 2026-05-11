"""Derived controller metrics for Solar Load Controller."""

from __future__ import annotations

import math
from datetime import datetime

from homeassistant.core import callback
from homeassistant.util import dt as dt_util

from .battery import classify_battery_power, normalize_battery_power
from .const import (
    BATTERY_MODE_PRESERVE,
    CONF_BATTERY_CAPACITY_KWH,
    CONF_BATTERY_MODE,
    CONF_BATTERY_POWER_DIRECTION,
    CONF_BATTERY_POWER_SENSOR,
    CONF_BATTERY_SOC_SENSOR,
    CONF_GRID_EXPORT_SENSOR,
    CONF_GRID_IMPORT_SENSOR,
    CONF_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
    CONF_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
    CONF_INVERTER_LIMIT_W,
    CONF_LOAD_POWER_W,
    CONF_MIN_DAILY_RUNTIME_MINUTES,
    CONF_MIN_RUNTIME_BATTERY_OVERRIDE,
    CONF_MIN_RUNTIME_GRID_OVERRIDE,
    CONF_PV_CURRENT_POWER_SENSOR,
    DECISION_LOW_FORECAST_ASSISTED_RUN,
    DEFAULT_BATTERY_POWER_DIRECTION,
    DEFAULT_FORECAST_WAIT_MINUTES,
    DEFAULT_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
    DEFAULT_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
    DEFAULT_LOAD_POWER_W,
    DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
)
from .energy import (
    household_energy_reserve_kwh,
    required_input_energy,
    time_priority_buffer_kwh,
    usable_battery_charge_for_ac_surplus,
)
from .high_mode import (
    HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS,
    HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS,
)
from .low_mode import (
    LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
    LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
    LOW_FORECAST_ASSISTED_HOLD_SUPPORT_TIME_CONSTANT_SECONDS,
    LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT,
    LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO,
    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO,
    LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
    LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
    LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
    LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
    LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
    assisted_run_effective_surplus_threshold_w as low_mode_assisted_effective_surplus_threshold_w,
    assisted_run_forecast_threshold_kwh as low_mode_assisted_run_forecast_threshold_kwh,
    assisted_run_priority as low_mode_assisted_run_priority,
    assisted_run_strength_ratio as low_mode_assisted_run_strength_ratio,
    assisted_run_surplus_threshold_w as low_mode_assisted_surplus_threshold_w,
    forecast_wait_threshold_kwh as low_mode_forecast_wait_threshold_kwh,
    runtime_pressure as low_mode_runtime_pressure,
    runtime_wait_buffer_minutes as low_mode_runtime_wait_buffer_minutes,
)
from .mid_mode import MID_FORECAST_ASSISTED_SURPLUS_RATIO, MID_FORECAST_WAIT_NEXT_HOUR_RATIO
from .sensor_reader import as_float


class ControllerMetricsMixin:
    """Derived values exposed by coordinator-backed entities and decisions."""

    @property
    def available_surplus_w(self) -> float:
        export_w = self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))
        import_w = self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR))
        if export_w is None or import_w is None:
            return 0.0
        return round(max(0.0, export_w - import_w), 1)

    @property
    def effective_solar_surplus_w(self) -> float:
        active_load_w = self.load_power_w if self.is_load_on else 0.0
        return round(
            self.available_surplus_w + self.usable_battery_charge_w + active_load_w,
            1,
        )

    @property
    def usable_battery_charge_w(self) -> float:
        return usable_battery_charge_for_ac_surplus(
            max(0.0, self.battery_power_w or 0.0),
            self.pv_current_power_w,
            self.inverter_limit_w,
        )

    @property
    def grid_export_w(self) -> float | None:
        return self._positive_state_value(self.config.get(CONF_GRID_EXPORT_SENSOR))

    @property
    def grid_import_w(self) -> float | None:
        return self._positive_state_value(self.config.get(CONF_GRID_IMPORT_SENSOR))

    @property
    def pv_current_power_w(self) -> float | None:
        return self._positive_state_value(self.config.get(CONF_PV_CURRENT_POWER_SENSOR))

    @property
    def inverter_limit_w(self) -> float | None:
        return as_float(self.config.get(CONF_INVERTER_LIMIT_W))

    @property
    def high_mode_base_household_load_w(self) -> float:
        return as_float(
            self.config.get(CONF_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W),
            DEFAULT_HIGH_MODE_BASE_HOUSEHOLD_LOAD_W,
        )

    @property
    def high_mode_household_reserve_margin_percent(self) -> float:
        return as_float(
            self.config.get(CONF_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT),
            DEFAULT_HIGH_MODE_HOUSEHOLD_RESERVE_MARGIN_PERCENT,
        )

    @property
    def high_mode_household_reserve_kwh(self) -> float:
        return household_energy_reserve_kwh(
            self.high_mode_base_household_load_w,
            self.high_mode_household_reserve_margin_percent,
            max(0.0, self.minutes_until_finish) / 60,
        )

    @property
    def high_mode_time_priority_buffer_kwh(self) -> float:
        total_window_minutes = self._total_window_minutes
        if total_window_minutes <= 0:
            progress = 0.0
        else:
            elapsed = max(
                0.0,
                min(total_window_minutes, total_window_minutes - self.minutes_until_finish),
            )
            progress = elapsed / total_window_minutes

        return time_priority_buffer_kwh(
            self.high_mode_base_household_load_w,
            self.high_mode_household_reserve_margin_percent,
            progress,
            min_hours=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MIN_HOURS,
            max_hours=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_MAX_HOURS,
            exponent=HIGH_FORECAST_POST_RUNTIME_PRIORITY_BUFFER_EXPONENT,
        )

    @property
    def runtime_progress(self) -> float:
        total_window_minutes = self._total_window_minutes
        if total_window_minutes <= 0:
            return 0.0
        elapsed = max(
            0.0,
            min(total_window_minutes, total_window_minutes - self.minutes_until_finish),
        )
        return round(elapsed / total_window_minutes, 3)

    @property
    def runtime_slack_minutes(self) -> float:
        return round(
            max(0.0, self.minutes_until_finish - self.runtime_remaining_today_minutes),
            1,
        )

    @property
    def low_mode_runtime_progress(self) -> float:
        return self.runtime_progress

    @property
    def low_mode_runtime_pressure(self) -> float:
        return round(
            low_mode_runtime_pressure(
                self.low_mode_runtime_progress,
                exponent=LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
            ),
            3,
        )

    @property
    def low_mode_runtime_slack_minutes(self) -> float:
        return self.runtime_slack_minutes

    @property
    def low_mode_runtime_wait_buffer_minutes(self) -> float:
        min_daily_runtime_minutes = as_float(
            self.config.get(CONF_MIN_DAILY_RUNTIME_MINUTES),
            DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
        )
        return low_mode_runtime_wait_buffer_minutes(
            min_daily_runtime_minutes,
            self.low_mode_runtime_progress,
            min_ratio=LOW_FORECAST_RUNTIME_BUFFER_MIN_RATIO,
            max_ratio=LOW_FORECAST_RUNTIME_BUFFER_MAX_RATIO,
            exponent=LOW_FORECAST_RUNTIME_BUFFER_EXPONENT,
        )

    @property
    def low_mode_forecast_wait_threshold_kwh(self) -> float:
        return low_mode_forecast_wait_threshold_kwh(
            self.load_power_w,
            DEFAULT_FORECAST_WAIT_MINUTES,
            self.low_mode_runtime_pressure,
            min_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MIN_MULTIPLIER,
            max_multiplier=LOW_FORECAST_WAIT_THRESHOLD_MAX_MULTIPLIER,
        )

    @property
    def low_mode_assisted_surplus_threshold_w(self) -> float:
        return low_mode_assisted_surplus_threshold_w(
            self.load_power_w,
            self.low_mode_runtime_pressure,
            early_ratio=LOW_FORECAST_ASSISTED_SURPLUS_EARLY_RATIO,
            late_ratio=LOW_FORECAST_ASSISTED_SURPLUS_LATE_RATIO,
        )

    @property
    def low_mode_assisted_start_surplus_w(self) -> float:
        return round(self.available_surplus_w + self.usable_battery_charge_w, 1)

    @property
    def low_mode_assisted_hold_support_w(self) -> float:
        if not (
            self.is_load_on
            and self._tracker.active_runtime_reason == DECISION_LOW_FORECAST_ASSISTED_RUN
        ):
            return self.low_mode_assisted_start_surplus_w
        return round(
            max(
                self.low_mode_assisted_start_surplus_w,
                self._decayed_low_assist_hold_support_w(),
            ),
            1,
        )

    @property
    def low_mode_assisted_strength_ratio(self) -> float:
        return low_mode_assisted_run_strength_ratio(
            self.low_mode_assisted_start_surplus_w,
            self.low_mode_assisted_surplus_threshold_w,
        )

    @property
    def low_mode_assisted_priority(self) -> float:
        return low_mode_assisted_run_priority(
            self.low_mode_runtime_progress,
            exponent=LOW_FORECAST_ASSISTED_PRIORITY_EXPONENT,
        )

    @property
    def low_mode_assisted_effective_surplus_threshold_w(self) -> float:
        return low_mode_assisted_effective_surplus_threshold_w(
            self.low_mode_assisted_surplus_threshold_w,
            self.low_mode_assisted_priority,
            late_relief_ratio=LOW_FORECAST_ASSISTED_SURPLUS_LATE_RELIEF_RATIO,
        )

    @property
    def low_mode_assisted_forecast_threshold_kwh(self) -> float:
        return low_mode_assisted_run_forecast_threshold_kwh(
            self.low_mode_forecast_wait_threshold_kwh,
            self.low_mode_assisted_start_surplus_w,
            self.low_mode_assisted_effective_surplus_threshold_w,
            assist_priority=self.low_mode_assisted_priority,
            ratio_span=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_RATIO_SPAN,
            exponent=LOW_FORECAST_ASSISTED_FORECAST_OVERRIDE_EXPONENT,
            late_relief_ratio=LOW_FORECAST_ASSISTED_FORECAST_LATE_RELIEF_RATIO,
        )

    @property
    def mid_mode_assisted_surplus_threshold_w(self) -> float:
        return round(self.load_power_w * MID_FORECAST_ASSISTED_SURPLUS_RATIO, 1)

    @property
    def mid_mode_solar_surplus_w(self) -> float:
        return self.available_surplus_w

    @property
    def mid_mode_forecast_wait_threshold_kwh(self) -> float:
        return round(self.load_power_w * MID_FORECAST_WAIT_NEXT_HOUR_RATIO / 1000, 4)

    def _decayed_low_assist_hold_support_w(
        self,
        now: datetime | None = None,
    ) -> float:
        if (
            self._low_assist_hold_support_updated_at is None
            or self._low_assist_hold_support_w <= 0
        ):
            return 0.0
        now = now or dt_util.utcnow()
        elapsed_seconds = max(
            0.0,
            (now - self._low_assist_hold_support_updated_at).total_seconds(),
        )
        tau = max(1.0, LOW_FORECAST_ASSISTED_HOLD_SUPPORT_TIME_CONSTANT_SECONDS)
        return self._low_assist_hold_support_w * math.exp(-elapsed_seconds / tau)

    @callback
    def _async_update_low_assist_hold_support(
        self,
        now: datetime | None = None,
    ) -> None:
        now = now or dt_util.utcnow()
        if not (
            self.is_load_on
            and self._tracker.active_runtime_reason == DECISION_LOW_FORECAST_ASSISTED_RUN
        ):
            self._low_assist_hold_support_w = 0.0
            self._low_assist_hold_support_updated_at = None
            return
        current_support_w = self.low_mode_assisted_start_surplus_w
        remembered_support_w = self._decayed_low_assist_hold_support_w(now)
        self._low_assist_hold_support_w = max(current_support_w, remembered_support_w)
        self._low_assist_hold_support_updated_at = now

    @property
    def projected_grid_import_w(self) -> float | None:
        import_w = self.grid_import_w
        export_w = self.grid_export_w
        if import_w is None or export_w is None:
            return None
        if self.is_load_on:
            return import_w
        return round(max(0.0, import_w - export_w + self.load_power_w), 1)

    @property
    def projected_grid_import_formula(self) -> str:
        if self.is_load_on:
            return "current_grid_import"
        return "current_grid_import - current_grid_export + load_power"

    @property
    def load_power_w(self) -> float:
        return as_float(self.config.get(CONF_LOAD_POWER_W), DEFAULT_LOAD_POWER_W)

    @property
    def min_runtime_grid_override(self) -> bool:
        return bool(self.config.get(CONF_MIN_RUNTIME_GRID_OVERRIDE, True))

    @property
    def min_runtime_battery_override(self) -> bool:
        return bool(self.config.get(CONF_MIN_RUNTIME_BATTERY_OVERRIDE, False))

    @property
    def runtime_remaining_today_minutes(self) -> float:
        minimum_minutes = as_float(
            self.config.get(CONF_MIN_DAILY_RUNTIME_MINUTES),
            DEFAULT_MIN_DAILY_RUNTIME_MINUTES,
        )
        return round(max(0.0, minimum_minutes - self.runtime_today_minutes), 1)

    @property
    def required_remaining_energy_kwh(self) -> float:
        return round(self.load_power_w * self.runtime_remaining_today_minutes / 60 / 1000, 3)

    @property
    def battery_soc(self) -> float | None:
        return self._positive_state_value(self.config.get(CONF_BATTERY_SOC_SENSOR))

    @property
    def battery_power_w(self) -> float | None:
        return normalize_battery_power(
            self.battery_power_raw_w,
            self.battery_power_direction,
        )

    @property
    def battery_power_raw_w(self) -> float | None:
        return self._state_as_float(self.config.get(CONF_BATTERY_POWER_SENSOR))

    @property
    def battery_power_direction(self) -> str:
        return str(
            self.config.get(
                CONF_BATTERY_POWER_DIRECTION,
                DEFAULT_BATTERY_POWER_DIRECTION,
            )
        )

    @property
    def battery_power_state(self) -> str:
        return classify_battery_power(self.battery_power_w)

    @property
    def battery_mode(self) -> str:
        return str(self.config.get(CONF_BATTERY_MODE, BATTERY_MODE_PRESERVE))

    @property
    def battery_headroom_kwh(self) -> float | None:
        capacity_kwh = as_float(self.config.get(CONF_BATTERY_CAPACITY_KWH))
        soc = self.battery_soc
        if capacity_kwh is None or capacity_kwh <= 0 or soc is None:
            return None
        return round(capacity_kwh * max(0.0, 100.0 - soc) / 100, 3)

    @property
    def forecast_excess_after_battery_kwh(self) -> float | None:
        forecast_remaining_kwh = self.forecast_remaining_today_kwh
        battery_charge_required_kwh = self.battery_charge_required_kwh
        if forecast_remaining_kwh is None or battery_charge_required_kwh is None:
            return None
        return round(forecast_remaining_kwh - battery_charge_required_kwh, 3)

    @property
    def battery_charge_required_kwh(self) -> float | None:
        return self._charging_input_energy_for_storage(self.battery_headroom_kwh)

    @property
    def high_forecast_post_runtime_battery_charge_required_kwh(self) -> float | None:
        return self._charging_input_energy_for_storage(
            self._battery_headroom_to_target_kwh(
                HIGH_FORECAST_POST_RUNTIME_BATTERY_TARGET_SOC
            )
        )

    def _battery_headroom_to_target_kwh(self, target_soc: float) -> float | None:
        capacity_kwh = as_float(self.config.get(CONF_BATTERY_CAPACITY_KWH))
        soc = self.battery_soc
        if capacity_kwh is None or capacity_kwh <= 0 or soc is None:
            return None
        return round(
            capacity_kwh * max(0.0, target_soc - min(100.0, soc)) / 100.0,
            3,
        )

    def _charging_input_energy_for_storage(
        self, storage_kwh: float | None
    ) -> float | None:
        return required_input_energy(storage_kwh, self.battery_charging_efficiency)
