"""JSONL decision-log file I/O for Solar Load Controller.

Coordinator-internal constants and the append/prune function for the
rolling debug log live here so coordinator.py stays focused on decision
logic and state management.

The coordinator handles building the log records (it has access to all
relevant state); this module handles only the file operations.
"""

from __future__ import annotations

import json
import threading
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

DECISION_LOG_FILENAME = "solar_load_controller_decisions.jsonl"
DECISION_LOG_RETENTION_DAYS = 7
DECISION_LOG_MAX_ENTRIES = 2000

# Lock protects the JSONL file against concurrent writes from the HA
# executor thread pool.
_LOG_LOCK = threading.Lock()


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def append_decision_log(path: str, record: dict[str, Any]) -> None:
    """Append *record* to the JSONL log at *path* and prune old history.

    Uses a module-level lock to prevent concurrent writes from the HA
    executor thread pool corrupting the file.

    Fast path: if the file has fewer lines than the maximum, just append —
    no read required.  Full read-filter-rewrite only happens when pruning is
    needed (i.e. the file is at or near the entry limit or contains stale
    records).
    """
    new_line = json.dumps(record, separators=(",", ":")) + "\n"

    with _LOG_LOCK:
        # Count existing lines without parsing to decide if pruning is needed.
        line_count = 0
        try:
            with open(path, encoding="utf-8") as fh:
                for _ in fh:
                    line_count += 1
        except FileNotFoundError:
            pass

        if line_count < DECISION_LOG_MAX_ENTRIES - 1:
            # Fast path: simply append; no pruning needed yet.
            with open(path, "a", encoding="utf-8") as fh:
                fh.write(new_line)
            return

        # Pruning path: read, filter by date and max count, rewrite.
        cutoff_epoch = (
            float(record["timestamp_epoch"])
            - DECISION_LOG_RETENTION_DAYS * 86_400
        )
        records: list[dict[str, Any]] = []
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        existing = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    ts = existing.get("timestamp_epoch")
                    if not isinstance(ts, int | float):
                        records.append(existing)
                    elif ts >= cutoff_epoch:
                        records.append(existing)
        except FileNotFoundError:
            pass

        records.append(record)
        records = records[-DECISION_LOG_MAX_ENTRIES:]

        with open(path, "w", encoding="utf-8") as fh:
            for item in records:
                fh.write(json.dumps(item, separators=(",", ":")))
                fh.write("\n")
