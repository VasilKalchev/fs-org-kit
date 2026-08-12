#!/usr/bin/env python3
"""
xdg-inherit-folder-icon-color-v1-fix.py - writes the parent's color into each child
folder's .directory, keeping the child's own icon variant. Self-contained
per the protocol: it evaluates and writes in one pass rather than
re-running the checker first.

Protocol (protocol_version 1.0, single scope):
    python xdg-inherit-folder-icon-color-v1-fix.py --path <dir> --params '<json>' --fix

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "fixed", "message": "..."}
                               | {"status": "violation", "message": "..."}
                               | {"status": "unfixable", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why

Two categories are reported but never written: a folder carrying a custom
icon this rule didn't compose, and - when on_different_color is "warn" -
a folder whose color was set deliberately to something else. Both come
back as `violation` rather than `fixed`, since the mismatch is still
there afterwards.
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path

from _shared import BadParams, RECOLOR, SET, UNMANAGED, evaluate, fail, read_settings, write_icon

MAX_REPORTED = 8


def excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def summarize(items: list, limit: int = MAX_REPORTED) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f", ... ({len(items) - limit} more)" if len(items) > limit else "")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if not args.fix:
        # The runner always passes --fix to a fixer. Without it this would
        # rewrite .directory files while looking like a dry run.
        print("error: xdg-inherit-folder-icon-color-v1-fix.py must be invoked with --fix", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    if not settings.parent_color:
        print(json.dumps({
            "status": "unfixable",
            "message": f"no color to inherit - {settings.root} has no icon color set, "
                       f"and no `color` param was given",
        }))
        return 0

    findings = evaluate(settings, excluded)
    if not findings:
        print(json.dumps({"status": "ok"}))
        return 0

    written: list[str] = []
    left_alone: list[str] = []
    failed: list[str] = []

    for action, rel, current, desired in findings:
        if action not in (SET, RECOLOR):
            label = f"{rel} (custom icon {current!r})" if action == UNMANAGED else f"{rel} ({current})"
            left_alone.append(label)
            continue
        try:
            write_icon(settings.root / rel, desired)
            written.append(f"{rel} -> {desired}")
        except OSError as e:
            failed.append(f"{rel} ({e})")

    if written and not left_alone and not failed:
        print(json.dumps({
            "status": "fixed",
            "message": f"{len(written)} folder(s) recolored to '{settings.parent_color}': {summarize(written)}",
        }))
        return 0

    parts = []
    if written:
        parts.append(f"{len(written)} folder(s) recolored: {summarize(written)}")
    if left_alone:
        parts.append(f"{len(left_alone)} left as-is: {summarize(left_alone)}")
    if failed:
        parts.append(f"{len(failed)} could not be written: {summarize(failed)}")
    print(json.dumps({"status": "violation", "message": "; ".join(parts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
