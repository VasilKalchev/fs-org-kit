#!/usr/bin/env python3
"""
xdg-auto-folder-icon-v1-check.py - reports folders whose icon doesn't match
what their name or contents say it should be. See xdg-auto-folder-icon-v1.toml
for the condition vocabulary and why {color} is never taken away.

Protocol (protocol_version 1.0, single scope):
    python xdg-auto-folder-icon-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import sys

from _shared import BadParams, evaluate, fail, read_settings, summarize



def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: --fix belongs to xdg-auto-folder-icon-v1-fix.py, not the checker", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    findings = evaluate(settings)
    if not findings:
        print(json.dumps({"status": "ok"}))
        return 0

    described = [f"{rel} ({current or 'no icon'} -> {desired})" for rel, current, desired in findings]
    shown = summarize(described)
    print(json.dumps({
        "status": "violation",
        "message": f"{len(findings)} folder(s) don't have the icon their name or contents call for: {shown}",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
