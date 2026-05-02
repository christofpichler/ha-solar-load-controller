"""Battery value helpers for Solar Load Controller."""

from __future__ import annotations

from .const import (
    BATTERY_POWER_CHARGING_POSITIVE,
    BATTERY_POWER_DISCHARGING_POSITIVE,
    DEFAULT_BATTERY_POWER_DIRECTION,
)

BATTERY_POWER_NEUTRAL_W = 25


def normalize_battery_power(
    raw_power_w: float | None,
    direction: str | None,
) -> float | None:
    """Return battery power normalized to positive charging values."""
    if raw_power_w is None:
        return None

    if direction == BATTERY_POWER_DISCHARGING_POSITIVE:
        return -raw_power_w
    if direction == BATTERY_POWER_CHARGING_POSITIVE:
        return raw_power_w
    if direction == DEFAULT_BATTERY_POWER_DIRECTION:
        return raw_power_w
    return raw_power_w


def classify_battery_power(
    power_w: float | None,
    neutral_threshold_w: float = BATTERY_POWER_NEUTRAL_W,
) -> str:
    """Return charging, discharging, neutral, or unknown for normalized power."""
    if power_w is None:
        return "unknown"
    if power_w > neutral_threshold_w:
        return "charging"
    if power_w < -neutral_threshold_w:
        return "discharging"
    return "neutral"
