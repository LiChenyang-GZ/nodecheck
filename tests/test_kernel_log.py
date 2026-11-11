"""Kernel log check: errors in this boot's journal (journalctl -k -b -p warning -o json).

The base log is node-1's real one (tests/fixtures/node-1/commands/journalctl-k.jsonl):
9 warnings and 1 err ("/dev/sr0: Can't lookup blockdev"), all harmless on an Azure VM.
Faults are made by appending one line built from a real line, with a new MESSAGE and PRIORITY.
"""
import copy
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from nodecheck import kernel_log
from nodecheck.__main__ import main
from nodecheck.spec import load_spec

ROOT = Path(__file__).parent.parent
NODE1 = ROOT / "tests" / "fixtures" / "node-1"
NODE1_LOG = NODE1 / "commands" / "journalctl-k.jsonl"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"
SR0 = "/dev/sr0: Can't lookup blockdev"


@pytest.fixture
def spec():
    return load_spec(SPEC_FILE)


@pytest.fixture
def text():
    return NODE1_LOG.read_text()


def line_like_the_real_ones(message, priority):
    """A journal line copied from node-1's real sr0 line, with another message and priority."""
    real = next(json.loads(l) for l in NODE1_LOG.read_text().splitlines() if SR0 in l)
    real["MESSAGE"] = message
    real["PRIORITY"] = str(priority)  # journald writes numbers as strings
    return json.dumps(real)


def test_parse_reads_priority_and_message_from_real_journal_json(text):
    entries = kernel_log.parse(text)

    assert len(entries) == 10
    assert [e["priority"] for e in entries].count(4) == 9
    assert [e["message"] for e in entries if e["priority"] == 3] == [SR0]
    assert entries[0]["message"] == "Speculative Return Stack Overflow: IBPB-extending microcode not applied!"


def test_parse_decodes_byte_array_messages_and_skips_lines_that_are_not_json():
    # journald writes MESSAGE as a list of byte values when it isn't clean UTF-8
    raw = json.dumps({"PRIORITY": "3", "MESSAGE": list(b"bad \xff byte")})
    text = "not json\n\n" + raw + "\n"

    entries = kernel_log.parse(text)

    assert len(entries) == 1
    assert entries[0]["priority"] == 3
    assert entries[0]["message"].startswith("bad ") and entries[0]["message"].endswith(" byte")


def test_boot_time_is_realtime_minus_monotonic(text):
    # every entry carries wall-clock time and time since boot; uptime -s on node-1 said 05:39:07
    started = kernel_log.boot_time(kernel_log.parse(text))

    assert started == datetime(2026, 11, 11, 5, 39, 7, 460159, tzinfo=timezone.utc)


def test_real_node1_log_passes_because_the_sr0_error_is_on_the_ignore_list(spec, text):
    result = kernel_log.check(kernel_log.parse(text), spec)

    assert result["name"] == "kernel_log"
    assert result["status"] == "PASS"
    assert "0 errors" in result["actual"]
    assert "1 ignored" in result["actual"]
    assert "9 warnings" in result["actual"]


def test_without_the_ignore_list_the_sr0_error_fails(spec, text):
    spec = copy.deepcopy(spec)
    spec["kernel_log"]["ignore"] = []

    result = kernel_log.check(kernel_log.parse(text), spec)

    assert result["status"] == "FAIL"
    assert SR0 in result["details"]


@pytest.mark.parametrize(
    "message, priority, expected",
    [
        ("Out of memory: Killed process 1234 (python3) total-vm:812345kB", 3, "FAIL"),
        ("I/O error, dev sda, sector 2048 op 0x0:(READ) flags 0x0 phys_seg 1 prio class 2", 3, "FAIL"),
        ("mce: [Hardware Error]: CPU 0: Machine Check: 0 Bank 4: b200000000070005", 0, "FAIL"),
        ("Kernel panic - not syncing: Fatal exception", 0, "FAIL"),
        ("hv_netvsc: some new warning", 4, "PASS"),
        ("python3[1234]: segfault at 0 ip 0000 sp 0000 error 4", 6, "PASS"),
    ],
    ids=["oom-err", "disk-io-err", "mce-emerg", "panic-emerg", "warning", "segfault-info"],
)
def test_priority_0_to_3_fails_and_lower_priorities_do_not(spec, text, message, priority, expected):
    text += line_like_the_real_ones(message, priority) + "\n"

    result = kernel_log.check(kernel_log.parse(text), spec)

    assert result["status"] == expected
    if expected == "FAIL":
        assert result["details"] == [message]


def test_unreadable_log_is_warn_not_pass(spec):
    # not seeing errors is not the same as there being none
    result = kernel_log.check(None, spec)

    assert result["status"] == "WARN"
    assert result["actual"] == "unreadable"


def test_run_gives_output_or_none_when_the_command_is_missing_or_fails():
    ok = kernel_log.run([sys.executable, "-c", "print('hello')"])
    missing = kernel_log.run(["no-such-command-nodecheck"])
    failed = kernel_log.run([sys.executable, "-c", "import sys; sys.exit(1)"])

    assert ok.strip() == "hello"
    assert missing is None
    assert failed is None


def test_read_takes_the_captured_file_under_a_fixture_root(tmp_path, text):
    assert kernel_log.read(NODE1) == text
    assert kernel_log.read(tmp_path) is None  # nothing captured there


def test_cli_check_adds_a_kernel_log_line_and_exits_1_on_an_injected_error(tmp_path, capsys):
    ok = main(["check", "--spec", str(SPEC_FILE), "--root", str(NODE1)])
    ok_out = capsys.readouterr().out

    broken = tmp_path / "node-1"
    shutil.copytree(NODE1, broken)
    oom = "Out of memory: Killed process 1234 (python3) total-vm:812345kB"
    with open(broken / "commands" / "journalctl-k.jsonl", "a") as f:
        f.write(line_like_the_real_ones(oom, 3) + "\n")
    failed = main(["check", "--spec", str(SPEC_FILE), "--root", str(broken)])
    failed_out = capsys.readouterr().out

    assert ok == 0
    assert any(l.startswith("  kernel_log") and l.endswith("PASS") for l in ok_out.splitlines())
    assert ok_out.strip().endswith("Result: 0 FAIL, 1 WARN")
    assert failed == 1
    assert any(l.startswith("  kernel_log") and l.endswith("FAIL") for l in failed_out.splitlines())
    assert "    " + oom in failed_out.splitlines()  # the error itself, indented under its check
    assert failed_out.strip().endswith("Result: 1 FAIL, 1 WARN")
