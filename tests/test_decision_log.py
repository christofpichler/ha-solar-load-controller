"""Tests for the rolling JSONL decision log."""

from __future__ import annotations

import json
import sys
import tempfile
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

from custom_components.solar_load_controller.decision_log import (
    DECISION_LOG_MAX_ENTRIES,
    append_decision_log,
)


class DecisionLogRollingTest(unittest.TestCase):
    """The log keeps the most recent MAX_ENTRIES lines, oldest dropped first."""

    def setUp(self) -> None:
        self._dir = tempfile.TemporaryDirectory()
        self.path = str(Path(self._dir.name) / "log.jsonl")

    def tearDown(self) -> None:
        self._dir.cleanup()

    def _write(self, n: int) -> None:
        append_decision_log(self.path, {"timestamp_epoch": 1_000_000 + n, "n": n})

    def _read(self) -> list[dict]:
        return [json.loads(line) for line in open(self.path) if line.strip()]

    def test_below_limit_appends_in_order(self) -> None:
        for i in range(5):
            self._write(i)
        self.assertEqual([r["n"] for r in self._read()], [0, 1, 2, 3, 4])

    def test_at_limit_holds_exactly_max(self) -> None:
        for i in range(DECISION_LOG_MAX_ENTRIES):
            self._write(i)
        self.assertEqual(len(self._read()), DECISION_LOG_MAX_ENTRIES)

    def test_over_limit_drops_oldest_first(self) -> None:
        for i in range(DECISION_LOG_MAX_ENTRIES + 1):
            self._write(i)
        rows = self._read()
        self.assertEqual(len(rows), DECISION_LOG_MAX_ENTRIES)
        self.assertEqual(rows[0]["n"], 1)  # the very first record is gone
        self.assertEqual(rows[-1]["n"], DECISION_LOG_MAX_ENTRIES)

    def test_window_stays_contiguous_and_bounded(self) -> None:
        for i in range(DECISION_LOG_MAX_ENTRIES + 50):
            self._write(i)
        rows = self._read()
        ns = [r["n"] for r in rows]
        self.assertEqual(len(rows), DECISION_LOG_MAX_ENTRIES)
        self.assertEqual(ns, list(range(ns[0], ns[0] + len(ns))))
        self.assertEqual(ns[-1], DECISION_LOG_MAX_ENTRIES + 49)

    def test_old_timestamps_are_not_pruned(self) -> None:
        """No date filter: an ancient record is kept like any other."""
        for i in range(DECISION_LOG_MAX_ENTRIES):
            self._write(i)
        append_decision_log(self.path, {"timestamp_epoch": 1, "n": -1})
        rows = self._read()
        self.assertEqual(len(rows), DECISION_LOG_MAX_ENTRIES)
        self.assertEqual(rows[-1]["n"], -1)

    def test_first_write_creates_the_file(self) -> None:
        self._write(0)
        self.assertEqual(len(self._read()), 1)


if __name__ == "__main__":
    unittest.main()
