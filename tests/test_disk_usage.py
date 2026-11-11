"""How full the root filesystem is: space and inodes, from df.

Fixtures are node-1's real df output (11/11 22:45):
  tests/fixtures/node-1/commands/df.txt, df-i.txt   before the fault: 4% of space, 2% of inodes
  tests/fixtures/node-1/fault-disk/df.txt           after `fallocate` took 60 GB: 97% (exactly 96.0%)
  tests/fixtures/node-1/fault-disk/df-after.txt     after the file was deleted: 4% again
Running out of inodes was not reproduced on the VM (8.26 million files would take too long),
so that test changes the real df -i line.
"""
import shutil
from pathlib import Path

import pytest

from nodecheck import disk_usage
from nodecheck.__main__ import main
from nodecheck.spec import FAIL, PASS, WARN, load_spec

ROOT = Path(__file__).parent.parent
NODE1 = ROOT / "tests" / "fixtures" / "node-1"
FULL = NODE1 / "fault-disk"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"


@pytest.fixture
def spec():
    return load_spec(SPEC_FILE)


def text(path):
    return Path(path).read_text()


def by_name(results):
    return {r["name"]: r for r in results}


def df_line(total, used, available):
    """A df -P output with these numbers, in the layout of the real one."""
    pct = -(-used * 100 // (used + available))  # df rounds up
    return ("Filesystem        1-blocks        Used  Available Capacity Mounted on\n"
            f"/dev/root      {total} {used} {available}      {pct}% /\n")


# --- parsing real df output ---


def test_df_gives_the_share_of_usable_space_that_is_used():
    full = disk_usage.parse(text(FULL / "df.txt"))

    assert full is not None
    assert full["used"] == 62811885568 and full["available"] == 2617151488
    # used / (used + available), unrounded: df itself prints 97% because it rounds up
    assert full["used_pct"] == pytest.approx(96.0, abs=0.01)
    assert full["mount"] == "/"


def test_df_i_gives_the_share_of_inodes_used():
    inodes = disk_usage.parse(text(NODE1 / "commands" / "df-i.txt"))

    assert inodes is not None
    assert inodes["total"] == 8257536 and inodes["used"] == 91417
    assert inodes["used_pct"] == pytest.approx(1.107, abs=0.001)


def test_output_without_a_filesystem_line_gives_none():
    assert disk_usage.parse("df: /: No such file or directory\n") is None


def test_read_takes_the_captured_files_under_a_fixture_root(tmp_path):
    assert disk_usage.read(NODE1) == (text(NODE1 / "commands" / "df.txt"), text(NODE1 / "commands" / "df-i.txt"))
    assert disk_usage.read(tmp_path) == (None, None)  # nothing captured there


# --- the fault: the disk filled to 96% with fallocate ---


def test_a_disk_filled_to_96_percent_fails(spec):
    space = disk_usage.parse(text(FULL / "df.txt"))
    inodes = disk_usage.parse(text(NODE1 / "commands" / "df-i.txt"))

    results = by_name(disk_usage.check(space, inodes, spec))

    assert results.get("disk_usage", {}).get("status") == FAIL
    assert "96%" in results["disk_usage"]["actual"]
    assert results.get("inode_usage", {}).get("status") == PASS  # one big file uses one inode


def test_the_same_disk_before_and_after_passes(spec):
    inodes = disk_usage.parse(text(NODE1 / "commands" / "df-i.txt"))
    for path in (NODE1 / "commands" / "df.txt", FULL / "df-after.txt"):
        space = disk_usage.parse(text(path))

        results = by_name(disk_usage.check(space, inodes, spec))

        assert results.get("disk_usage", {}).get("status") == PASS, path


def test_between_warn_and_fail_is_warn(spec):
    space = disk_usage.parse(df_line(65445814272, 55_000_000_000, 10_429_037_056))  # 84%

    results = by_name(disk_usage.check(space, None, spec))

    assert results.get("disk_usage", {}).get("status") == WARN


def test_inodes_running_out_fails_while_space_is_free(spec):
    # millions of tiny files: 95% of inodes used, 4% of the space
    real = text(NODE1 / "commands" / "df-i.txt")
    used, free = 7_844_659, 412_877
    many_files = real.replace("8257536 91417 8166119    2%", f"8257536 {used} {free}   95%")
    assert many_files != real

    results = by_name(disk_usage.check(disk_usage.parse(text(NODE1 / "commands" / "df.txt")),
                                       disk_usage.parse(many_files), spec))

    assert results.get("disk_usage", {}).get("status") == PASS
    assert results.get("inode_usage", {}).get("status") == FAIL


def test_unreadable_df_is_warn_not_pass(spec):
    results = by_name(disk_usage.check(None, None, spec))

    assert results.get("disk_usage", {}).get("status") == WARN
    assert results.get("inode_usage", {}).get("status") == WARN


def test_spec_has_usage_thresholds(spec):
    assert spec["disk_usage"] == {"mount": "/", "warn_pct": 80, "fail_pct": 90}


# --- the command line ---


def test_cli_check_fails_a_full_disk_and_exits_1(tmp_path, capsys):
    ok = main(["check", "--spec", str(SPEC_FILE), "--root", str(NODE1)])
    ok_out = capsys.readouterr().out

    full = tmp_path / "node-1"
    shutil.copytree(NODE1, full)
    shutil.copy(FULL / "df.txt", full / "commands" / "df.txt")
    failed = main(["check", "--spec", str(SPEC_FILE), "--root", str(full)])
    failed_out = capsys.readouterr().out

    assert ok == 0
    assert any(l.startswith("  disk_usage") and l.endswith("PASS") for l in ok_out.splitlines())
    assert failed == 1
    assert any(l.startswith("  disk_usage") and l.endswith("FAIL") for l in failed_out.splitlines())
    assert failed_out.strip().endswith("Result: 1 FAIL, 1 WARN")
