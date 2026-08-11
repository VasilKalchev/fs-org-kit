#!/usr/bin/env python3
"""
collect-v1-fix.py - sweeps everything the checker would report into the
target. Self-contained per the protocol: it selects and moves in one
pass rather than re-running the checker first.

Protocol (protocol_version 1.0, single scope):
    python collect-v1-fix.py --path <dir> --params '<json>' --fix

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "fixed", "message": "..."}
                               | {"status": "violation", "message": "..."}
                               | {"status": "unfixable", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why

`violation` here means some items moved and others couldn't - a partial
sweep is reported as one, since the path still holds things the standard
says shouldn't be there.
"""

import argparse
import json
import shutil
import sys

from _shared import BadParams, destination_for, fail, read_settings, selected_for

MAX_REPORTED = 8


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
        # The runner always passes --fix to a fixer. Running without it
        # would otherwise move files while looking like a dry run.
        print("error: collect-v1-fix.py must be invoked with --fix", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.path)
    except BadParams as e:
        return fail(str(e))

    entries = selected_for(settings)
    if not entries:
        print(json.dumps({"status": "ok"}))
        return 0

    if not settings.target.exists():
        if not settings.create_target:
            print(json.dumps({
                "status": "unfixable",
                "message": f"{len(entries)} item(s) to collect, but {settings.target} "
                           f"doesn't exist and create_target is false",
            }))
            return 0
        try:
            settings.target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            print(json.dumps({
                "status": "unfixable",
                "message": f"{len(entries)} item(s) to collect, but {settings.target} couldn't be created: {e}",
            }))
            return 0
    elif not settings.target.is_dir():
        print(json.dumps({
            "status": "unfixable",
            "message": f"target {settings.target} exists and is not a directory",
        }))
        return 0

    moved: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []

    for entry in entries:
        label = entry.relative_to(settings.source).as_posix()
        try:
            destination = destination_for(entry, settings.target, settings.on_conflict)
        except FileExistsError as e:
            # on_conflict = "fail": stop immediately rather than leave a
            # half-swept folder in a state the report doesn't describe.
            print(json.dumps({
                "status": "unfixable",
                "message": f"{label} already exists at the target ({e}) and on_conflict is 'fail'"
                           + (f"; {len(moved)} item(s) had already moved" if moved else ""),
            }))
            return 0
        if destination is None:
            skipped.append(label)
            continue
        try:
            shutil.move(str(entry), str(destination))
            moved.append(label)
        except (OSError, shutil.Error) as e:
            failed.append(f"{label} ({e})")

    if moved and not skipped and not failed:
        print(json.dumps({
            "status": "fixed",
            "message": f"{len(moved)} item(s) collected into {settings.target}: {summarize(moved)}",
        }))
        return 0

    parts = []
    if moved:
        parts.append(f"{len(moved)} item(s) collected into {settings.target}")
    if skipped:
        parts.append(f"{len(skipped)} left in place - already present at the target: {summarize(skipped)}")
    if failed:
        parts.append(f"{len(failed)} could not be moved: {summarize(failed)}")
    print(json.dumps({"status": "violation", "message": "; ".join(parts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
