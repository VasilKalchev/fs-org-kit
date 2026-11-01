#!/usr/bin/env python3
"""
timestamp-consistency-v1-check.py - checks that a file or folder's own
embedded timestamp doesn't contradict the timestamps embedded in its
ancestor folder names. See timestamp-consistency-v1.toml for the full
param documentation and recognized pattern list.

Protocol (protocol_version 1.0, single scope):
    python timestamp-consistency-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import calendar
import json
import re
import sys
from pathlib import Path

FIELD_NAMES = ("year", "month", "day", "hour", "minute", "second")

# most specific first - order doesn't actually matter for correctness
# (every pattern is fully anchored, so lengths can't collide), but kept
# specific-to-general for readability
DATETIME_PATTERN = re.compile(r"^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})(?=[^0-9]|$)")
FULL_DATE_PATTERN = re.compile(r"^(\d{4})-?(\d{2})-?(\d{2})$")
YEAR_MONTH_PATTERN = re.compile(r"^(\d{4})-?(\d{2})$")
YEAR_PATTERN = re.compile(r"^(\d{4})$")


def parse_component(name: str) -> tuple | None:
    """Returns a 6-tuple (year, month, day, hour, minute, second), each
    an int or None, or None if nothing recognizable was found at all.
    Digits in a timestamp's shape that name no real moment ("2024-13",
    "20240230") aren't a timestamp."""
    fields = _match_component(name)
    return fields if fields is not None and _is_real(fields) else None


def _is_real(fields: tuple) -> bool:
    year, month, day, hour, minute, second = fields
    if year < 1:
        return False
    if month is not None and not 1 <= month <= 12:
        return False
    if day is not None and not 1 <= day <= calendar.monthrange(year, month)[1]:
        return False
    return all(v is None or 0 <= v < limit for v, limit in ((hour, 24), (minute, 60), (second, 60)))


def _match_component(name: str) -> tuple | None:
    m = DATETIME_PATTERN.match(name)
    if m:
        y, mo, d, h, mi, s = map(int, m.groups())
        return (y, mo, d, h, mi, s)

    m = FULL_DATE_PATTERN.match(name)
    if m:
        y, mo, d = map(int, m.groups())
        return (y, mo, d, None, None, None)

    m = YEAR_MONTH_PATTERN.match(name)
    if m:
        y, mo = map(int, m.groups())
        return (y, mo, None, None, None, None)

    m = YEAR_PATTERN.match(name)
    if m:
        return (int(m.group(1)), None, None, None, None, None)

    return None


def merge_check(accumulated: dict, new_fields: tuple) -> tuple[dict, str | None]:
    """Returns (updated_accumulated, conflict_description_or_None)."""
    conflicts = []
    updated = dict(accumulated)
    for i, field_name in enumerate(FIELD_NAMES):
        new_val = new_fields[i]
        if new_val is None:
            continue
        existing = accumulated.get(field_name)
        if existing is not None and existing != new_val:
            conflicts.append(f"{field_name} {new_val} contradicts already-established {field_name} {existing}")
        else:
            updated[field_name] = new_val
    return updated, ("; ".join(conflicts) if conflicts else None)


def walk(current_dir: Path, accumulated: dict, recursive: bool, require_all: bool, root: Path, violations: list) -> None:
    try:
        children = sorted(current_dir.iterdir())
    except OSError:
        return  # unreadable - nothing in it can be judged, which isn't a reason to fail the rest
    for child in children:
        parsed = parse_component(child.name)
        if parsed is None:
            if require_all:
                violations.append((child.relative_to(root), "no recognizable timestamp in name"))
            child_accumulated = accumulated
        else:
            child_accumulated, conflict = merge_check(accumulated, parsed)
            if conflict:
                violations.append((child.relative_to(root), conflict))
                # keep descending with the OLD accumulated state, not the
                # conflicting one - avoids re-reporting the same conflict
                # for every single file under one bad folder
                child_accumulated = accumulated

        # a symlinked folder isn't descended into: a link back up the
        # tree would recurse until the interpreter gave up
        if child.is_dir() and not child.is_symlink() and recursive:
            walk(child, child_accumulated, recursive, require_all, root, violations)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: timestamp-consistency-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    recursive = params.get("recursive", True)
    require_all = params.get("require_all_components_timestamped", False)

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    violations: list = []
    walk(root, {}, recursive, require_all, root, violations)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    parts = [f"{path} ({reason})" for path, reason in shown]
    message = f"{len(violations)} item(s) with inconsistent timestamps: {', '.join(parts)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
