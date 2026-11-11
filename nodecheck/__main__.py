"""Command line: python3 -m nodecheck <command>

    python3 -m nodecheck inventory              # this machine
    python3 -m nodecheck inventory --root DIR   # a captured fixture directory
    python3 -m nodecheck check --spec config/b2ats_v2.json [--root DIR]

`check` compares the inventory with the spec and looks for kernel errors since this boot.
With --root DIR, the kernel log is read from DIR/commands/journalctl-k.jsonl instead.

    python3 -m nodecheck bench --spec config/b2ats_v2.json --peer 172.16.0.5 --out baselines/node-1.json
"""
from __future__ import annotations

import argparse
import json
import sys

from nodecheck import kernel_log
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

    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(collect(args.root), indent=2))
    elif args.command == "check":
        spec = load_spec(args.spec)
        results = check(collect(args.root), spec)
        log = kernel_log.read(args.root)
        results.append(kernel_log.check(None if log is None else kernel_log.parse(log), spec))
        print(format_report(results, spec))
        # 1 when anything FAILs, so a script looping over many nodes can pick out the bad ones
        return 1 if has_failures(results) else 0
    elif args.command == "bench":
        pass  # Not implemented yet.
    return 0


if __name__ == "__main__":
    sys.exit(main())
