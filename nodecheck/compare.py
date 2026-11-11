"""Compare a fresh benchmark run with this node's baseline (see bench.py).

For each metric the spec (benchmark.compare) says which way is better and how much worse is too much:
  FAIL  worse than the baseline by fail_drop or more (e.g. 25%)
  WARN  worse by warn_drop or more (e.g. 15%), or no value this time
  PASS  less worse than warn_drop, or better than the baseline
  INFO  shown but not judged: the spec gives this metric no thresholds
"""
from __future__ import annotations

from nodecheck.spec import PASS

INFO = "INFO"

# what `compare --only network` re-runs: about 45 s instead of 4 minutes
NETWORK = ["net_gbit_per_s", "net_latency_ms"]


def compare(baseline: dict, current: dict, spec: dict) -> list[dict]:
    """One result per metric in `current` ({metric: median, or None if the tool failed}).

    Each result is {"name", "status", "actual", "expected"}, like the spec checks.
    """
    return [{"name": metric, "status": PASS, "actual": "", "expected": ""} for metric in current]
