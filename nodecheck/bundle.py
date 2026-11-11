"""Collect what an investigation needs into one .tar.gz, with one command.

When a check fails, whoever looks next shouldn't have to log in and type a dozen commands
(and maybe miss the moment). Like Red Hat's sosreport, but small: the health check report,
the inventory, the kernel and system error logs, disk, memory, CPU, network and tc state,
plus copies of the spec and baseline that were used.

Rules:
  - read-only, no root, and a fixed list: nothing outside it (no keys, no /etc/shadow)
  - a command that fails or is missing doesn't stop the bundle; MANIFEST.txt records the
    exit code and the size of every file, because "couldn't collect it" is a clue too
"""
from __future__ import annotations

from pathlib import Path

# file in the bundle -> command whose output it holds
COMMANDS = {
    "journalctl-kernel.txt": ["journalctl", "-k", "-b", "--no-pager"],  # kernel messages, this boot
    "journalctl-err.txt": ["journalctl", "-p", "err", "-b", "--no-pager"],  # errors from everything, this boot
    "df.txt": ["df", "-h"],
    "df-i.txt": ["df", "-i"],
    "free.txt": ["free", "-m"],
    "lscpu.txt": ["lscpu"],
    "uname.txt": ["uname", "-a"],
    "uptime.txt": ["uptime"],
    "ip-link.txt": ["ip", "-s", "link"],  # -s: packet, error and drop counters per NIC
    "ip-addr.txt": ["ip", "addr"],
    "ss.txt": ["ss", "-s"],
    "tc-qdisc.txt": ["tc", "qdisc", "show"],  # a forgotten tc rule looks exactly like a slow network
}
# file in the bundle -> file on the machine, relative to the root
FILES = {"os-release": Path("etc") / "os-release"}


def run(command: list[str]) -> tuple[int | None, str]:
    """(exit code, output), or (None, "") if the command doesn't exist."""
    return None, ""


def make(out: Path | str, report: str, inventory: dict, copies: dict[str, Path | str],
         root: Path | str = "/", runner=None) -> Path:
    """Write the bundle to out (a .tar.gz) and return its path.

    report: the health check report; inventory: the hardware inventory;
    copies: extra files to include as they are (e.g. {"spec.json": "config/b2ats_v2.json"});
    root: where FILES are read from; runner(command) -> (exit code, output), default run.
    """
    return Path(out)
