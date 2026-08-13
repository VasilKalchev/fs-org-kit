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
import os
import re
import sys
from pathlib import Path

SIZE_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}
SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$")


def is_excluded(relative_posix: str, exclude_globs: list) -> bool:
    return any(fnmatch.fnmatch(relative_posix, pattern) for pattern in exclude_globs)


def scan_tree(root: Path, exclude_globs: list):
    """Single pass over the tree, one os.scandir() per folder - depth,
    total size, and each folder's direct item/file/folder counts are all
    collected while the tree is walked, instead of a second full listing
    pass over folders already visited.

    Returns (folder_stats, deepest, total_size) where folder_stats is a
    pre-order list of (folder, item_count, file_count, folder_count) for
    `root` and every folder beneath it - the same set and order `walk()`
    used to build `all_folders` in, so `folder_stats[0]` is always root's
    own entry."""
    folder_stats = []
    deepest = 0
    total_size = 0

    def visit(folder: Path, depth: int):
        nonlocal deepest, total_size
        deepest = max(deepest, depth)
        try:
            entries = sorted(os.scandir(folder), key=lambda e: e.name)
        except OSError:
            entries = []
        items = files = folders = 0
        subdirs = []
        for entry in entries:
            child = Path(entry.path)
            rel = child.relative_to(root).as_posix()
            if is_excluded(rel, exclude_globs):
                continue
            items += 1
            if entry.is_dir():
                folders += 1
                subdirs.append(child)
            elif entry.is_file():
                files += 1
                try:
                    total_size += entry.stat().st_size
                except OSError:
                    pass
        folder_stats.append((folder, items, files, folders))
        for sub in subdirs:
            visit(sub, depth + 1)

    visit(root, 0)
    return folder_stats, deepest, total_size


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

    folder_stats, deepest, total_size = scan_tree(root, exclude_globs)

    violations = []

    def check(value, max_v, min_v, label):
        if max_v is not None and value > max_v:
            violations.append(f"{label} is {value}, exceeds max {max_v}")
        if min_v is not None and value < min_v:
            violations.append(f"{label} is {value}, below min {min_v}")

    stats_to_check = folder_stats if recursive else folder_stats[:1]
    for folder, items, files, folders in stats_to_check:
        where = "" if folder == root else f" under '{folder.relative_to(root).as_posix()}'"

        before = len(violations)
        check(items, max_items, min_items, "item count")
        check(files, max_files, min_files, "file count")
        check(folders, max_folders, min_folders, "folder count")
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
