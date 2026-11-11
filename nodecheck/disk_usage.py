"""How full the root filesystem is: space and inodes, from `df`.

A disk can be big enough for the spec and still be full. Two ways to run out:
  space   bytes: one big file, or logs that never get rotated
  inodes  one per file or directory: millions of tiny files can use them all up
          while plenty of space is left, and then no new file can be created

`df -P -B1 /` gives bytes, `df -P -i /` gives inodes, both one line per filesystem (-P).
The share used is used / (used + available), as df computes it; df rounds it up, this
module keeps the exact value.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# the filesystem to look at (the spec's disk_usage.mount) is added at the end
DF = ["df", "-P", "-B1"]
DF_INODES = ["df", "-P", "-i"]
# where a captured fixture directory keeps the same output
FIXTURE_FILES = (Path("commands") / "df.txt", Path("commands") / "df-i.txt")


def run(command: list[str]) -> str | None:
    """Output of the command, or None if it is missing or fails."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def read(root: Path | str = "/", mount: str = "/") -> tuple[str | None, str | None]:
    """(df output, df -i output) for mount on this machine when root is "/", else the files captured under root."""
    if Path(root) == Path("/"):
        return run(DF + [mount]), run(DF_INODES + [mount])
    texts = []
    for name in FIXTURE_FILES:
        try:
            texts.append((Path(root) / name).read_text())
        except OSError:
            texts.append(None)
    return texts[0], texts[1]


def parse(text: str) -> dict | None:
    """{"total", "used", "available", "used_pct", "mount"} from `df -P` output (bytes or inodes)."""
    for line in text.splitlines()[1:]:  # the first line is the header
        fields = line.split()
        # filesystem, total, used, available, use%, mount (-P keeps it on one line)
        if len(fields) < 6:
            continue
        try:
            total, used, available = (int(f) for f in fields[1:4])
        except ValueError:
            continue
        usable = used + available
        used_pct = 100 * used / usable if usable else 0.0
        return {"total": total, "used": used, "available": available,
                "used_pct": used_pct, "mount": fields[5]}
    return None


def check(space: dict | None, inodes: dict | None, spec: dict) -> list[dict]:
    """Two results, "disk_usage" and "inode_usage", shaped like the checks in spec.py."""
    rule = spec["disk_usage"]
    return [
        _check_one("disk_usage", space, rule, _bytes_free),
        _check_one("inode_usage", inodes, rule, lambda n: f"{n:,} free"),
    ]


def _check_one(name: str, usage: dict | None, rule: dict, describe_free) -> dict:
    warn, fail = rule["warn_pct"], rule["fail_pct"]
    expected = f"{rule['mount']}: WARN from {warn}%, FAIL from {fail}%"
    if usage is None:
        # df missing or unreadable: not seen is not fine
        return _result(name, WARN, "unreadable", expected)
    pct = usage["used_pct"]
    actual = f"{pct:.0f}% used ({describe_free(usage['available'])})"
    if pct >= fail:
        status = FAIL
    elif pct >= warn:
        status = WARN
    else:
        status = PASS
    return _result(name, status, actual, expected)


def _bytes_free(n: int) -> str:
    return f"{n / 1024**3:.1f} GiB free"


def _result(name: str, status: str, actual: str, expected: str) -> dict:
    return {"name": name, "status": status, "actual": actual, "expected": expected}
