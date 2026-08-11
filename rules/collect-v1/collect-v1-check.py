#!/usr/bin/env python3
"""
collect-v1-check.py - reports everything sitting in a path that should
have been swept into the target. See collect-v1.toml for what moves, how
the target is templated, and the conflict policy.

Protocol (protocol_version 1.0, single scope):
    python collect-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import sys

from _shared import BadParams, fail, read_settings, selected_for

MAX_REPORTED = 8


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        # The runner never does this - it invokes collect-v1-fix.py
        # directly. Rejecting it anyway keeps a runner bug from looking
        # like a rule that quietly declined to move anything.
        print("error: --fix belongs to collect-v1-fix.py, not the checker", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    entries = selected_for(settings)
    if not entries:
        print(json.dumps({"status": "ok"}))
        return 0

    names = [e.relative_to(settings.source).as_posix() for e in entries]
    shown = ", ".join(names[:MAX_REPORTED])
    if len(names) > MAX_REPORTED:
        shown += f", ... ({len(names) - MAX_REPORTED} more)"
    print(json.dumps({
        "status": "violation",
        "message": f"{len(names)} item(s) to collect into {settings.target}: {shown}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
