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

import json
import subprocess
import tarfile
import tempfile
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


def run(command: list[str]) -> tuple[int | str | None, str]:
    """(exit code, output with stderr), or (None, "") if the command doesn't exist."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=60)
    except OSError:  # not installed
        return None, ""
    except subprocess.TimeoutExpired:
        return "timeout", ""
    return done.returncode, done.stdout + done.stderr


def make(out: Path | str, report: str, inventory: dict, copies: dict[str, Path | str],
         root: Path | str = "/", runner=None) -> Path:
    """Write the bundle to out (a .tar.gz) and return its path.

    report: the health check report; inventory: the hardware inventory;
    copies: extra files to include as they are (e.g. {"spec.json": "config/b2ats_v2.json"});
    root: where FILES are read from; runner(command) -> (exit code, output), default run.
    The archive unpacks into one folder named like the file, e.g. nodecheck-node-1-20261111T1320Z/.
    """
    runner = runner or run
    out = Path(out)
    folder = out.name.removesuffix(".tar.gz")
    rows = []  # (file, exit, command) for MANIFEST.txt; sizes are added when written

    entries = {"check.txt": report, "inventory.json": json.dumps(inventory, indent=2) + "\n"}
    rows += [("check.txt", 0, "nodecheck check"), ("inventory.json", 0, "nodecheck inventory")]
    for name, command in COMMANDS.items():
        code, output = runner(command)
        entries[name] = output
        rows.append((name, code, " ".join(command)))
    for name, relative in FILES.items():
        entries[name], code = _read(Path(root) / relative)
        rows.append((name, code, f"copy of /{relative.as_posix()}"))
    for name, path in copies.items():
        entries[name], code = _read(Path(path))
        rows.append((name, code, f"copy of {path}"))

    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / folder
        base.mkdir()
        lines = ["file\texit\tbytes\tcommand"]
        for name, code, command in rows:
            data = entries[name].encode()
            (base / name).write_bytes(data)
            lines.append(f"{name}\t{'not found' if code is None else code}\t{len(data)}\t{command}")
        (base / "MANIFEST.txt").write_bytes(("\n".join(lines) + "\n").encode())
        out.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(out, "w:gz") as tar:
            tar.add(base, arcname=folder)
    return out


def _read(path: Path) -> tuple[str, int | None]:
    """(text, 0), or ("", None) if the file can't be read."""
    try:
        return path.read_text(encoding="utf-8", errors="replace"), 0
    except OSError:
        return "", None
