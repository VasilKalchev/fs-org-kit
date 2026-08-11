#!/usr/bin/env python3
"""
file-extensions-v1-check.py - checks that every file under --path has an
allowed extension, or does not have a disallowed one. See rule.toml for
the full param documentation.

This rule has no fixer (see rule.toml) - it only ever runs in check mode.

Protocol (protocol_version 1.0, single scope):
    python file-extensions-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken (bad params, bad path,
           or invoked with --fix) - stderr has why
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path


def extension_of(file: Path) -> str:
    suffix = file.suffix.lower()
    return suffix[1:] if suffix else "none"


def normalize(extensions: list) -> set:
    return {str(e).lower().lstrip(".") for e in extensions}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: file-extensions-v1 has no fixer - it should never be invoked with --fix", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    allowed = normalize(params.get("allowed", []))
    disallowed = normalize(params.get("disallowed", []))
    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    if bool(allowed) == bool(disallowed):
        print(
            "error: exactly one of `allowed` or `disallowed` must be a non-empty list "
            f"(got allowed={sorted(allowed)}, disallowed={sorted(disallowed)})",
            file=sys.stderr,
        )
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    files = root.rglob("*") if recursive else root.glob("*")
    violations = []
    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, p) for p in exclude_globs):
            continue
        ext = extension_of(f)
        if allowed and ext not in allowed:
            violations.append(f)
        elif disallowed and ext in disallowed:
            violations.append(f)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    names = sorted(str(f.relative_to(root)) for f in violations)
    shown = names[:10]
    more = f", and {len(names) - 10} more" if len(names) > 10 else ""
    mode = f"not in the allowed list {sorted(allowed)}" if allowed else f"in the disallowed list {sorted(disallowed)}"
    message = f"{len(names)} file(s) with an extension {mode}: {', '.join(shown)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
