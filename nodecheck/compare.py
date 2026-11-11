"""Compare a fresh benchmark run with this node's baseline (see bench.py).

For each metric the spec (benchmark.compare) says which way is better and how much worse is too much,
either as a share of the baseline or in the metric's own unit:
  warn_drop / fail_drop   e.g. 0.15 / 0.25: 15% / 25% worse (bandwidth, CPU, disk)
  warn_by / fail_by       e.g. 1.0 / 1.5: 1 / 1.5 ms worse (latency: a share of 0.46 ms is mostly noise)

  FAIL  worse than the baseline by the fail threshold or more
  WARN  worse by the warn threshold or more, or no value this time
  PASS  less worse than that, or better than the baseline
  INFO  shown but not judged: the spec gives this metric no thresholds
"""
from __future__ import annotations

from nodecheck.spec import FAIL, PASS, WARN

INFO = "INFO"

# what `compare --only network` re-runs: about 45 s instead of 4 minutes
NETWORK = ["net_gbit_per_s", "net_latency_ms"]


def compare(baseline: dict, current: dict, spec: dict) -> list[dict]:
    """One result per metric in `current` ({metric: median, or None if the tool failed}).

    Each result is {"name", "status", "actual", "expected"}, like the spec checks.
    Only the metrics that were run again are compared (e.g. just the network ones).
    """
    rules = spec["benchmark"]["compare"]
    return [
        _compare_one(metric, value, baseline["metrics"].get(metric), rules.get(metric, {}))
        for metric, value in current.items()
    ]


def _compare_one(metric: str, value: float | None, base: dict | None, rule: dict) -> dict:
    if base is None or not base.get("median"):
        return _result(metric, WARN, _number(value, ""), "no baseline value to compare with")
    was, unit = base["median"], base["unit"]
    lower_is_better = rule.get("better") == "lower"
    sign = "+" if lower_is_better else "-"
    in_units = "fail_by" in rule  # thresholds in the metric's unit rather than a share of the baseline
    expected = f"{was:.2f} {unit}"
    if in_units:
        expected += f", WARN {sign}{rule['warn_by']} {unit}, FAIL {sign}{rule['fail_by']} {unit}"
    elif "fail_drop" in rule:
        expected += f", WARN {sign}{rule['warn_drop']:.0%}, FAIL {sign}{rule['fail_drop']:.0%}"

    if value is None:
        # the tool failed this time (e.g. iperf3 could not reach the peer): not seen is not fine
        return _result(metric, WARN, "no value this time", expected)

    if in_units:
        change = value - was  # +2.36 = 2.36 ms more than the baseline
        actual = f"{value:.2f} {unit} ({change:+.2f} {unit})"
        warn, fail = rule["warn_by"], rule["fail_by"]
    else:
        change = value / was - 1  # +0.14 = 14% higher than the baseline
        actual = f"{value:.2f} {unit} ({change:+.0%})"
        if "fail_drop" not in rule:
            return _result(metric, INFO, actual, expected + ", not judged")
        warn, fail = rule["warn_drop"], rule["fail_drop"]

    # how much worse, in the same terms as the thresholds; negative = better, which is never flagged
    worse = change if lower_is_better else -change
    if worse >= fail:
        status = FAIL
    elif worse >= warn:
        status = WARN
    else:
        status = PASS
    return _result(metric, status, actual, expected)


def _number(value: float | None, unit: str) -> str:
    return "no value this time" if value is None else f"{value:.2f} {unit}".strip()


def _result(name: str, status: str, actual: str, expected: str) -> dict:
    return {"name": name, "status": status, "actual": actual, "expected": expected}
