#!/usr/bin/env python3
"""
uncataloged-reserved-v1-check.py - finds folders whose name starts with
the reserved prefix but aren't in the `cataloged` list. See
uncataloged-reserved-v1.toml for the full param documentation.

Protocol (protocol_version 1.0, single scope):
    python uncataloged-reserved-v1-check.py --path <dir> --params '<json>'

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


def iter_entries(root: Path, recursive: bool, exclude_globs: list):
    """Every entry under root, in a stable order, minus what `exclude`
    names. A glob is matched against the path relative to root and
    against the bare name, and an excluded folder takes its whole
    subtree with it - the same reading every bundled rule's `exclude`
    has. Symlinked folders are listed, never descended into."""
    def walk(folder: Path):
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            rel = child.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(child.name, g) for g in exclude_globs):
                continue
            yield child
            if recursive and child.is_dir() and not child.is_symlink():
                yield from walk(child)

    yield from walk(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: uncataloged-reserved-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    prefix = params.get("prefix", "_")
    if not isinstance(prefix, str) or not prefix:
        print("error: prefix must be a non-empty string", file=sys.stderr)
        return 1

    # `cataloged` is either a literal list of names, or the standard's
    # whole [folders.reserved] table handed over by a {ref = "..."}. In
    # the table case an entry is always a sub-table and the schema-level
    # keys beside them (`prefix`) are not, so keeping the table-valued
    # keys drops those without this script knowing their names.
    cataloged = params.get("cataloged", [])
    if isinstance(cataloged, dict):
        cataloged = [name for name, entry in cataloged.items() if isinstance(entry, dict)]
    cataloged = set(cataloged)

    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    folders = iter_entries(root, recursive, exclude_globs)
    uncataloged = []
    for f in folders:
        if not f.is_dir():
            continue
        if not f.name.startswith(prefix):
            continue
        rel = f.relative_to(root).as_posix()
        if f.name not in cataloged:
            uncataloged.append(rel)

    if not uncataloged:
        print(json.dumps({"status": "ok"}))
        return 0

    uncataloged.sort()
    shown = uncataloged[:10]
    more = f", and {len(uncataloged) - 10} more" if len(uncataloged) > 10 else ""
    message = f"{len(uncataloged)} folder(s) start with '{prefix}' but aren't cataloged: {', '.join(shown)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
