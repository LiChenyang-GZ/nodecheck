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
_SEVERITY = {PASS: 0, WARN: 1, FAIL: 2}
_MAX_DETAILS = 5  # detail lines shown per check in the report

GIB = 1024**3  # bytes
KIB_PER_GIB = 1024**2  # /proc/meminfo counts in KiB


def load_spec(path: Path | str) -> dict:
    """Read a machine-type spec, e.g. config/b2ats_v2.json."""
    return json.loads(Path(path).read_text())


def check(inventory: dict, spec: dict) -> list[dict]:
    """One result per check: {"name", "status", "actual", "expected"}."""
    return [
        _check_cpu(inventory, spec),
        _check_memory(inventory, spec),
        _check_disk(inventory, spec),
        _check_disk_type(inventory, spec),
        _check_nics(inventory, spec),
        _check_os(inventory, spec),
    ]


def has_failures(results: list[dict]) -> bool:
    return any(r["status"] == FAIL for r in results)


def format_report(results: list[dict], spec: dict) -> str:
    """Human-readable table, one line per check (and its details, if any), plus a result line."""
    lines = [f"Spec: {spec.get('model', '(unnamed)')}"]
    width = max([10] + [len(r["name"]) for r in results])  # benchmark names are longer than "cpu"
    for r in results:
        lines.append(f"  {r['name']:<{width}} {r['actual']:<34} expected {r['expected']:<44} {r['status']}")
        # e.g. the kernel errors themselves, so the report says what went wrong, not just how many
        details = r.get("details", [])
        lines.extend(f"    {d}" for d in details[:_MAX_DETAILS])
        if len(details) > _MAX_DETAILS:
            lines.append(f"    ... and {len(details) - _MAX_DETAILS} more")
    fails = sum(r["status"] == FAIL for r in results)
    warns = sum(r["status"] == WARN for r in results)
    lines.append(f"Result: {fails} FAIL, {warns} WARN")
    return "\n".join(lines)


def _result(name: str, status: str, actual: str, expected: str) -> dict:
    return {"name": name, "status": status, "actual": actual, "expected": expected}


def _compare_count(have: int | None, want: int) -> str:
    """Fewer than ordered is a fault; more than ordered is surprising but not a fault."""
    if have is None:
        return WARN
    if have < want:
        return FAIL
    if have > want:
        return WARN
    return PASS


def _check_cpu(inventory: dict, spec: dict) -> dict:
    # Compared with logical CPUs: an Azure vCPU is a hardware thread, not a core.
    want = spec["cpu"]["logical_cpus"]
    have = inventory["cpu"]["logical_cpus"]
    actual = "unreadable" if have is None else f"{have} logical CPUs"
    return _result("cpu", _compare_count(have, want), actual, str(want))


def _check_memory(inventory: dict, spec: dict) -> dict:
    # MemTotal is RAM minus firmware/kernel reservations, so it never reaches the
    # advertised size. The spec says how much of it must be visible (min_ratio).
    gib = spec["memory"]["gib"]
    ratio = spec["memory"]["min_ratio"]
    need_kib = gib * ratio * KIB_PER_GIB
    expected = f">= {gib * ratio:.2f} GiB ({gib} GiB x {ratio})"

    have_kib = inventory["memory"]["total_kib"]
    if have_kib is None:
        return _result("memory", WARN, "unreadable", expected)
    actual = f"{have_kib / KIB_PER_GIB:.2f} GiB"
    if have_kib < need_kib:
        return _result("memory", FAIL, actual, expected)
    if have_kib > gib * KIB_PER_GIB:
        return _result("memory", WARN, actual + " (more than ordered)", expected)
    return _result("memory", PASS, actual, expected)


def _big_enough_disks(inventory: dict, spec: dict) -> list[dict]:
    min_bytes = spec["disk"]["min_size_gib"] * GIB
    return [d for d in inventory["disks"] if d["size_bytes"] is not None and d["size_bytes"] >= min_bytes]


def _check_disk(inventory: dict, spec: dict) -> dict:
    expected = f">= {spec['disk']['min_size_gib']} GiB"
    disks = inventory["disks"]
    if not disks:
        return _result("disk", FAIL, "no disks", expected)
    largest = max(disks, key=lambda d: d["size_bytes"] or 0)
    actual = f"{largest['name']} {(largest['size_bytes'] or 0) / GIB:.0f} GiB"
    status = PASS if _big_enough_disks(inventory, spec) else FAIL
    return _result("disk", status, actual, expected)


def _check_disk_type(inventory: dict, spec: dict) -> dict:
    want = spec["disk"]["type"]  # "ssd" or "hdd"
    if not spec["disk"]["check_type"]:
        # e.g. Azure: virtual disks report rotational=1 even on SSD
        return _result("disk_type", WARN, "not trusted here", f"{want} (not verifiable on this platform)")

    disks = _big_enough_disks(inventory, spec)
    if not disks:
        return _result("disk_type", WARN, "no disk to check", want)
    statuses = []
    for disk in disks:
        rotational = disk["rotational"]
        if rotational is None:
            statuses.append(WARN)
        else:
            is_ssd = not rotational
            statuses.append(PASS if is_ssd == (want == "ssd") else FAIL)
    actual = ", ".join(
        f"{d['name']} " + {True: "hdd", False: "ssd", None: "unknown"}[d["rotational"]] for d in disks
    )
    # with several disks, the worst one decides
    return _result("disk_type", max(statuses, key=_SEVERITY.get), actual, want)


def _check_nics(inventory: dict, spec: dict) -> dict:
    # Only presence and link state. The speed a driver claims is not trusted;
    # throughput is measured by benchmarks instead.
    want = spec["nics"]["min_up"]
    up = [n["name"] for n in inventory["nics"] if n["state"] == "up"]
    actual = f"{len(up)} up" + (f" ({', '.join(up)})" if up else "")
    status = PASS if len(up) >= want else FAIL
    return _result("nics", status, actual, f">= {want} up")


def _check_os(inventory: dict, spec: dict) -> dict:
    prefix = spec["os"]["prefix"]
    have = inventory["os"]
    if have is None:
        return _result("os", WARN, "unreadable", f"{prefix}*")
    status = PASS if have.startswith(prefix) else FAIL
    return _result("os", status, have, f"{prefix}*")
