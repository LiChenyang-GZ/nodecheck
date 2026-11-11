"""Look for errors the kernel logged since this boot.

The kernel writes messages (printk) into a ring buffer in memory. `dmesg` reads that
buffer directly, but Ubuntu sets kernel.dmesg_restrict=1, so only root may. journald
copies the buffer to disk, and `journalctl -k` can read that copy as any user in the
`adm` group. `-o json` gives one JSON object per line with a numeric PRIORITY
(0 emerg ... 3 err, 4 warning ... 7 debug).

The result has the same shape as the checks in spec.py: {"name", "status", "actual", "expected"}.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# this boot (-b), kernel only (-k), warning and worse (-p warning)
JOURNALCTL = ["journalctl", "-k", "-b", "-p", "warning", "-o", "json", "--no-pager"]
# where a captured fixture directory keeps the same output
FIXTURE_FILE = Path("commands") / "journalctl-k.jsonl"


def run(command: list[str] = JOURNALCTL) -> str | None:
    """Output of the command, or None if it is missing or fails."""
    # Not implemented yet.
    return ""


def read(root: Path | str = "/") -> str | None:
    """This machine's journal when root is "/", otherwise the file captured under root."""
    # Not implemented yet.
    return ""


def parse(text: str) -> list[dict]:
    """One dict per journal line: {"priority", "message", "realtime_us", "monotonic_us"}."""
    # Not implemented yet.
    return []


def boot_time(entries: list[dict]) -> datetime | None:
    """When this boot started (UTC), worked out from any entry."""
    # Not implemented yet.
    return None


def check(entries: list[dict] | None, spec: dict) -> dict:
    """PASS: no errors. FAIL: errors not on the spec's ignore list. WARN: log unreadable."""
    # Not implemented yet.
    return {"name": "kernel_log", "status": None, "actual": "", "expected": ""}
