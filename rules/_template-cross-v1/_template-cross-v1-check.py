#!/usr/bin/env python3
"""
_template-cross-v1 - checker template, cross scope.

Runs as a plain subprocess, never imported. Prints exactly one JSON line
on stdout - a stray print corrupts the verdict. Exit 0 means "I ran, the
verdict is on stdout"; nonzero means this script is broken (bad params, a
path that isn't there), with the reason on stderr. Finding a violation is
never nonzero.

A cross-scope script receives every location of its set in one
invocation, so the whole point is comparing them - if the check makes
sense against one location at a time, it wants scope = "single" instead.

Protocol reference: doc/RULES.md, "The checker script".
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="cross-scope rule template")
    parser.add_argument("--paths", action="append", default=[])
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        # The runner never does this - it invokes -fix.py directly when one
        # exists. Rejecting it anyway turns a runner bug into a loud failure
        # instead of a silently wrong result.
        print("error: _template-cross-v1: --fix belongs to _template-cross-v1-fix.py",
              file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    if len(args.paths) < 2:
        print("error: --paths requires 2 or more locations", file=sys.stderr)
        return 1

    roots = [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1

    recursive = params.get("recursive", True)

    violations: list[str] = []
    for root in roots:
        entries = root.rglob("*") if recursive else root.iterdir()
        # --- collect whatever the comparison needs from each location --
        # Read only. A checker is given no writable location beyond its
        # cache and the system temp directory, so a stray write fails the
        # invocation rather than quietly happening.
        _ = list(entries)

    # --- compare the locations against each other here ----------------

    if violations:
        print(json.dumps({
            "status": "violation",
            "message": f"{len(violations)} problem(s): " + ", ".join(sorted(violations)[:5]),
        }))
    else:
        print(json.dumps({"status": "ok"}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
