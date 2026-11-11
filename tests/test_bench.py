"""Benchmarks and baseline: stress-ng, fio, iperf3, ping; median of several runs.

Parsers are tested on node-1's real output (tests/fixtures/node-1/bench/, captured 11/11).
run_benchmarks is tested with a fake runner that hands back that output, so no VM is needed.
"""
import json
from pathlib import Path

import pytest

from nodecheck import bench
from nodecheck.__main__ import main
from nodecheck.spec import load_spec

ROOT = Path(__file__).parent.parent
BENCH = ROOT / "tests" / "fixtures" / "node-1" / "bench"
SPEC_FILE = ROOT / "config" / "b2ats_v2.json"
PEER = "172.16.0.5"
METRICS = ["cpu_bogo_ops_per_s", "disk_randread_iops", "disk_seqread_mb_per_s", "net_gbit_per_s", "net_latency_ms"]


def fixture(name):
    return (BENCH / name).read_text()


def stress_ng_output(ops_per_s):
    """node-1's real stress-ng output with another bogo ops/s (real time) value."""
    return fixture("stress-ng.txt").replace("2336.67", f"{ops_per_s:.2f}")


def fake_runner(cpu_per_run):
    """Answers each benchmark command with node-1's real output; CPU varies per run."""
    calls = []
    cpu = iter(cpu_per_run)

    def runner(command):
        calls.append(command)
        line = " ".join(command)
        if "stress-ng" in line:
            return stress_ng_output(next(cpu))
        if "--rw=randread" in line:
            return fixture("fio-randread.json")
        if "--rw=read" in line:
            return fixture("fio-seqread.json")
        if "iperf3" in line:
            return fixture("iperf3.json")
        if "ping" in line:
            return fixture("ping.txt")
        return None

    runner.calls = calls
    return runner


# --- parsers, on real output ---


def test_stress_ng_gives_bogo_ops_per_second_in_real_time():
    # the metrics line has two rates; real time is the one that drops if the CPU is throttled
    assert bench.parse_stress_ng(fixture("stress-ng.txt")) == pytest.approx(2336.67)


def test_stress_ng_without_a_metrics_line_gives_none():
    assert bench.parse_stress_ng("stress-ng: error: [123] cpu: cannot allocate\n") is None


def test_fio_gives_iops_and_mb_per_s_from_its_json():
    randread = bench.parse_fio(fixture("fio-randread.json"))
    seqread = bench.parse_fio(fixture("fio-seqread.json"))

    assert randread == {"iops": pytest.approx(9396.71, abs=0.01), "mb_per_s": pytest.approx(38.49, abs=0.01)}
    assert seqread == {"iops": pytest.approx(126.73, abs=0.01), "mb_per_s": pytest.approx(132.89, abs=0.01)}  # bw_bytes / 10^6


def test_fio_output_that_is_not_json_or_has_an_error_gives_none():
    failed = json.loads(fixture("fio-randread.json"))
    failed["jobs"][0]["error"] = 5  # EIO

    assert bench.parse_fio("fio: failed to open file\n") is None
    assert bench.parse_fio(json.dumps(failed)) is None


def test_iperf3_gives_gbit_per_s_received():
    assert bench.parse_iperf3(fixture("iperf3.json")) == pytest.approx(4.956, abs=0.001)


def test_iperf3_that_could_not_connect_gives_none():
    # what iperf3 -J prints when nothing listens on the peer
    text = json.dumps({"start": {}, "intervals": [], "end": {}, "error": "unable to connect to server: Connection refused"})

    assert bench.parse_iperf3(text) is None


def test_ping_gives_average_round_trip_ms():
    assert bench.parse_ping(fixture("ping.txt")) == pytest.approx(0.512)


def test_ping_with_every_packet_lost_gives_none():
    text = "--- 172.16.0.9 ping statistics ---\n20 packets transmitted, 0 received, 100% packet loss, time 3999ms\n"

    assert bench.parse_ping(text) is None


# --- median ---


def test_median_ignores_one_slow_run_where_the_mean_would_not():
    runs = [2336.0, 1100.0, 2300.0]  # the middle run lost half its CPU to a noisy neighbour

    assert bench.median(runs) == 2300.0  # the mean would be 1912


def test_median_skips_failed_runs_and_is_none_when_all_failed():
    assert bench.median([None, 10.0, 12.0]) == 11.0
    assert bench.median([None, None, None]) is None


# --- running ---


def test_run_benchmarks_runs_every_tool_once_per_run_against_the_peer():
    runner = fake_runner([2336.0, 1100.0, 2300.0])

    values = bench.run_benchmarks(PEER, runs=3, runner=runner)

    assert sorted(values) == sorted(METRICS)
    assert values.get("cpu_bogo_ops_per_s") == [2336.0, 1100.0, 2300.0]
    assert values.get("disk_randread_iops") == [pytest.approx(9396.71, abs=0.01)] * 3
    assert len(runner.calls) == 15  # 5 commands x 3 runs
    lines = [" ".join(c) for c in runner.calls]
    assert all("--direct=1" in l for l in lines if "fio" in l)  # bypass the page cache
    assert all(PEER in l for l in lines if "iperf3" in l or "ping" in l)


def test_a_tool_that_fails_gives_none_for_that_run_only():
    runner = fake_runner([2336.0, 2300.0, 2310.0])

    def broken_iperf3(command):
        return None if "iperf3" in " ".join(command) else runner(command)

    values = bench.run_benchmarks(PEER, runs=3, runner=broken_iperf3)

    assert values.get("net_gbit_per_s") == [None, None, None]
    assert values.get("cpu_bogo_ops_per_s") == [2336.0, 2300.0, 2310.0]


# --- the baseline file ---


def test_baseline_keeps_every_run_the_median_and_how_it_was_measured():
    spec = load_spec(SPEC_FILE)
    values = bench.run_benchmarks(PEER, runs=3, runner=fake_runner([2336.0, 1100.0, 2300.0]))

    baseline = bench.make_baseline("node-1", values, spec, measured_at="2026-11-11T06:30:00+00:00")

    assert baseline.get("node") == "node-1"
    assert baseline.get("model") == "Azure Standard_B2ats_v2"
    assert baseline.get("measured_at") == "2026-11-11T06:30:00+00:00"
    assert baseline.get("metrics", {}).get("cpu_bogo_ops_per_s") == {
        "unit": "bogo ops/s",
        "runs": [2336.0, 1100.0, 2300.0],
        "median": 2300.0,
    }
    assert baseline["metrics"]["net_latency_ms"]["unit"] == "ms"
    # the exact commands, so a later run can be checked to be like for like
    assert any("stress-ng" in c for c in baseline["conditions"]["commands"].values())
    # Azure-specific caveats travel with the numbers
    assert "burst" in baseline["conditions"]["notes"]["cpu"]
    assert "host caching" in baseline["conditions"]["notes"]["disk"]


def test_summary_has_one_line_per_metric_with_median_and_unit(tmp_path):
    spec = load_spec(SPEC_FILE)
    values = bench.run_benchmarks(PEER, runs=3, runner=fake_runner([2336.0, 1100.0, 2300.0]))
    baseline = bench.make_baseline("node-1", values, spec, measured_at="2026-11-11T06:30:00+00:00")

    lines = bench.format_summary(baseline).splitlines()

    assert len(lines) == 5
    assert lines[0].split()[:3] == ["cpu_bogo_ops_per_s", "2300.00", "bogo"]


def test_cli_bench_writes_the_baseline_and_exits_1_if_a_metric_has_no_value(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(bench, "run", fake_runner([2336.0, 2300.0, 2310.0]))
    out = tmp_path / "baselines" / "node-1.json"

    ok = main(["bench", "--spec", str(SPEC_FILE), "--peer", PEER, "--out", str(out)])
    printed = capsys.readouterr().out

    assert out.exists()
    saved = json.loads(out.read_text())
    assert ok == 0
    assert saved["metrics"]["cpu_bogo_ops_per_s"]["median"] == 2310.0
    assert "cpu_bogo_ops_per_s" in printed

    # nobody listening on the peer: the network numbers are missing, so the baseline is incomplete
    fine = fake_runner([2336.0, 2300.0, 2310.0])
    monkeypatch.setattr(bench, "run", lambda c: None if "iperf3" in " ".join(c) else fine(c))
    failed = main(["bench", "--spec", str(SPEC_FILE), "--peer", PEER, "--out", str(tmp_path / "b.json")])

    assert failed == 1
