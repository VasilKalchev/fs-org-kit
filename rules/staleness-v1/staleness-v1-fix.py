#!/usr/bin/env python3
"""
staleness-v1-fix.py - moves violating direct children to (mode="stale")
or out of (mode="active") the archive sibling. See staleness-v1.toml
for the full param documentation.

Protocol (protocol_version 1.0, single scope, fix mode):
    python staleness-v1-fix.py --path <dir> --params '<json>' --fix

stdout: exactly one JSON line -
    {"status": "ok"}
    {"status": "fixed", "message": "..."}       - every violation resolved
    {"status": "violation", "message": "..."}   - some resolved, some not
    {"status": "unfixable", "message": "..."}   - destination doesn't exist
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import os
import sys
from pathlib import Path

from _shared import find_violations, move_item, parse_duration, resolve_destination


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if not args.fix:
        print("error: staleness-v1-fix.py should only ever be invoked with --fix", file=sys.stderr)
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
    destination_param = params.get("destination")
    if not destination_param:
        print("error: destination is required", file=sys.stderr)
        return 1

    create_destination = params.get("create_destination", False)
    if not isinstance(create_destination, bool):
        print("error: create_destination must be a boolean", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    violations = find_violations(root, mode, threshold_seconds, basis, exclude_globs)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    destination = resolve_destination(destination_param, root)

    if not destination.is_dir():
        if not create_destination:
            print(json.dumps({
                "status": "unfixable",
                "message": f"{len(violations)} item(s) violate the standard, but the destination {destination} "
                           f"doesn't exist and create_destination is false",
            }))
            return 0
        try:
            destination.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(json.dumps({
                "status": "unfixable",
                "message": f"{len(violations)} item(s) violate the standard, but the destination {destination} "
                           f"couldn't be created: {e}",
            }))
            return 0

    resolved, failed = [], []
    for item, age in violations:
        target = destination / item.name
        if os.path.lexists(target):
            failed.append(f"{item.name} (a '{item.name}' already exists at {destination}, not overwritten)")
            continue
        try:
            move_item(item, target)
            resolved.append(item.name)
        except OSError as e:
            failed.append(f"{item.name} ({e})")

    if not failed:
        message = f"{len(resolved)} item(s) moved to {destination}"
        print(json.dumps({"status": "fixed", "message": message}))
        return 0

    shown = failed[:10]
    more = f", and {len(failed) - 10} more" if len(failed) > 10 else ""
    message = (
        f"{len(resolved)} of {len(violations)} item(s) moved to {destination}; "
        f"{len(failed)} unresolved: {', '.join(shown)}{more}"
    )
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
