#!/usr/bin/env python3
"""
_template-both-v1 - fixer template, scope = "both".

A fixer is self-contained: it detects the problem AND resolves it in one
pass. The runner invokes this directly whenever it exists and --fix was
passed, and never runs the checker first - so the detection logic has to
live here too, not just the repair.

It also repeats the checker's argument validation. That duplication is
deliberate: the two scripts are separately invocable, and a fixer that
trusted its caller would be a fixer that writes to the wrong place.

Delete this file if the rule shouldn't fix anything. Its presence on disk
IS how the runner knows a rule is fixable, and check-only is a permanent,
normal design rather than a stub.

Protocol reference: doc/RULES.md, "The fixer script".
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="dual-scope fixer template")
    parser.add_argument("--path")
    parser.add_argument("--paths", action="append", default=[])
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    if args.path and args.paths:
        print("error: pass --path or --paths, not both", file=sys.stderr)
        return 1
    if not args.path and not args.paths:
        print("error: one of --path or --paths is required", file=sys.stderr)
        return 1
    if args.paths and len(args.paths) < 2:
        print("error: --paths requires 2 or more locations", file=sys.stderr)
        return 1

    roots = [Path(args.path)] if args.path else [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1

    recursive = params.get("recursive", True)

    found: list[str] = []
    resolved: list[str] = []
    for root in roots:
        entries = root.rglob("*") if recursive else root.iterdir()
        # --- detect and resolve here ---------------------------------
        # Writable here: root and this invocation's own target(s).
        _ = list(entries)

    if not found:
        verdict = {"status": "ok"}
    elif len(resolved) == len(found):
        verdict = {"status": "fixed", "message": f"resolved {len(resolved)}"}
    elif resolved:
        verdict = {"status": "violation",
                   "message": f"resolved {len(resolved)} of {len(found)}"}
    else:
        verdict = {"status": "unfixable", "message": f"{len(found)} problem(s), none auto-resolvable"}

    print(json.dumps(verdict))
    return 0


if __name__ == "__main__":
    sys.exit(main())
