#!/usr/bin/env python3
"""
naming-pattern-v1-check.py - checks file/folder names against a regex,
either as an allowlist (every name must match) or a disallowlist (no
name may match). See naming-pattern-v1.toml for full param docs.

Protocol (protocol_version 1.0, single scope):
    python naming-pattern-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: naming-pattern-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    pattern_str = params.get("pattern")
    if not pattern_str:
        print("error: pattern is required and must be non-empty", file=sys.stderr)
        return 1
    try:
        pattern = re.compile(pattern_str)
    except re.error as e:
        print(f"error: pattern is not a valid regular expression: {e}", file=sys.stderr)
        return 1

    mode = params.get("mode")
    if mode not in ("allow", "disallow"):
        print(f"error: mode must be 'allow' or 'disallow', got {mode!r}", file=sys.stderr)
        return 1

    target = params.get("target", "both")
    if target not in ("files", "folders", "both"):
        print(f"error: target must be 'files', 'folders', or 'both', got {target!r}", file=sys.stderr)
        return 1

    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    items = root.rglob("*") if recursive else root.glob("*")
    violations = []
    for item in items:
        is_dir = item.is_dir()
        if is_dir and target == "files":
            continue
        if not is_dir and target == "folders":
            continue

        rel = item.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, p) for p in exclude_globs):
            continue

        matched = bool(pattern.search(item.name))
        if mode == "allow" and not matched:
            violations.append(rel)
        elif mode == "disallow" and matched:
            violations.append(rel)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    violations.sort()
    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    verb = "doesn't match the required pattern" if mode == "allow" else "matches the disallowed pattern"
    message = f"{len(violations)} item(s) that {verb}: {', '.join(shown)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
