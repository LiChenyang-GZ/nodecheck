"""Command line: python3 -m nodecheck <command>

    python3 -m nodecheck inventory              # this machine
    python3 -m nodecheck inventory --root DIR   # a captured fixture directory
    python3 -m nodecheck check --spec config/b2ats_v2.json [--root DIR]
"""
from __future__ import annotations

import argparse
import json
import sys

from nodecheck.inventory import collect
from nodecheck.spec import check, format_report, load_spec


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nodecheck", description="Validate a Linux node before handover.")
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="print the hardware inventory as JSON")
    inventory.add_argument("--root", default="/", help="filesystem root to read from (default: /)")

    check_cmd = commands.add_parser("check", help="compare the inventory with a machine-type spec")
    check_cmd.add_argument("--spec", required=True, help="spec file, e.g. config/b2ats_v2.json")
    check_cmd.add_argument("--root", default="/", help="filesystem root to read from (default: /)")

    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(collect(args.root), indent=2))
    elif args.command == "check":
        spec = load_spec(args.spec)
        results = check(collect(args.root), spec)
        print(format_report(results, spec))
        # Not implemented yet: the exit code doesn't reflect FAILs.
    return 0


if __name__ == "__main__":
    sys.exit(main())
