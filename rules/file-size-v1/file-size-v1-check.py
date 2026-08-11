#!/usr/bin/env python3
"""
file-size-v1-check.py - checks each file individually against per-file
max_size/min_size thresholds. See file-size-v1.toml for the full param
documentation, including why this isn't a folder-structure-v1 param.

Protocol (protocol_version 1.0, single scope):
    python file-size-v1-check.py --path <dir> --params '<json>'

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

# Deliberately identical to folder-structure-v1's vocabulary, so a size
# written in the standard means the same thing wherever it appears. A
# rule is a standalone script and can't import from a sibling rule.
SIZE_UNITS = {"B": 1, "KIB": 1024, "MIB": 1024**2, "GIB": 1024**3, "TIB": 1024**4}
SIZE_PATTERN = re.compile(r"^(\d+(?:\.\d+)?)\s*([A-Za-z]*)$")

MAX_REPORTED = 5


def parse_size(value) -> int:
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


def is_excluded(relative_posix: str, exclude_globs: list) -> bool:
    return any(fnmatch.fnmatch(relative_posix, pattern) for pattern in exclude_globs)


def normalize_extensions(values: list) -> set:
    """'.JPG' and 'jpg' are the same filter."""
    return {str(v).lstrip(".").lower() for v in values if str(v).strip()}


def collect_files(root: Path, recursive: bool, exclude_globs: list, extensions: set):
    """Every file to be checked. Excluding a folder prunes its subtree.

    Symlinks are skipped before stat: a symlink's own size is the length
    of the path it stores, and following it would measure a file outside
    the tree - see the manifest.
    """
    for child in sorted(root.iterdir()):
        rel = child.relative_to(root).as_posix()
        if is_excluded(rel, exclude_globs):
            continue
        if child.is_symlink():
            continue
        if child.is_dir():
            if recursive:
                yield from collect_files(child, recursive, exclude_globs, extensions)
        elif child.is_file():
            if extensions and child.suffix.lstrip(".").lower() not in extensions:
                continue
            yield child


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: file-size-v1 has no fixer", file=sys.stderr)
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

    max_size_str = params.get("max_size", "")
    min_size_str = params.get("min_size", "")
    if not max_size_str and not min_size_str:
        # A threshold-less attachment can only ever report ok, which
        # looks like a passing check rather than the authoring mistake
        # it is. Same stance as file-extensions-v1's empty-lists check.
        print("error: at least one of `max_size`/`min_size` must be set",
              file=sys.stderr)
        return 1

    try:
        max_size = parse_size(max_size_str) if max_size_str else None
        min_size = parse_size(min_size_str) if min_size_str else None
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1

    if max_size is not None and min_size is not None and min_size > max_size:
        print(f"error: min_size ({format_size(min_size)}) exceeds max_size "
              f"({format_size(max_size)}) - no file could satisfy both",
              file=sys.stderr)
        return 1

    exclude = params.get("exclude", [])
    if not isinstance(exclude, list):
        print("error: `exclude` must be a list of glob strings", file=sys.stderr)
        return 1

    extensions_param = params.get("extensions", [])
    if not isinstance(extensions_param, list):
        print("error: `extensions` must be a list", file=sys.stderr)
        return 1

    recursive = bool(params.get("recursive", True))
    extensions = normalize_extensions(extensions_param)

    over: list = []
    under: list = []
    for f in collect_files(root, recursive, exclude, extensions):
        try:
            size = f.stat().st_size
        except OSError as e:
            print(f"error: cannot stat {f}: {e}", file=sys.stderr)
            return 1
        rel = f.relative_to(root).as_posix()
        if max_size is not None and size > max_size:
            over.append((rel, size))
        elif min_size is not None and size < min_size:
            under.append((rel, size))

    if not over and not under:
        print(json.dumps({"status": "ok"}))
        return 0

    parts = []
    for label, found, limit in (("exceed", over, max_size), ("below", under, min_size)):
        if not found:
            continue
        shown = ", ".join(f"{rel} ({format_size(size)})" for rel, size in found[:MAX_REPORTED])
        if len(found) > MAX_REPORTED:
            shown += f", and {len(found) - MAX_REPORTED} more"
        preposition = "exceed max" if label == "exceed" else "below min"
        parts.append(f"{len(found)} file(s) {preposition} {format_size(limit)}: {shown}")

    print(json.dumps({"status": "violation", "message": "; ".join(parts)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
