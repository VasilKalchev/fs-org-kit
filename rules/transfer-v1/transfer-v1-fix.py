#!/usr/bin/env python3
"""
transfer-v1-fix.py - moves, copies, or syncs everything the checker
would report. Self-contained per the protocol: it selects and transfers
in one pass rather than re-running the checker first.

Protocol (protocol_version 1.0, cross scope):
    python transfer-v1-fix.py --paths <p> --paths <p> --params '<json>' --fix

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "fixed", "message": "..."}
                               | {"status": "violation", "message": "..."}
                               | {"status": "unfixable", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why

`violation` here means some items transferred and others couldn't - a
partial run is reported as one, since the source still holds things the
standard says shouldn't still be there.
"""

import argparse
import json
import shutil
import sys

from _shared import (
    VERB_PAST,
    BadParams,
    already_at_target,
    copy_entry,
    destination_for,
    fail,
    move_entry,
    pending,
    read_settings,
    summarize,
    unfixable,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if not args.fix:
        # The runner always passes --fix to a fixer. Running without it
        # would otherwise transfer files while looking like a dry run.
        print("error: transfer-v1-fix.py must be invoked with --fix", file=sys.stderr)
        return 1

    try:
        settings = read_settings(args.params, args.paths)
    except BadParams as e:
        return fail(str(e))

    entries, shared = pending(settings)
    if not entries:
        print(json.dumps({"status": "ok"}))
        return 0

    if not settings.target.exists():
        if not settings.create_target:
            return unfixable(
                f"{len(entries)} item(s) pending, but {settings.target} "
                f"doesn't exist and create_target is false"
            )
        try:
            settings.target.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            return unfixable(f"{len(entries)} item(s) pending, but {settings.target} couldn't be created: {e}")
    elif not settings.target.is_dir():
        return unfixable(f"target {settings.target} exists and is not a directory")

    moved: list[str] = []
    skipped: list[str] = []
    failed: list[str] = []
    verb_past = VERB_PAST[settings.operation]

    for entry in entries:
        label = entry.relative_to(settings.source).as_posix()

        if settings.operation == "sync":
            # Re-checked here, not just at selection time: a self-
            # contained fixer doesn't trust its own snapshot against a
            # filesystem it's actively changing.
            if already_at_target(entry, settings.target, strict=entry.name in shared):
                continue
            # A name another selected entry already took (recursive only)
            # gets a numbered one - sync never overwrites either.
            try:
                destination = destination_for(entry, settings.target, "rename")
            except FileExistsError as e:
                failed.append(f"{label} ({e})")
                continue
        else:
            try:
                destination = destination_for(entry, settings.target, settings.on_conflict)
            except FileExistsError as e:
                # on_conflict = "fail": stop immediately rather than leave
                # a half-done transfer in a state the report doesn't
                # describe.
                return unfixable(
                    f"{label} already exists at the target ({e}) and on_conflict is 'fail'"
                    + (f"; {len(moved)} item(s) had already been {verb_past}" if moved else "")
                )
            if destination is None:
                skipped.append(label)
                continue

        try:
            if settings.operation == "move":
                move_entry(entry, destination)
            else:
                copy_entry(entry, destination)
            moved.append(label)
        except (OSError, shutil.Error) as e:
            failed.append(f"{label} ({e})")

    if moved and not skipped and not failed:
        print(json.dumps({
            "status": "fixed",
            "message": f"{len(moved)} item(s) {verb_past} to {settings.target}: {summarize(moved)}",
        }))
        return 0

    if not moved and not skipped and not failed:
        # Every remaining entry was "sync"'d away by the target already
        # having it by the time this ran.
        print(json.dumps({"status": "ok"}))
        return 0

    parts = []
    if moved:
        parts.append(f"{len(moved)} item(s) {verb_past} to {settings.target}")
    if skipped:
        parts.append(f"{len(skipped)} left in place - already present at the target: {summarize(skipped)}")
    if failed:
        parts.append(f"{len(failed)} could not be {verb_past}: {summarize(failed)}")
    print(json.dumps({"status": "violation", "message": "; ".join(parts)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
