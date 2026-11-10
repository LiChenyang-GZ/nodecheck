"""Compare the inventory with the machine-type spec (config/b2ats_v2.json).

The base inventory is node-1's real one (from tests/fixtures/node-1). Each fault is made by
changing one field of a copy, so every test shows exactly which difference changes the verdict.
"""
import copy
import json
from pathlib import Path

import pytest

from nodecheck.__main__ import main
from nodecheck.inventory import collect
from nodecheck.spec import check, format_report, load_spec

ROOT = Path(__file__).parent.parent
NODE1 = ROOT / "tests" / "fixtures" / "node-1"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"
GIB_IN_KIB = 1024 * 1024


@pytest.fixture
def spec():
    return load_spec(SPEC_FILE)


@pytest.fixture
def node1():
    return collect(NODE1)


def status_of(results, name):
    """Status of one check, or None if that check didn't run."""
    return next((r["status"] for r in results if r["name"] == name), None)


def test_real_node1_passes_the_spec_with_one_warn_for_disk_type(spec, node1):
    results = check(node1, spec)

    assert {r["name"]: r["status"] for r in results} == {
        "cpu": "PASS",
        "memory": "PASS",  # 0.82 GiB of 1 GiB, above the 0.8 ratio
        "disk": "PASS",
        "disk_type": "WARN",  # Azure reports rotational=1 on SSD: not verifiable here
        "nics": "PASS",
        "os": "PASS",
    }


@pytest.mark.parametrize(
    "logical_cpus, expected",
    [(2, "PASS"), (1, "FAIL"), (4, "WARN"), (None, "WARN")],
    ids=["as-spec", "one-missing", "more-than-ordered", "unreadable"],
)
def test_cpu_fewer_fails_more_warns(spec, node1, logical_cpus, expected):
    node1["cpu"]["logical_cpus"] = logical_cpus

    assert status_of(check(node1, spec), "cpu") == expected


@pytest.mark.parametrize(
    "total_kib, expected",
    [
        (857080, "PASS"),  # the real value: 0.82 GiB
        (int(0.81 * GIB_IN_KIB), "PASS"),
        (int(0.79 * GIB_IN_KIB), "FAIL"),  # just under 1 GiB x 0.8
        (None, "WARN"),
    ],
    ids=["real-0.82", "0.81", "0.79", "unreadable"],
)
def test_memory_uses_the_min_ratio_from_the_spec(spec, node1, total_kib, expected):
    node1["memory"]["total_kib"] = total_kib

    assert status_of(check(node1, spec), "memory") == expected


def test_memory_ratio_comes_from_the_spec_not_the_code(spec, node1):
    # A big-server style spec: 0.95. The same 0.82 GiB now fails.
    spec["memory"]["min_ratio"] = 0.95

    assert status_of(check(node1, spec), "memory") == "FAIL"


def test_missing_or_too_small_disk_fails(spec, node1):
    small = copy.deepcopy(node1)
    small["disks"][0]["size_bytes"] = 32 * 1024**3
    none = copy.deepcopy(node1)
    none["disks"] = []

    assert status_of(check(small, spec), "disk") == "FAIL"
    assert status_of(check(none, spec), "disk") == "FAIL"


@pytest.mark.parametrize(
    "rotational, expected",
    [(False, "PASS"), (True, "FAIL"), (None, "WARN")],
    ids=["ssd", "spinning", "unknown"],
)
def test_disk_type_is_checked_only_when_the_spec_says_so(spec, node1, rotational, expected):
    # On bare metal rotational is reliable, so the spec turns the check on.
    spec["disk"]["check_type"] = True
    node1["disks"][0]["rotational"] = rotational

    assert status_of(check(node1, spec), "disk_type") == expected


def test_nic_down_fails_but_claimed_speed_is_ignored(spec, node1):
    slow = copy.deepcopy(node1)
    slow["nics"][0]["speed_mbps"] = 10  # claimed speed is not trusted; benchmarks measure it
    down = copy.deepcopy(node1)
    down["nics"][0]["state"] = "down"

    assert status_of(check(slow, spec), "nics") == "PASS"
    assert status_of(check(down, spec), "nics") == "FAIL"


@pytest.mark.parametrize(
    "os_name, expected",
    [("Ubuntu 24.04.5 LTS", "PASS"), ("Ubuntu 22.04.4 LTS", "FAIL"), (None, "WARN")],
    ids=["24.04", "22.04", "unreadable"],
)
def test_os_must_match_the_spec_prefix(spec, node1, os_name, expected):
    node1["os"] = os_name

    assert status_of(check(node1, spec), "os") == expected


def test_report_has_one_line_per_check_and_a_result_line(spec, node1):
    report = format_report(check(node1, spec), spec)
    lines = report.splitlines()

    assert len(lines) == 8  # spec line, 6 checks, result line
    assert "Azure Standard_B2ats_v2" in lines[0]
    assert any(line.startswith("  memory") and line.endswith("PASS") for line in lines)
    assert any(line.startswith("  disk_type") and line.endswith("WARN") for line in lines)
    assert lines[-1] == "Result: 0 FAIL, 1 WARN"


def test_cli_check_exit_code_is_1_only_when_something_fails(tmp_path, capsys):
    ok = main(["check", "--spec", str(SPEC_FILE), "--root", str(NODE1)])
    ok_out = capsys.readouterr().out

    bigger = json.loads(SPEC_FILE.read_text())
    bigger["cpu"]["logical_cpus"] = 4  # node-1 has 2: one machine type up
    bigger_file = tmp_path / "bigger.json"
    bigger_file.write_text(json.dumps(bigger))
    failed = main(["check", "--spec", str(bigger_file), "--root", str(NODE1)])
    failed_out = capsys.readouterr().out

    assert ok == 0
    assert ok_out.strip().endswith("Result: 0 FAIL, 1 WARN")
    assert failed == 1
    assert failed_out.strip().endswith("Result: 1 FAIL, 1 WARN")
