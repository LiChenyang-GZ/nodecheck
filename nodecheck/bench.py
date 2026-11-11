"""Benchmarks: run stress-ng, fio, iperf3 and ping, keep the median of several runs as a baseline.

One number per metric, always measured the same way (the commands are fixed below),
so a later run can be compared with the baseline:

  cpu_bogo_ops_per_s      stress-ng, 2 CPU workers for 20 s    (bogo ops/s, real time)
  disk_randread_iops      fio, 4k random reads for 20 s        (IOPS)
  disk_seqread_mb_per_s   fio, 1M sequential reads for 20 s    (MB/s)
  net_gbit_per_s          iperf3 to the peer for 10 s          (Gbit/s, as received)
  net_latency_ms          ping the peer 20 times               (average round trip, ms)

Why the median: in the cloud another VM on the same host can steal CPU, disk or network
for a while ("noisy neighbour"). One slow run moves the mean, not the median.
"""
from __future__ import annotations

import json
import re
import shlex
import statistics
import subprocess
import sys
from pathlib import Path

FIO_FILE = "/tmp/nodecheck-fio.dat"
_FIO = [
    "fio", f"--filename={FIO_FILE}", "--size=256M",
    "--direct=1",  # O_DIRECT: skip the page cache, or we'd be timing RAM
    "--ioengine=libaio", "--runtime=20", "--time_based",
    "--unlink=1",  # delete the test file afterwards
    "--output-format=json",
]

# metric -> (command, unit); "{peer}" is replaced by the other node's IP
COMMANDS = {
    # stress-ng prints its metrics on stderr, so the shell merges it into stdout
    "cpu_bogo_ops_per_s": (["sh", "-c", "stress-ng --cpu 2 --timeout 20s --metrics-brief 2>&1"], "bogo ops/s"),
    "disk_randread_iops": (_FIO[:1] + ["--name=randread", "--rw=randread", "--bs=4k", "--iodepth=32"] + _FIO[1:], "IOPS"),
    "disk_seqread_mb_per_s": (_FIO[:1] + ["--name=seqread", "--rw=read", "--bs=1M", "--iodepth=8"] + _FIO[1:], "MB/s"),
    "net_gbit_per_s": (["iperf3", "-c", "{peer}", "-t", "10", "-J"], "Gbit/s"),
    "net_latency_ms": (["ping", "-c", "20", "-i", "0.2", "{peer}"], "ms"),
}


def run(command: list[str]) -> str | None:
    """Output of the command, or None if it is missing or fails."""
    try:
        done = subprocess.run(command, capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0:
        return None
    return done.stdout


def parse_stress_ng(text: str) -> float | None:
    """bogo ops/s (real time) from `stress-ng --metrics-brief`.

    The metrics line is: stressor, bogo ops, real s, usr s, sys s, ops/s (real time),
    ops/s (usr+sys). Real time is the one that drops when the CPU is throttled.
    """
    numbers = r"\s+([\d.]+)" * 6
    m = re.search(r"metrc:\s*\[\d+\]\s+cpu" + numbers, text)
    return float(m.group(5)) if m else None


def parse_fio(text: str) -> dict | None:
    """{"iops", "mb_per_s"} of the read side of `fio --output-format=json`."""
    job = _json(text)
    try:
        job = job["jobs"][0]
    except (TypeError, KeyError, IndexError):
        return None
    if job.get("error"):
        return None
    read = job["read"]
    return {"iops": read["iops"], "mb_per_s": read["bw_bytes"] / 1e6}  # MB = 10^6 bytes, as disk specs use


def parse_iperf3(text: str) -> float | None:
    """Gbit/s received, from `iperf3 -J` (what actually arrived, not what was sent)."""
    result = _json(text)
    if not result or result.get("error"):
        return None
    try:
        return result["end"]["sum_received"]["bits_per_second"] / 1e9
    except KeyError:
        return None


def parse_ping(text: str) -> float | None:
    """Average round trip in ms, from the `rtt min/avg/max/mdev` line of ping."""
    m = re.search(r"min/avg/max/mdev = [\d.]+/([\d.]+)/", text)
    return float(m.group(1)) if m else None


_PARSERS = {
    "cpu_bogo_ops_per_s": parse_stress_ng,
    "disk_randread_iops": lambda t: (parse_fio(t) or {}).get("iops"),
    "disk_seqread_mb_per_s": lambda t: (parse_fio(t) or {}).get("mb_per_s"),
    "net_gbit_per_s": parse_iperf3,
    "net_latency_ms": parse_ping,
}


def median(values: list[float | None]) -> float | None:
    """Median of the runs that worked (None = a run that failed)."""
    ok = [v for v in values if v is not None]
    return statistics.median(ok) if ok else None


def command_for(metric: str, peer: str) -> list[str]:
    return [peer if part == "{peer}" else part for part in COMMANDS[metric][0]]


def run_benchmarks(peer: str, runs: int, runner=None, metrics: list[str] | None = None) -> dict:
    """{metric: [one value per run]}; runner(command) returns the command's output or None (default: run).

    metrics: only these (default: all of COMMANDS).

    Runs are interleaved (all tools, then all tools again) so a slow minute hits one run
    of each tool rather than every run of one tool.
    """
    runner = runner or run
    metrics = metrics or list(COMMANDS)
    values = {metric: [] for metric in metrics}
    for i in range(runs):
        print(f"run {i + 1}/{runs} ...", file=sys.stderr)
        for metric in metrics:
            out = runner(command_for(metric, peer))
            values[metric].append(None if out is None else _PARSERS[metric](out))
    return values


def make_baseline(node: str, values: dict, spec: dict, measured_at: str, peer: str = "{peer}") -> dict:
    """The baseline document: who, when, how it was measured, every run and the median."""
    return {
        "node": node,
        "model": spec["model"],
        "measured_at": measured_at,
        "conditions": {
            "runs": len(next(iter(values.values()), [])),
            "commands": {m: shlex.join(command_for(m, peer)) for m in COMMANDS},
            "notes": spec["benchmark"]["notes"],
        },
        "metrics": {
            m: {"unit": COMMANDS[m][1], "runs": runs, "median": median(runs)} for m, runs in values.items()
        },
    }


def format_summary(baseline: dict) -> str:
    """One line per metric: median, unit and the runs it came from."""
    lines = []
    for name, m in baseline["metrics"].items():
        med = "failed" if m["median"] is None else f"{m['median']:.2f}"
        runs = ", ".join("failed" if v is None else f"{v:.2f}" for v in m["runs"])
        lines.append(f"{name:<22} {med:>10} {m['unit']:<11} runs: {runs}")
    return "\n".join(lines)


def save(baseline: dict, path: Path | str) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(baseline, indent=2) + "\n")


def _json(text: str):
    """Parse JSON, skipping anything a tool printed before the opening brace."""
    try:
        return json.loads(text[text.index("{"):])
    except ValueError:  # no brace (index) or not valid JSON (JSONDecodeError)
        return None
