"""Command line: python3 -m nodecheck <command>

    python3 -m nodecheck inventory              # this machine
    python3 -m nodecheck inventory --root DIR   # a captured fixture directory
    python3 -m nodecheck check --spec config/b2ats_v2.json [--root DIR]

`check` compares the inventory with the spec, looks for kernel errors since this boot and checks
how full the root filesystem is. With --root DIR, the kernel log and df output are read from
DIR/commands/ (journalctl-k.jsonl, df.txt, df-i.txt) instead.

    python3 -m nodecheck bench --spec config/b2ats_v2.json --peer 172.16.0.5 --out baselines/node-1.json
    python3 -m nodecheck compare --spec config/b2ats_v2.json --peer 172.16.0.5 --baseline baselines/node-1.json [--only network]

`compare` runs the benchmarks again and flags metrics that got worse than the baseline.
"""
from __future__ import annotations

import argparse
import json
import socket
import sys
from datetime import datetime, timezone
from pathlib import Path

from nodecheck import bench, compare, disk_usage, kernel_log
from nodecheck.inventory import collect
from nodecheck.spec import check, format_report, has_failures, load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nodecheck", description="Validate a Linux node before handover.")
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="print the hardware inventory as JSON")
    inventory.add_argument("--root", default="/", help="filesystem root to read from (default: /)")

    check_cmd = commands.add_parser("check", help="compare with a machine-type spec and check the kernel log")
    check_cmd.add_argument("--spec", required=True, help="spec file, e.g. config/b2ats_v2.json")
    check_cmd.add_argument("--root", default="/", help="filesystem root to read from (default: /)")

    bench_cmd = commands.add_parser("bench", help="run the benchmarks and save the median of each as a baseline")
    bench_cmd.add_argument("--spec", required=True, help="spec file, e.g. config/b2ats_v2.json")
    bench_cmd.add_argument("--peer", required=True, help="private IP of the other node (runs `iperf3 -s`)")
    bench_cmd.add_argument("--out", required=True, help="where to write the baseline JSON")
    bench_cmd.add_argument("--node", default=socket.gethostname(), help="node name (default: this hostname)")

    compare_cmd = commands.add_parser("compare", help="run the benchmarks again and compare with a baseline")
    compare_cmd.add_argument("--spec", required=True, help="spec file, e.g. config/b2ats_v2.json")
    compare_cmd.add_argument("--peer", required=True, help="private IP of the other node (runs `iperf3 -s`)")
    compare_cmd.add_argument("--baseline", required=True, help="this node's baseline, e.g. baselines/node-1.json")
    compare_cmd.add_argument("--only", choices=["network"], help="re-run only iperf3 and ping (about 45 s)")

    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(collect(args.root), indent=2))
    elif args.command == "check":
        spec = load_spec(args.spec)
        results = check(collect(args.root), spec)
        log = kernel_log.read(args.root)
        results.append(kernel_log.check(None if log is None else kernel_log.parse(log), spec))
        space, inodes = (None if t is None else disk_usage.parse(t) for t in disk_usage.read(args.root, spec["disk_usage"]["mount"]))
        results.extend(disk_usage.check(space, inodes, spec))
        print(format_report(results, spec))
        # 1 when anything FAILs, so a script looping over many nodes can pick out the bad ones
        return 1 if has_failures(results) else 0
    elif args.command == "bench":
        spec = load_spec(args.spec)
        values = bench.run_benchmarks(args.peer, spec["benchmark"]["runs"])
        measured_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        baseline = bench.make_baseline(args.node, values, spec, measured_at, peer=args.peer)
        bench.save(baseline, args.out)
        print(f"Baseline for {args.node} ({spec['model']}), median of {spec['benchmark']['runs']} runs")
        print(bench.format_summary(baseline))
        print(f"Saved to {args.out}")
        # 1 when a metric has no value at all (e.g. iperf3 server not running): the baseline is incomplete
        return 1 if any(m["median"] is None for m in baseline["metrics"].values()) else 0
    elif args.command == "compare":
        spec = load_spec(args.spec)
        baseline = json.loads(Path(args.baseline).read_text())
        runs = spec["benchmark"]["runs"]
        metrics = compare.NETWORK if args.only == "network" else None
        values = bench.run_benchmarks(args.peer, runs, metrics=metrics)
        current = {metric: bench.median(v) for metric, v in values.items()}
        results = compare.compare(baseline, current, spec)
        print(f"Baseline: {baseline['node']}, measured {baseline['measured_at']}; now: median of {runs} runs")
        print(format_report(results, spec))
        return 1 if has_failures(results) else 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
