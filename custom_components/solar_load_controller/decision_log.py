"""JSONL decision-log file I/O for Solar Load Controller.

Coordinator-internal constants and the append function for the rolling debug
log live here so coordinator.py stays focused on decision logic and state
management.

The coordinator handles building the log records (it has access to all
relevant state); this module handles only the file operations.
"""

from __future__ import annotations

import json
import threading
from collections import deque
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECISION_LOG_FILENAME = "solar_load_controller_decisions.jsonl"
DECISION_LOG_MAX_ENTRIES = 2000

# Lock protects the JSONL file against concurrent writes from the HA
# executor thread pool.
_LOG_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_decision_log(path: str, record: dict[str, Any]) -> None:
    """Append *record* and keep only the most recent DECISION_LOG_MAX_ENTRIES.

    Rolling window by line count: below the limit the record is appended; at
    the limit the oldest lines are dropped so the file holds the last
    DECISION_LOG_MAX_ENTRIES decisions. No date-based pruning.

    A module-level lock prevents concurrent writes from the HA executor thread
    pool from corrupting the file.
    """
    new_line = json.dumps(record, separators=(",", ":")) + "\n"

    with _LOG_LOCK:
        line_count = 0
        try:
            with open(path, encoding="utf-8") as fh:
                for _ in fh:
                    line_count += 1
        except FileNotFoundError:
            pass

        if line_count < DECISION_LOG_MAX_ENTRIES:
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(new_line)
            return

        # At the limit: keep the newest lines, drop the oldest, then append.
        keep = deque(maxlen=DECISION_LOG_MAX_ENTRIES - 1)
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    if line.strip():
                        keep.append(line if line.endswith("\n") else line + "\n")
        except FileNotFoundError:
            pass

        with open(path, "w", encoding="utf-8") as fh:
            fh.writelines(keep)
            fh.write(new_line)
