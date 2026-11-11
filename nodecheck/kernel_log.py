"""Look for errors the kernel logged since this boot.

The kernel writes messages (printk) into a ring buffer in memory. `dmesg` reads that
buffer directly, but Ubuntu sets kernel.dmesg_restrict=1, so only root may. journald
copies the buffer to disk, and `journalctl -k` can read that copy as any user in the
`adm` group. `-o json` gives one JSON object per line with a numeric PRIORITY
(0 emerg, 1 alert, 2 crit, 3 err, 4 warning, 5 notice, 6 info, 7 debug).

The level is chosen by whoever wrote the printk in the kernel source. It says how urgent
the event is for the kernel, not whether the machine is fit to hand over, so the spec adds
two things on top: the highest priority that counts as an error, and an ignore list of
known harmless messages.

The result has the same shape as the checks in spec.py: {"name", "status", "actual", "expected"},
plus "details": the error messages themselves.
"""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# this boot (-b), kernel only (-k), warning and worse (-p warning)
JOURNALCTL = ["journalctl", "-k", "-b", "-p", "warning", "-o", "json", "--no-pager"]
# where a captured fixture directory keeps the same output
FIXTURE_FILE = Path("commands") / "journalctl-k.jsonl"


def run(command: list[str] = JOURNALCTL) -> str | None:
    """Output of the command, or None if it is missing or fails."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):  # OSError covers "command not found"
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def read(root: Path | str = "/") -> str | None:
    """This machine's journal when root is "/", otherwise the file captured under root."""
    if Path(root) == Path("/"):
        return run()
    path = Path(root) / FIXTURE_FILE
    try:
        return path.read_text()
    except OSError:
        return None


def parse(text: str) -> list[dict]:
    """One dict per journal line: {"priority", "message", "realtime_us", "monotonic_us"}."""
    entries = []
    for line in text.splitlines():
        try:
            record = json.loads(line)
        except ValueError:
            continue  # blank line, or something journalctl printed that isn't an entry
        entries.append(
            {
                "priority": _int(record.get("PRIORITY")),
                "message": _text(record.get("MESSAGE")),
                "realtime_us": _int(record.get("__REALTIME_TIMESTAMP")),
                "monotonic_us": _int(record.get("__MONOTONIC_TIMESTAMP")),
            }
        )
    return entries


def boot_time(entries: list[dict]) -> datetime | None:
    """When this boot started (UTC), worked out from any entry.

    Each entry carries the wall-clock time (realtime) and the time since boot (monotonic),
    both in microseconds, so their difference is the moment the machine booted.
    """
    for e in entries:
        if e["realtime_us"] is not None and e["monotonic_us"] is not None:
            since_epoch = timedelta(microseconds=e["realtime_us"] - e["monotonic_us"])
            return datetime(1970, 1, 1, tzinfo=timezone.utc) + since_epoch
    return None


def check(entries: list[dict] | None, spec: dict) -> dict:
    """PASS: no errors. FAIL: errors not on the spec's ignore list. WARN: log unreadable."""
    max_priority = spec["kernel_log"]["max_priority"]
    ignore = [re.compile(rule["pattern"]) for rule in spec["kernel_log"]["ignore"]]
    expected = f"none at priority <= {max_priority}, this boot"

    if entries is None:
        # not seeing errors is not the same as there being none
        return _result(WARN, "unreadable", expected, [])

    errors, ignored, warnings = [], 0, 0
    for e in entries:
        if e["priority"] is None or e["priority"] > max_priority:
            warnings += 1
        elif any(p.search(e["message"]) for p in ignore):
            ignored += 1
        else:
            errors.append(e["message"])

    started = boot_time(entries)
    if started:
        expected = f"none at priority <= {max_priority}, boot {started:%d %b %H:%M} UTC"
    actual = f"{len(errors)} error{'' if len(errors) == 1 else 's'} ({ignored} ignored, {warnings} warnings)"
    return _result(FAIL if errors else PASS, actual, expected, errors)


def _result(status: str, actual: str, expected: str, details: list[str]) -> dict:
    return {"name": "kernel_log", "status": status, "actual": actual, "expected": expected, "details": details}


def _int(value) -> int | None:
    try:
        return int(value)  # journald writes numbers as strings
    except (TypeError, ValueError):
        return None


def _text(value) -> str:
    if isinstance(value, list):
        # journald writes MESSAGE as a list of byte values when it isn't clean UTF-8
        return bytes(value).decode("utf-8", errors="replace")
    return "" if value is None else str(value)
