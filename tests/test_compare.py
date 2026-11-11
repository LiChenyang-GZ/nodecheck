"""Compare a fresh run with the baseline: flag metrics that got worse.

The baseline is node-1's real one (baselines/node-1.json, 11/11 18:12: 5.03 Gbit/s, 0.463 ms).
The fault is real too: tests/fixtures/node-1/fault-tbf/ is iperf3 and ping on node-1 while
`tc qdisc add dev eth0 root tbf rate 1gbit burst 256kb latency 50ms` limited its eth0
(11/11 20:44; tc.txt shows the qdisc before and after).
"""
import json
from pathlib import Path

import pytest

from nodecheck import bench, compare
from nodecheck.__main__ import main
from nodecheck.spec import FAIL, PASS, WARN, has_failures, load_spec

ROOT = Path(__file__).parent.parent
FAULT = ROOT / "tests" / "fixtures" / "node-1" / "fault-tbf"
HEALTHY = ROOT / "tests" / "fixtures" / "node-1" / "bench"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"
BASELINE_FILE = ROOT / "baselines" / "node-1.json"
PEER = "172.16.0.5"


@pytest.fixture
def spec():
    return load_spec(SPEC_FILE)


@pytest.fixture
def baseline():
    return json.loads(BASELINE_FILE.read_text())


def network_now(folder):
    """The two network medians as compare gets them, from one captured iperf3 + ping."""
    return {
        "net_gbit_per_s": bench.parse_iperf3((folder / "iperf3.json").read_text()),
        "net_latency_ms": bench.parse_ping((folder / "ping.txt").read_text()),
    }


def by_name(results):
    return {r["name"]: r for r in results}


# --- the fault: bandwidth limited to 1 Gbit/s with tc ---


def test_throttled_network_fails_against_the_baseline(spec, baseline):
    now = network_now(FAULT)
    assert now["net_gbit_per_s"] == pytest.approx(0.953, abs=0.001)  # was 5.03: -81%

    results = by_name(compare.compare(baseline, now, spec))

    assert results["net_gbit_per_s"]["status"] == FAIL
    assert has_failures(list(results.values()))


def test_report_line_shows_the_change_against_the_baseline(spec, baseline):
    result = by_name(compare.compare(baseline, network_now(FAULT), spec))["net_gbit_per_s"]

    assert "0.95" in result["actual"] and "-81%" in result["actual"]
    assert "5.03" in result["expected"]  # what it was compared with


def test_latency_is_shown_but_not_judged_yet(spec, baseline):
    # 1.105 ms against 0.463 (+139%), yet the spec gives latency no thresholds
    result = by_name(compare.compare(baseline, network_now(FAULT), spec))["net_latency_ms"]

    assert result["status"] == compare.INFO
    assert "1.10" in result["actual"]


# --- normal variation must not be flagged ---


def test_a_healthy_run_passes(spec, baseline):
    now = network_now(HEALTHY)  # node-1 at 17:36, before the baseline: 4.96 Gbit/s, -1.5%

    results = compare.compare(baseline, now, spec)

    assert by_name(results)["net_gbit_per_s"]["status"] == PASS
    assert not has_failures(results)


def test_better_than_the_baseline_is_not_flagged(spec, baseline):
    # 5.73 Gbit/s measured at 20:35 with no fault: +14% is luck, not a fault
    results = by_name(compare.compare(baseline, {"net_gbit_per_s": 5.73}, spec))

    assert results["net_gbit_per_s"]["status"] == PASS


# --- thresholds ---


def test_worse_than_warn_drop_but_not_fail_drop_is_warn(spec, baseline):
    now = {"net_gbit_per_s": 5.03 * 0.80}  # -20%: past 15%, not yet 25%

    assert by_name(compare.compare(baseline, now, spec))["net_gbit_per_s"]["status"] == WARN


def test_every_judged_metric_uses_its_own_thresholds(spec, baseline):
    spec["benchmark"]["compare"]["cpu_bogo_ops_per_s"] = {"better": "higher", "warn_drop": 0.5, "fail_drop": 0.9}
    now = {"cpu_bogo_ops_per_s": 2300 * 0.7, "disk_randread_iops": 9391 * 0.7}  # both -30%

    results = by_name(compare.compare(baseline, now, spec))

    assert results["cpu_bogo_ops_per_s"]["status"] == PASS  # its own, looser thresholds
    assert results["disk_randread_iops"]["status"] == FAIL


def test_for_lower_is_better_a_rise_is_worse(spec, baseline):
    # the structure for latency, once it gets thresholds
    spec["benchmark"]["compare"]["net_latency_ms"] = {"better": "lower", "warn_drop": 0.15, "fail_drop": 0.25}

    worse = by_name(compare.compare(baseline, {"net_latency_ms": 0.463 * 1.5}, spec))
    better = by_name(compare.compare(baseline, {"net_latency_ms": 0.463 * 0.5}, spec))

    assert worse["net_latency_ms"]["status"] == FAIL
    assert better["net_latency_ms"]["status"] == PASS


def test_a_metric_with_no_value_this_time_is_warn(spec, baseline):
    # e.g. iperf3 could not reach the peer: not seen is not the same as fine
    result = by_name(compare.compare(baseline, {"net_gbit_per_s": None}, spec))["net_gbit_per_s"]

    assert result["status"] == WARN


def test_only_the_metrics_run_again_are_compared(spec, baseline):
    results = compare.compare(baseline, network_now(FAULT), spec)

    assert [r["name"] for r in results] == ["net_gbit_per_s", "net_latency_ms"]


def test_spec_says_which_way_is_better_for_every_metric(spec):
    rules = spec["benchmark"]["compare"]

    assert sorted(rules) == sorted(bench.COMMANDS)
    assert rules["net_gbit_per_s"]["better"] == "higher"
    assert rules["net_latency_ms"]["better"] == "lower"


# --- running it ---


def fault_runner(command):
    """Answers iperf3 and ping with the output captured under the tc limit."""
    line = " ".join(command)
    if "iperf3" in line:
        return (FAULT / "iperf3.json").read_text()
    if "ping" in line:
        return (FAULT / "ping.txt").read_text()
    return None


def test_run_benchmarks_can_run_only_the_network_metrics():
    calls = []

    def runner(command):
        calls.append(command)
        return fault_runner(command)

    values = bench.run_benchmarks(PEER, runs=3, runner=runner, metrics=compare.NETWORK)

    assert sorted(values) == sorted(compare.NETWORK)
    assert len(calls) == 6  # iperf3 + ping, 3 runs; no stress-ng, no fio


def test_cli_compare_reports_the_throttled_network_and_exits_1(monkeypatch, capsys):
    monkeypatch.setattr(bench, "run", fault_runner)

    code = main(["compare", "--spec", str(SPEC_FILE), "--peer", PEER,
                 "--baseline", str(BASELINE_FILE), "--only", "network"])
    printed = capsys.readouterr().out

    assert code == 1  # a script looping over nodes can pick this one out
    assert "net_gbit_per_s" in printed and "FAIL" in printed
    assert "node-1" in printed  # whose baseline it was compared with
