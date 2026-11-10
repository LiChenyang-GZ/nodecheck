"""Step 1: read a node's hardware inventory from /proc and /sys.

Linux exposes hardware state as files: /proc for the kernel's own view (CPU, memory),
/sys for devices (disks, NICs, firmware tables). Commands like lscpu, free and lsblk
read the same files. Reading them directly needs no extra packages and no root.

`root` is where the filesystem starts: "/" on a real node, a fixture directory in tests.
"""
from __future__ import annotations

from pathlib import Path


def collect(root: Path | str = "/") -> dict:
    """Return the node's hardware inventory as a JSON-ready dict."""
    # Not implemented yet: only the shape of the result is defined (step 1, red).
    return {
        "hostname": None,
        "kernel": None,
        "os": None,
        "system": {"vendor": None, "product": None},
        "cpu": {"model": None, "logical_cpus": None, "physical_cores": None},
        "memory": {"total_kib": None, "available_kib": None},
        "disks": [],
        "nics": [],
    }
