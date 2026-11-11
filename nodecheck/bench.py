"""Benchmarks: run stress-ng, fio, iperf3 and ping, keep the median of several runs as a baseline.

One number per metric, always measured the same way (the commands are fixed below),
so a later run can be compared with the baseline:

  cpu_bogo_ops_per_s      stress-ng, 2 CPU workers for 20 s    (bogo ops/s, real time)
  disk_randread_iops      fio, 4k random reads for 20 s        (IOPS)
  disk_seqread_mb_per_s   fio, 1M sequential reads for 20 s    (MB/s)
  net_gbit_per_s          iperf3 to the peer for 10 s          (Gbit/s, as received)
  net_latency_ms          ping the peer 20 times               (average round trip, ms)
"""
from __future__ import annotations

from pathlib import Path


def run(command: list[str]) -> str | None:
    """Output of the command, or None if it is missing or fails."""
    # Not implemented yet.
    return None


def parse_stress_ng(text: str) -> float | None:
    """bogo ops/s (real time) from `stress-ng --metrics-brief`."""
    # Not implemented yet.
    return None


def parse_fio(text: str) -> dict | None:
    """{"iops", "mb_per_s"} of the read side of `fio --output-format=json`."""
    # Not implemented yet.
    return None


def parse_iperf3(text: str) -> float | None:
    """Gbit/s received, from `iperf3 -J`."""
    # Not implemented yet.
    return None


def parse_ping(text: str) -> float | None:
    """Average round trip in ms, from the `rtt min/avg/max/mdev` line of ping."""
    # Not implemented yet.
    return None


def median(values: list[float | None]) -> float | None:
    """Median of the runs that worked (None = a run that failed)."""
    # Not implemented yet.
    return None


def run_benchmarks(peer: str, runs: int, runner=None) -> dict:
    """{metric: [one value per run]}; runner(command) returns the command's output or None (default: run)."""
    # Not implemented yet.
    return {}


def make_baseline(node: str, values: dict, spec: dict, measured_at: str) -> dict:
    """The baseline document: who, when, how it was measured, every run and the median."""
    # Not implemented yet.
    return {}


def format_summary(baseline: dict) -> str:
    """One line per metric: median, unit and the runs it came from."""
    # Not implemented yet.
    return ""


def save(baseline: dict, path: Path | str) -> None:
    # Not implemented yet.
    pass
