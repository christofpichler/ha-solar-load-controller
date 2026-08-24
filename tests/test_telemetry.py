"""Tests for the anonymous installation heartbeat."""

from __future__ import annotations

import asyncio
import sys
import types
import unittest
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parents[1]
CUSTOM_COMPONENTS_DIR = PROJECT_DIR / "custom_components"
PACKAGE_NAME = "custom_components.solar_load_controller"
PACKAGE_DIR = CUSTOM_COMPONENTS_DIR / "solar_load_controller"

custom_components = sys.modules.setdefault(
    "custom_components", types.ModuleType("custom_components")
)
custom_components.__path__ = [str(CUSTOM_COMPONENTS_DIR)]
solar_load_controller = sys.modules.setdefault(
    PACKAGE_NAME, types.ModuleType(PACKAGE_NAME)
)
solar_load_controller.__path__ = [str(PACKAGE_DIR)]
setattr(custom_components, "solar_load_controller", solar_load_controller)

homeassistant = sys.modules.setdefault(
    "homeassistant", types.ModuleType("homeassistant")
)
core = sys.modules.setdefault(
    "homeassistant.core", types.ModuleType("homeassistant.core")
)
helpers = sys.modules.setdefault(
    "homeassistant.helpers", types.ModuleType("homeassistant.helpers")
)
helpers_storage = sys.modules.setdefault(
    "homeassistant.helpers.storage", types.ModuleType("homeassistant.helpers.storage")
)
helpers_event = sys.modules.setdefault(
    "homeassistant.helpers.event", types.ModuleType("homeassistant.helpers.event")
)
helpers_aiohttp = sys.modules.setdefault(
    "homeassistant.helpers.aiohttp_client",
    types.ModuleType("homeassistant.helpers.aiohttp_client"),
)
loader = sys.modules.setdefault(
    "homeassistant.loader", types.ModuleType("homeassistant.loader")
)


def _callback(func):
    return func


core.callback = _callback
core.HomeAssistant = object


class _FakeStore:
    """In-memory stand-in for homeassistant.helpers.storage.Store."""

    _data: dict[str, dict] = {}

    def __init__(self, _hass, _version, key) -> None:
        self.key = key

    async def async_load(self):
        return _FakeStore._data.get(self.key)

    async def async_save(self, data) -> None:
        _FakeStore._data[self.key] = data


helpers_storage.Store = _FakeStore
helpers_event.async_track_time_interval = lambda *a, **k: (lambda: None)


class _FakeResponse:
    def __init__(self, status: int = 200) -> None:
        self.status = status


class _FakeSession:
    """Records calls and can be told to fail."""

    def __init__(self, *, status: int = 200, raises: Exception | None = None) -> None:
        self.status = status
        self.raises = raises
        self.calls: list[tuple[str, dict]] = []

    async def post(self, url, json=None, **_kwargs):
        self.calls.append((url, json))
        if self.raises is not None:
            raise self.raises
        return _FakeResponse(self.status)


_SESSION = _FakeSession()
helpers_aiohttp.async_get_clientsession = lambda _hass: _SESSION


class _FakeIntegration:
    version = "1.3.2"


async def _async_get_integration(_hass, _domain):
    return _FakeIntegration()


loader.async_get_integration = _async_get_integration

from custom_components.solar_load_controller import telemetry  # noqa: E402


class _FakeHass:
    def __init__(self) -> None:
        self.loop = None


def _run(coro):
    return asyncio.run(coro)


class InstallationIdTest(unittest.TestCase):
    def setUp(self) -> None:
        _FakeStore._data.clear()

    def test_id_is_generated_once_and_reused(self) -> None:
        hass = _FakeHass()
        first = _run(telemetry.async_get_installation_id(hass))
        second = _run(telemetry.async_get_installation_id(hass))

        self.assertEqual(first, second)

    def test_id_is_a_random_uuid_not_derived_from_the_host(self) -> None:
        import uuid as uuid_module

        hass = _FakeHass()
        value = _run(telemetry.async_get_installation_id(hass))
        parsed = uuid_module.UUID(value)

        self.assertEqual(parsed.version, 4)

    def test_id_is_shared_across_config_entries(self) -> None:
        """The id identifies the installation, not a single config entry."""
        first = _run(telemetry.async_get_installation_id(_FakeHass()))
        second = _run(telemetry.async_get_installation_id(_FakeHass()))

        self.assertEqual(first, second)
        self.assertEqual(list(_FakeStore._data), ["solar_load_controller_installation_id"])


class HeartbeatPayloadTest(unittest.TestCase):
    def setUp(self) -> None:
        _SESSION.__init__()

    def test_payload_carries_exactly_two_fields(self) -> None:
        ok = _run(
            telemetry.async_send_heartbeat(
                _FakeHass(), installation_id="abc", version="1.3.2"
            )
        )

        self.assertTrue(ok)
        _url, payload = _SESSION.calls[0]
        self.assertEqual(payload, {"installation_id": "abc", "version": "1.3.2"})

    def test_network_failure_is_swallowed(self) -> None:
        _SESSION.raises = OSError("no route to host")

        ok = _run(
            telemetry.async_send_heartbeat(
                _FakeHass(), installation_id="abc", version="1.3.2"
            )
        )

        self.assertFalse(ok)

    def test_error_status_is_reported_but_does_not_raise(self) -> None:
        _SESSION.status = 500

        ok = _run(
            telemetry.async_send_heartbeat(
                _FakeHass(), installation_id="abc", version="1.3.2"
            )
        )

        self.assertFalse(ok)

    def test_cancellation_is_not_swallowed(self) -> None:
        _SESSION.raises = asyncio.CancelledError()

        with self.assertRaises(asyncio.CancelledError):
            _run(
                telemetry.async_send_heartbeat(
                    _FakeHass(), installation_id="abc", version="1.3.2"
                )
            )


if __name__ == "__main__":
    unittest.main()
