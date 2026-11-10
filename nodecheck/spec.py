"""Compare a node's inventory (see inventory.py) with the expected spec for its machine type.

Each check gives one of three statuses:
  FAIL  less than the spec, or missing (a core, memory, the disk, a NIC). Not fit to hand over.
  WARN  not wrong, but a person should look: more than the spec, unreadable,
        or not verifiable on this platform.
  PASS  matches the spec.
"""
from __future__ import annotations

import json
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"


def load_spec(path: Path | str) -> dict:
    """Read a machine-type spec, e.g. config/b2ats_v2.json."""
    return json.loads(Path(path).read_text())


def check(inventory: dict, spec: dict) -> list[dict]:
    """One result per check: {"name", "status", "actual", "expected"}."""
    # Not implemented yet: no checks run.
    return []


def format_report(results: list[dict], spec: dict) -> str:
    """Human-readable table, one line per check, plus a result line."""
    # Not implemented yet.
    return ""
