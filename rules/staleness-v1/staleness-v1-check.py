#!/usr/bin/env python3
"""
staleness-v1-check.py - flags direct children of --path that are too
old (mode="stale") or unexpectedly recent (mode="active"). See
staleness-v1.toml for the full param documentation.

Protocol (protocol_version 1.0, single scope):
    python staleness-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import sys
from pathlib import Path

from _shared import find_violations, format_age, parse_duration


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: staleness-v1-check.py has no fixing capability - invoke staleness-v1-fix.py instead", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    mode = params.get("mode")
    if mode not in ("stale", "active"):
        print(f"error: mode must be 'stale' or 'active', got {mode!r}", file=sys.stderr)
        return 1

    threshold = params.get("threshold")
    if not threshold:
        print("error: threshold is required", file=sys.stderr)
        return 1
    try:
        threshold_seconds = parse_duration(threshold)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    basis = params.get("basis", "mtime")
    if basis not in ("mtime", "atime"):
        print(f"error: basis must be 'mtime' or 'atime', got {basis!r}", file=sys.stderr)
        return 1

    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    violations = find_violations(root, mode, threshold_seconds, basis, exclude_globs)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    verb = "hasn't been touched in" if mode == "stale" else "was touched only"
    parts = [f"{item.name} ({verb} {format_age(age)})" for item, age in shown]
    message = f"{len(violations)} item(s) violating '{mode}' threshold of {threshold}: {', '.join(parts)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
