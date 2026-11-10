"""Command line: python3 -m nodecheck <command>"""
from __future__ import annotations

import sys


def main(argv: list[str] | None = None) -> int:
    # Not implemented yet (step 1, red).
    print("nodecheck: not implemented", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
