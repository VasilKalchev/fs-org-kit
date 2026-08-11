#!/usr/bin/env python3
"""
folder-icon-inherit-v1-check.py - reports child folders whose icon color
doesn't match their parent's. See folder-icon-inherit-v1.toml for why
color is inherited but variant isn't, and which platforms this applies to.

Protocol (protocol_version 1.0, single scope):
    python folder-icon-inherit-v1-check.py --path <dir> --params '<json>'

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

from _shared import BadParams, UNMANAGED, evaluate, fail, read_settings

MAX_REPORTED = 8


def excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: --fix belongs to folder-icon-inherit-v1-fix.py, not the checker", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    if not settings.parent_color:
        # Nothing to propagate. Reported rather than silently passing:
        # an attachment asking children to match a color the parent
        # doesn't have is a gap in the standard, not a clean result.
        print(json.dumps({
            "status": "violation",
            "message": f"no color to inherit - {settings.root} has no icon color set, "
                       f"and no `color` param was given",
        }))
        return 0

    findings = evaluate(settings, excluded)
    if not findings:
        print(json.dumps({"status": "ok"}))
        return 0

    described = [
        f"{rel} ({current or 'no icon'} -> {desired})" if action != UNMANAGED
        else f"{rel} (custom icon {current!r}, left alone)"
        for action, rel, current, desired in findings
    ]
    shown = ", ".join(described[:MAX_REPORTED])
    if len(described) > MAX_REPORTED:
        shown += f", ... ({len(described) - MAX_REPORTED} more)"
    print(json.dumps({
        "status": "violation",
        "message": f"{len(findings)} folder(s) don't match the parent color '{settings.parent_color}': {shown}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
