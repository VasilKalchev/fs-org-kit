#!/usr/bin/env python3
"""
transfer-v1-check.py - reports source entries not yet transferred to the
target. See transfer-v1.toml for what moves, how the target is
templated, and the conflict policy.

Protocol (protocol_version 1.0, cross scope):
    python transfer-v1-check.py --paths <p> --paths <p> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import sys

from _shared import BadParams, fail, pending, read_settings

MAX_REPORTED = 8


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        # The runner never does this - it invokes transfer-v1-fix.py
        # directly. Rejecting it anyway keeps a runner bug from looking
        # like a rule that quietly declined to act.
        print("error: --fix belongs to transfer-v1-fix.py, not the checker", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.paths)
    except BadParams as e:
        return fail(str(e))

    entries = pending(settings)
    if not entries:
        print(json.dumps({"status": "ok"}))
        return 0

    names = [e.relative_to(settings.source).as_posix() for e in entries]
    shown = ", ".join(names[:MAX_REPORTED])
    if len(names) > MAX_REPORTED:
        shown += f", ... ({len(names) - MAX_REPORTED} more)"
    verb = {"move": "moved", "copy": "copied", "sync": "synced"}[settings.operation]
    print(json.dumps({
        "status": "violation",
        "message": f"{len(names)} item(s) not yet {verb} to {settings.target}: {shown}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
