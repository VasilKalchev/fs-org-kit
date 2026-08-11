#!/usr/bin/env python3
"""
folder-structure-v1-check.py - checks item/file/folder counts, folder
nesting depth, and total size against configured thresholds. See
folder-structure-v1.toml for the full param documentation.

Protocol (protocol_version 1.0, single scope):
    python folder-structure-v1-check.py --path <dir> --params '<json>'

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

SIZE_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}
SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$")


def is_excluded(relative_posix: str, exclude_globs: list) -> bool:
    return any(fnmatch.fnmatch(relative_posix, pattern) for pattern in exclude_globs)


def walk(folder: Path, root: Path, exclude_globs: list):
    """Yields every non-excluded descendant of `folder`, recursively -
    an excluded folder's contents are skipped too, not just the folder
    itself, so exclusion prunes the whole subtree."""
    for child in sorted(folder.iterdir()):
        rel = child.relative_to(root).as_posix()
        if is_excluded(rel, exclude_globs):
            continue
        yield child
        if child.is_dir():
            yield from walk(child, root, exclude_globs)


def direct_children_of(folder: Path, root: Path, exclude_globs: list) -> list:
    return [
        c for c in folder.iterdir()
        if not is_excluded(c.relative_to(root).as_posix(), exclude_globs)
    ]


def parse_size(value: str) -> int:
    """'500MiB' -> bytes. Bare integer strings/numbers are bytes."""
    m = SIZE_PATTERN.match(str(value).strip())
    if not m:
        raise ValueError(f"not a recognized size: {value!r}")
    number, unit = m.groups()
    unit = unit.upper() or "B"
    if unit not in SIZE_UNITS:
        raise ValueError(f"unrecognized size unit in {value!r}: {unit}")
    return int(float(number) * SIZE_UNITS[unit])


def format_size(n: int) -> str:
    for unit, factor in reversed(list(SIZE_UNITS.items())):
        if n >= factor and unit != "B":
            return f"{n / factor:.1f}{unit.replace('IB', 'iB')}"
    return f"{n}B"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: folder-structure-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    def limit(name: str, sentinel):
        v = params.get(name, sentinel)
        return None if v == sentinel else v

    max_items = limit("max_items", -1)
    min_items = limit("min_items", -1)
    max_files = limit("max_files", -1)
    min_files = limit("min_files", -1)
    max_folders = limit("max_folders", -1)
    min_folders = limit("min_folders", -1)
    max_depth = limit("max_depth", -1)
    max_size_str = limit("max_size", "")
    min_size_str = limit("min_size", "")

    try:
        max_size = parse_size(max_size_str) if max_size_str is not None else None
        min_size = parse_size(min_size_str) if min_size_str is not None else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    recursive = params.get("recursive", False)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    deepest = 0
    total_size = 0
    all_folders = [root]
    for item in walk(root, root, exclude_globs):
        if item.is_dir():
            depth = len(item.relative_to(root).parts)
            deepest = max(deepest, depth)
            all_folders.append(item)
        elif item.is_file():
            try:
                total_size += item.stat().st_size
            except OSError:
                pass

    violations = []

    def check(value, max_v, min_v, label):
        if max_v is not None and value > max_v:
            violations.append(f"{label} is {value}, exceeds max {max_v}")
        if min_v is not None and value < min_v:
            violations.append(f"{label} is {value}, below min {min_v}")

    folders_to_check = all_folders if recursive else [root]
    for folder in folders_to_check:
        children = direct_children_of(folder, root, exclude_globs)
        files = [c for c in children if c.is_file()]
        folders = [c for c in children if c.is_dir()]
        where = "" if folder == root else f" under '{folder.relative_to(root).as_posix()}'"

        before = len(violations)
        check(len(children), max_items, min_items, "item count")
        check(len(files), max_files, min_files, "file count")
        check(len(folders), max_folders, min_folders, "folder count")
        if where:
            for i in range(before, len(violations)):
                violations[i] += where

    if max_depth is not None and deepest > max_depth:
        violations.append(f"folder depth is {deepest}, exceeds max {max_depth}")
    if max_size is not None and total_size > max_size:
        violations.append(f"total size is {format_size(total_size)}, exceeds max {format_size(max_size)}")
    if min_size is not None and total_size < min_size:
        violations.append(f"total size is {format_size(total_size)}, below min {format_size(min_size)}")

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    message = "; ".join(violations)
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
