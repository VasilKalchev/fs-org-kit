#!/usr/bin/env python3
"""
basename-sync-v1-check.py - checks whether 2+ paths agree on which files
exist by name (their stem), across extensions. See basename-sync-v1.toml
for the full param documentation.

Protocol (protocol_version 1.0, cross scope):
    python basename-sync-v1-check.py --paths <p1> --paths <p2> [...] --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken (bad params, bad path,
           or invoked with --fix) - stderr has why
"""

import argparse
import json
import sys
from pathlib import Path

from _shared import find_violations, normalize_extensions


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: basename-sync-v1-check.py has no fixing capability - invoke basename-sync-v1-fix.py instead", file=sys.stderr)
        return 1

    if len(args.paths) < 2:
        print(f"error: scope=cross needs 2 or more --paths, got {len(args.paths)}", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    mode = params.get("mode")
    if mode not in ("shared", "exclusive"):
        print(f"error: mode must be 'shared' or 'exclusive', got {mode!r}", file=sys.stderr)
        return 1

    recursive = params.get("recursive", True)
    allowed_extensions = normalize_extensions(params.get("extensions", []))
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    roots = [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1

    violations = find_violations(roots, recursive, allowed_extensions, exclude_globs, mode)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    stems = sorted(violations.keys())
    shown = stems[:10]
    more = f", and {len(stems) - 10} more" if len(stems) > 10 else ""

    if mode == "shared":
        parts = []
        for stem in shown:
            missing_from = violations[stem]["missing"]
            parts.append(f"{stem} (missing from {len(missing_from)} of {len(roots)} path(s))")
        message = f"{len(stems)} stem(s) not present in all {len(roots)} path(s): {', '.join(parts)}{more}"
    else:
        parts = []
        for stem in shown:
            present = violations[stem]["present"]
            parts.append(f"{stem} (present in {len(present)} paths)")
        message = f"{len(stems)} stem(s) present in more than one path: {', '.join(parts)}{more}"

    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
