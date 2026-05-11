"""DecisionInputs assembly for Solar Load Controller."""

from __future__ import annotations

from .decision_engine import DecisionInputs


def build_decision_inputs(view) -> DecisionInputs:
    """Return a pure snapshot for the decision engine."""
    runtime_remaining = view.runtime_remaining_today_minutes
    return DecisionInputs(
        is_load_on=view.is_load_on,
        automation_paused=view.automation_paused,
        inside_time_window=view.inside_time_window,
        missing_required_grid_sensor_value=view._missing_required_grid_sensor_value,
        grid_import_w=view.grid_import_w,
        grid_export_w=view.grid_export_w,
        grid_import_limit_w=view.grid_import_limit_w,
        grid_import_start_limit_w=view.grid_import_start_limit_w,
        grid_import_over_limit_duration_seconds=(
            view.grid_import_over_limit_duration_seconds
        ),
        grid_import_shutdown_delay_seconds=(
            view.grid_import_shutdown_delay_seconds
        ),
        grid_import_shutdown_allowed=view.grid_import_shutdown_allowed,
        grid_import_cooldown_active=view.grid_import_cooldown_active,
        grid_import_cooldown_remaining_seconds=(
            view.grid_import_cooldown_remaining_seconds
        ),
        projected_grid_import_w=view.projected_grid_import_w,
        projected_grid_import_formula=view.projected_grid_import_formula,
        available_surplus_w=view.available_surplus_w,
        effective_solar_surplus_w=view.effective_solar_surplus_w,
        load_power_w=view.load_power_w,
        runtime_today_minutes=view.runtime_today_minutes,
        runtime_remaining_minutes=runtime_remaining,
        required_remaining_energy_kwh=view.required_remaining_energy_kwh,
        minutes_until_finish=view.minutes_until_finish,
        low_mode_runtime_progress=view.low_mode_runtime_progress,
        low_mode_runtime_pressure=view.low_mode_runtime_pressure,
        low_mode_runtime_slack_minutes=view.low_mode_runtime_slack_minutes,
        low_mode_runtime_wait_buffer_minutes=(
            view.low_mode_runtime_wait_buffer_minutes
        ),
        low_mode_forecast_wait_threshold_kwh=(
            view.low_mode_forecast_wait_threshold_kwh
        ),
        low_mode_assisted_surplus_threshold_w=(
            view.low_mode_assisted_surplus_threshold_w
        ),
        low_mode_assisted_effective_surplus_threshold_w=(
            view.low_mode_assisted_effective_surplus_threshold_w
        ),
        low_mode_assisted_start_surplus_w=(
            view.low_mode_assisted_start_surplus_w
        ),
        low_mode_assisted_strength_ratio=(
            view.low_mode_assisted_strength_ratio
        ),
        low_mode_assisted_priority=view.low_mode_assisted_priority,
        low_mode_assisted_forecast_threshold_kwh=(
            view.low_mode_assisted_forecast_threshold_kwh
        ),
        min_on_active=view.min_on_active,
        min_on_remaining_minutes=view.min_on_remaining_minutes,
        min_off_active=view.min_off_active,
        min_off_remaining_minutes=view.min_off_remaining_minutes,
        export_guard_run_available=view._export_guard_run_available,
        battery_priority_after_runtime=(
            view._should_prioritize_battery_after_runtime()
        ),
        battery_headroom_kwh=view.battery_headroom_kwh,
        battery_charge_required_kwh=view.battery_charge_required_kwh,
        high_forecast_post_runtime_battery_charge_required_kwh=(
            view.high_forecast_post_runtime_battery_charge_required_kwh
        ),
        high_mode_base_household_load_w=view.high_mode_base_household_load_w,
        high_mode_household_reserve_margin_percent=(
            view.high_mode_household_reserve_margin_percent
        ),
        high_mode_household_reserve_kwh=view.high_mode_household_reserve_kwh,
        forecast_excess_after_battery_kwh=view.forecast_excess_after_battery_kwh,
        forecast_assisted_run_available=view._forecast_assisted_run_available,
        high_forecast_grid_import_active=view._high_forecast_grid_import_active,
        high_forecast_grid_import_duration_seconds=(
            view.high_forecast_grid_import_duration_seconds
        ),
        high_forecast_grid_import_shutdown_delay_seconds=(
            view.high_forecast_grid_import_shutdown_delay_seconds
        ),
        runtime_force_latched=view._runtime_force_latched,
        must_force_minimum_runtime=view._must_force_minimum_runtime(
            runtime_remaining
        ),
        min_runtime_battery_override=view.min_runtime_battery_override,
        min_runtime_grid_override=view.min_runtime_grid_override,
        projected_grid_import_exceeds_limit=(
            view._projected_grid_import_exceeds_limit
        ),
        battery_can_support_forced_runtime=(
            view._battery_can_support_forced_runtime(runtime_remaining)
        ),
        should_wait_for_forecast=view._should_wait_for_forecast,
        mid_mode_assisted_surplus_threshold_w=(
            view.mid_mode_assisted_surplus_threshold_w
        ),
        mid_mode_solar_surplus_w=view.mid_mode_solar_surplus_w,
        mid_mode_forecast_wait_threshold_kwh=(
            view.mid_mode_forecast_wait_threshold_kwh
        ),
        battery_mode=view.battery_mode,
        battery_soc=view.battery_soc,
        battery_power_w=view.battery_power_w,
        battery_power_state=view.battery_power_state,
        forecast_today_kwh=view.forecast_today_kwh,
        forecast_remaining_today_kwh=view.forecast_remaining_today_kwh,
        forecast_next_hour_kwh=view.forecast_next_hour_kwh,
        forecast_kwh_per_kwp=view.forecast_kwh_per_kwp,
        forecast_day_class=view.forecast_day_class,
    )


class DecisionInputsMixin:
    """Controller DecisionInputs property."""

    @property
    def _decision_inputs(self) -> DecisionInputs:
        """Return a pure snapshot for the decision engine."""
        return build_decision_inputs(self)
