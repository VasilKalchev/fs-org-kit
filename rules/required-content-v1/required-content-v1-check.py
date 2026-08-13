#!/usr/bin/env python3
"""
required-content-v1-check.py - checks a path for entries it must have,
should have, or must not have. See required-content-v1.toml for why the
params are three flat lists, what a trailing slash means, and how this
relates to naming-pattern-v1.

Protocol (protocol_version 1.0, single scope):
    python required-content-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path

TIERS = ("required", "suggested", "forbidden")
MAX_REPORTED = 8


def entries_under(root: Path) -> list[tuple[str, str, bool]]:
    """(relative posix path, basename, is_dir) for everything under root.
    Collected once and reused for every pattern - a standard can attach a
    dozen globs to one path, and re-walking per glob would read the tree a
    dozen times. The basename is carried along because the walk already
    has it; recovering it later would mean a throwaway Path per entry per
    pattern."""
    found: list[tuple[str, str, bool]] = []

    def walk(folder: Path) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            is_dir = child.is_dir() and not child.is_symlink()
            found.append((child.relative_to(root).as_posix(), child.name, is_dir))
            if is_dir:
                walk(child)

    walk(root)
    return found


def matches(pattern: str, entries: list[tuple[str, str, bool]]) -> list[str]:
    """Every entry satisfying one pattern. A trailing slash restricts the
    match to directories - "build/" and "build" ask different questions,
    and a file where a folder belongs is worth catching."""
    directories_only = pattern.endswith("/")
    bare = pattern.rstrip("/")
    hits = []
    for rel, name, is_dir in entries:
        if directories_only and not is_dir:
            continue
        # Matched against the relative path, so "src/*.py" works, and
        # against the bare name, so "*.pyc" catches one at any depth
        # without needing a "**/" prefix.
        if fnmatch.fnmatch(rel, bare) or fnmatch.fnmatch(name, bare):
            hits.append(rel + ("/" if is_dir else ""))
    return hits


def summarize(items: list, limit: int = MAX_REPORTED) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f", ... ({len(items) - limit} more)" if len(items) > limit else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: required-content-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    tiers = {}
    for tier in TIERS:
        value = params.get(tier, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            print(f"error: {tier} must be a list of glob strings", file=sys.stderr)
            return 1
        tiers[tier] = value

    report_suggested = bool(params.get("report_suggested", True))

    if not any(tiers.values()):
        # Nothing asserted, so this attachment can only ever report ok.
        print("error: required, suggested and forbidden are all empty - this attachment asserts nothing",
              file=sys.stderr)
        return 1

    entries = entries_under(root)
    problems: list[str] = []

    missing_required = [p for p in tiers["required"] if not matches(p, entries)]
    if missing_required:
        problems.append(f"missing required: {summarize(missing_required)}")

    if report_suggested:
        missing_suggested = [p for p in tiers["suggested"] if not matches(p, entries)]
        if missing_suggested:
            problems.append(f"missing suggested: {summarize(missing_suggested)}")

    present_forbidden: list[str] = []
    for pattern in tiers["forbidden"]:
        present_forbidden.extend(matches(pattern, entries))
    if present_forbidden:
        problems.append(f"present but forbidden: {summarize(sorted(set(present_forbidden)))}")

    if not problems:
        print(json.dumps({"status": "ok"}))
        return 0
    print(json.dumps({"status": "violation", "message": "; ".join(problems)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
