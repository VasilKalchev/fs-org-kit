#!/usr/bin/env python3
"""
timestamp-format-v1-check.py - checks that any name whose leading
characters form a real calendar date or datetime uses one of the
standard's accepted formats. See timestamp-format-v1.toml for the full
param documentation, including the two-pass "is it timestamped at all,
then is it in the accepted list" algorithm.

Protocol (protocol_version 1.0, single scope):
    python timestamp-format-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import sys
from datetime import datetime
from pathlib import Path

# A reference datetime where every numeric field renders at its maximum
# width (2 digits for month/day/hour/minute/second) - used to measure
# how many characters a format string "should" occupy, so a candidate
# span of exactly that length can be sliced off the front of a name and
# tested. Only fixed-width directives (%Y %m %d %H %M %S, plus literal
# characters) are supported - see the manifest's `formats` docs.
REFERENCE_DT = datetime(2020, 12, 31, 23, 59, 59)

# Built-in, non-configurable: exists only to decide whether a name
# "looks like an attempted timestamp" at all, not to accept anything -
# see the manifest's "How looks timestamped is decided" section.
DETECTOR_FORMATS = [
    "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d_%H:%M:%S",
    "%Y-%m-%d_%H-%M-%S",
    "%Y%m%d_%H%M%S",
    "%Y%m%dT%H%M%S",
    "%Y%m%d%H%M%S",
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y%m%d",
]


def format_length(fmt: str) -> int:
    return len(REFERENCE_DT.strftime(fmt))


def prepare_formats(formats: list) -> list:
    """Pair each format with its rendered length, longest first. Built
    once per run rather than per filesystem entry: format_length is a
    strftime call, far more expensive than the comparison it feeds, and
    match_leading runs twice for every item in the tree. Sorted on the
    length alone, so same-length formats keep their declared order and
    the first match stays the one it was before."""
    return sorted(((format_length(f), f) for f in formats), key=lambda pair: pair[0], reverse=True)


# the detector list is fixed, so its lengths are computed once at import
PREPARED_DETECTORS = prepare_formats(DETECTOR_FORMATS)


def match_leading(name: str, prepared: list):
    """Tries each format (longest expected span first) as a fixed-length
    slice off the front of `name`. Returns (matched_text, fmt) for the
    first one that's both the right shape and a real calendar
    date/datetime, or None if nothing in the list matches at all.
    `prepared` comes from prepare_formats."""
    for length, fmt in prepared:
        if length > len(name):
            continue
        candidate = name[:length]
        if length < len(name) and name[length].isdigit():
            continue  # would be truncating a longer digit run
        try:
            datetime.strptime(candidate, fmt)
        except ValueError:
            continue
        return candidate, fmt
    return None


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
        print("error: timestamp-format-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    formats = params.get("formats", [])
    if not isinstance(formats, list) or not formats:
        print("error: formats must be a non-empty list of strptime-style format strings", file=sys.stderr)
        return 1
    try:
        prepared = prepare_formats(formats)
    except (TypeError, ValueError) as e:
        print(f"error: not a usable strptime format string: {e}", file=sys.stderr)
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

    items = iter_entries(root, recursive, exclude_globs)
    violations = []
    for item in items:
        is_dir = item.is_dir()
        if is_dir and target == "files":
            continue
        if not is_dir and target == "folders":
            continue

        rel = item.relative_to(root).as_posix()

        if match_leading(item.name, prepared) is not None:
            continue  # correctly formatted

        detected = match_leading(item.name, PREPARED_DETECTORS)
        if detected is not None:
            matched_text, _ = detected
            violations.append((rel, matched_text))
        # else: no leading timestamp at all - not this rule's concern

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    violations.sort(key=lambda v: v[0])
    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    parts = [f"{rel} (found {matched_text!r}, not in the accepted formats)" for rel, matched_text in shown]
    message = f"{len(violations)} item(s) with a badly-formatted timestamp: {', '.join(parts)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
