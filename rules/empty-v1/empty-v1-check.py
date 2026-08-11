#!/usr/bin/env python3
"""
empty-v1-check.py - reports zero-byte files and empty folders. See
empty-v1.toml for the full param documentation, including the two
readings of "empty folder" and why there's no fixer.

Protocol (protocol_version 1.0, single scope):
    python empty-v1-check.py --path <dir> --params '<json>'

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

EMPTY_MEANINGS = ("no_entries", "no_files")
MAX_REPORTED = 8


def is_excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def has_any_file(folder: Path) -> bool:
    """True if any real file exists anywhere below `folder`. Used for the
    "no_files" reading, where a tree of empty folders is itself empty.
    Symlinks count as content: something deliberately put one there."""
    try:
        for child in folder.iterdir():
            if child.is_symlink() or child.is_file():
                return True
            if child.is_dir() and has_any_file(child):
                return True
    except OSError:
        return True  # unreadable - can't claim it's empty
    return False


def folder_is_empty(folder: Path, meaning: str) -> bool:
    try:
        entries = list(folder.iterdir())
    except OSError:
        return False
    if not entries:
        return True
    return meaning == "no_files" and not has_any_file(folder)


def walk(root: Path, base: Path, recursive: bool, exclude: list, meaning: str,
         check_files: bool, check_folders: bool, found: list) -> None:
    """Collect every empty thing under `root`, reporting paths relative to
    `base` so the message reads the same however deep the recursion went."""
    try:
        children = sorted(root.iterdir())
    except OSError:
        return
    for child in children:
        rel = child.relative_to(base).as_posix()
        if is_excluded(rel, exclude):
            continue
        if child.is_symlink():
            continue  # see the manifest - a symlink is never "empty"
        if child.is_dir():
            if check_folders and folder_is_empty(child, meaning):
                found.append(f"{rel}/")
                continue  # already reported as a whole; don't also list what's inside
            if recursive:
                walk(child, base, recursive, exclude, meaning, check_files, check_folders, found)
        elif child.is_file() and check_files:
            try:
                if child.stat().st_size == 0:
                    found.append(rel)
            except OSError:
                continue


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        # The runner never does this - it invokes a -fix.py directly when
        # one exists. Rejecting it anyway turns a runner bug into a loud
        # failure instead of a silently wrong result.
        print("error: empty-v1 has no fixer", file=sys.stderr)
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

    check_files = bool(params.get("check_files", True))
    check_folders = bool(params.get("check_folders", True))
    recursive = bool(params.get("recursive", True))
    exclude = params.get("exclude", [])
    meaning = params.get("folder_empty_means", "no_entries")

    if not isinstance(exclude, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1
    if meaning not in EMPTY_MEANINGS:
        print(f"error: folder_empty_means must be one of {list(EMPTY_MEANINGS)}, got {meaning!r}", file=sys.stderr)
        return 1
    if not check_files and not check_folders:
        # Nothing to look for. Reporting "ok" would be a clean bill of
        # health this invocation never actually checked for.
        print("error: check_files and check_folders are both false - this attachment can never report anything",
              file=sys.stderr)
        return 1

    if check_folders and folder_is_empty(root, meaning):
        print(json.dumps({"status": "violation", "message": f"{root} is empty"}))
        return 0

    found: list[str] = []
    walk(root, root, recursive, exclude, meaning, check_files, check_folders, found)

    if not found:
        print(json.dumps({"status": "ok"}))
        return 0

    shown = ", ".join(found[:MAX_REPORTED])
    if len(found) > MAX_REPORTED:
        shown += f", ... ({len(found) - MAX_REPORTED} more)"
    print(json.dumps({
        "status": "violation",
        "message": f"{len(found)} empty item(s): {shown}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
