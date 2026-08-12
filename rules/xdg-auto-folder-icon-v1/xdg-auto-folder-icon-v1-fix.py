#!/usr/bin/env python3
"""
xdg-auto-folder-icon-v1-fix.py - writes the icon each folder's name or
contents call for. Self-contained per the protocol: it evaluates and
writes in one pass rather than re-running the checker first.

Protocol (protocol_version 1.0, single scope):
    python xdg-auto-folder-icon-v1-fix.py --path <dir> --params '<json>' --fix

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "fixed", "message": "..."}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import sys
from pathlib import Path

from _shared import BadParams, evaluate, fail, read_settings, write_icon

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
        print("error: xdg-auto-folder-icon-v1-fix.py must be invoked with --fix", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    findings = evaluate(settings, excluded)
    if not findings:
        print(json.dumps({"status": "ok"}))
        return 0

    written: list[str] = []
    failed: list[str] = []
    for rel, _current, desired in findings:
        try:
            write_icon(settings.root / rel, desired)
            written.append(f"{rel} -> {desired}")
        except OSError as e:
            failed.append(f"{rel} ({e})")

    if not failed:
        print(json.dumps({
            "status": "fixed",
            "message": f"{len(written)} folder icon(s) set: {summarize(written)}",
        }))
        return 0

    parts = []
    if written:
        parts.append(f"{len(written)} folder icon(s) set: {summarize(written)}")
    parts.append(f"{len(failed)} could not be written: {summarize(failed)}")
    print(json.dumps({"status": "violation", "message": "; ".join(parts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
