"""Command line: python3 -m nodecheck <command>

    python3 -m nodecheck inventory              # this machine
    python3 -m nodecheck inventory --root DIR   # a captured fixture directory
"""
from __future__ import annotations

import argparse
import json
import sys

from nodecheck.inventory import collect


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nodecheck", description="Validate a Linux node before handover.")
    commands = parser.add_subparsers(dest="command", required=True)

    inventory = commands.add_parser("inventory", help="print the hardware inventory as JSON")
    inventory.add_argument("--root", default="/", help="filesystem root to read from (default: /)")

    args = parser.parse_args(argv)
    if args.command == "inventory":
        print(json.dumps(collect(args.root), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
