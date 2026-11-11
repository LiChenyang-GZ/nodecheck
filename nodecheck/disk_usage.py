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

from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

DF = ["df", "-P", "-B1", "/"]
DF_INODES = ["df", "-P", "-i", "/"]
# where a captured fixture directory keeps the same output
FIXTURE_FILES = (Path("commands") / "df.txt", Path("commands") / "df-i.txt")


def read(root: Path | str = "/") -> tuple[str | None, str | None]:
    """(df output, df -i output) of this machine when root is "/", else the files captured under root."""
    return None, None


def parse(text: str) -> dict | None:
    """{"total", "used", "available", "used_pct", "mount"} from `df -P` output (bytes or inodes)."""
    return None


def check(space: dict | None, inodes: dict | None, spec: dict) -> list[dict]:
    """Two results, "disk_usage" and "inode_usage", shaped like the checks in spec.py."""
    return []
