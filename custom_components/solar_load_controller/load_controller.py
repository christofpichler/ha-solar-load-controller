"""Load-control state helpers for Solar Load Controller."""

from __future__ import annotations

from datetime import datetime, timedelta

from homeassistant.util import dt as dt_util


class LoadControlState:
    """Track pending service calls and pause-mode manual-control intent."""

    def __init__(self) -> None:
        self.paused_needs_turn_off = False
        self.pending_automatic_turn_on = False
        self.pending_load_state: bool | None = None
        self.pending_decision_reason: str | None = None
        self.pending_load_state_set_at: datetime | None = None

    def set_automation_paused(self, paused: bool, *, is_load_on: bool) -> None:
        """Record pause-mode state used by the coordinator."""
        if paused:
            self.paused_needs_turn_off = is_load_on
        else:
            self.paused_needs_turn_off = False

    def should_respect_manual_on_while_paused(
        self,
        *,
        is_load_on: bool,
        timeout: timedelta,
    ) -> bool:
        """Return whether a paused on-state should be treated as manual."""
        if not is_load_on:
            return False
        return (
            not self.paused_needs_turn_off
            and not self.pending_state_matches(False, timeout=timeout)
        )

    def consume_paused_turn_off(self) -> None:
        """Clear the one-shot pause turn-off marker."""
        self.paused_needs_turn_off = False

    def set_pending_load_state(
        self,
        desired_state: bool,
        *,
        automatic_turn_on: bool,
        decision_reason: str,
        now: datetime | None = None,
    ) -> None:
        """Track an in-flight service call until HA reports the state change."""
        self.pending_load_state = desired_state
        self.pending_load_state_set_at = now or dt_util.utcnow()
        self.pending_automatic_turn_on = automatic_turn_on
        self.pending_decision_reason = decision_reason if automatic_turn_on else None

    def clear_pending_load_state(self, current_state: bool | None = None) -> None:
        """Clear pending state when it is completed or explicitly reset."""
        if current_state is not None and self.pending_load_state != current_state:
            return
        self.pending_load_state = None
        self.pending_load_state_set_at = None
        self.pending_automatic_turn_on = False
        self.pending_decision_reason = None

    def pending_state_matches(
        self,
        desired_state: bool,
        *,
        timeout: timedelta,
        now: datetime | None = None,
    ) -> bool:
        """Return whether the desired service call is already in flight."""
        if self.pending_load_state != desired_state:
            return False
        if self.pending_load_state_set_at is None:
            return False
        now = now or dt_util.utcnow()
        if now - self.pending_load_state_set_at > timeout:
            self.clear_pending_load_state()
            return False
        return True

    def load_change_source(self, current_state: bool, *, timeout: timedelta) -> str:
        """Return whether the current load state change is automatic or manual."""
        if self.pending_state_matches(current_state, timeout=timeout):
            return "automatic"
        return "manual"


class LoadControlMixin:
    """Controller pending-state helpers backed by LoadControlState."""

    def _load_change_source(self, current_state: bool) -> str:
        """Return whether the current load state change is automatic or manual."""
        return self._load_control.load_change_source(
            current_state,
            timeout=self.pending_load_state_timeout,
        )

    def _async_set_pending_load_state(
        self,
        desired_state: bool,
        *,
        automatic_turn_on: bool,
        decision_reason: str,
    ) -> None:
        """Track an in-flight service call until HA reports the state change."""
        self._load_control.set_pending_load_state(
            desired_state,
            automatic_turn_on=automatic_turn_on,
            decision_reason=decision_reason,
        )

    def _async_clear_pending_load_state(self, current_state: bool | None = None) -> None:
        """Clear pending state when it is completed or explicitly reset."""
        self._load_control.clear_pending_load_state(current_state)

    def _pending_load_state_matches(self, desired_state: bool) -> bool:
        """Return whether the desired service call is already in flight."""
        return self._load_control.pending_state_matches(
            desired_state,
            timeout=self.pending_load_state_timeout,
        )
