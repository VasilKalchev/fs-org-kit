#!/usr/bin/env python3
"""
_template-single-v1 - fixer template, single scope.

A fixer is self-contained: it detects the problem AND resolves it in one
pass. The runner invokes this directly whenever it exists and --fix was
passed, and never runs the checker first - so the detection logic has to
live here too, not just the repair.

Delete this file if the rule shouldn't fix anything. Its presence on disk
IS how the runner knows a rule is fixable, and check-only is a permanent,
normal design rather than a stub: renaming, moving, or deleting a user's
files is often a decision only they should make.

Protocol reference: doc/RULES.md, "The fixer script".
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="single-scope fixer template")
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    entries = root.rglob("*") if params.get("recursive", True) else root.iterdir()

    found: list[str] = []
    resolved: list[str] = []
    for entry in entries:
        # --- detect and resolve here ---------------------------------
        # Writable here: root and this invocation's own target. Moving or
        # removing a folder is allowed, and the runner will report the
        # invocations already planned against the old location as
        # `skipped` rather than running them.
        _ = entry

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
