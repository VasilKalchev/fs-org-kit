#!/usr/bin/env python3
"""
basename-sync-v1-fix.py - for every stem that violates `mode` (see
basename-sync-v1.toml), invokes the user-provided `fixer_script` once,
passing it that stem's situation. This rule never touches a file itself -
converting, deleting, moving, or anything else is entirely up to the
user's own script.

Protocol (protocol_version 1.0, cross scope, fix mode):
    python basename-sync-v1-fix.py --paths <p1> --paths <p2> [...] --params '<json>' --fix

For each violating stem, fixer_script is invoked as:
    <fixer_script> --mode <mode> --stem <stem> --present '<json>' --missing '<json>'
where --present is {root: [extension, ...]} for every given path that HAS
this stem, and --missing is a JSON list of given paths that don't (always
[] in exclusive mode). Exit code 0 = that stem is now handled; nonzero =
it wasn't.

stdout: exactly one JSON line -
    {"status": "ok"}
    {"status": "fixed", "message": "..."}       - every violation resolved
    {"status": "violation", "message": "..."}   - some resolved, some not
    {"status": "unfixable", "message": "..."}   - fixer_script not configured
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import json
import subprocess
import sys
from pathlib import Path

from _shared import find_violations, normalize_extensions

USER_SCRIPT_TIMEOUT_SECONDS = 300.0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--paths", action="append", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if not args.fix:
        print("error: basename-sync-v1-fix.py should only ever be invoked with --fix", file=sys.stderr)
        return 1

    if len(args.paths) < 2:
        print(f"error: scope=cross needs 2 or more --paths, got {len(args.paths)}", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    mode = params.get("mode")
    if mode not in ("shared", "exclusive"):
        print(f"error: mode must be 'shared' or 'exclusive', got {mode!r}", file=sys.stderr)
        return 1

    recursive = params.get("recursive", True)
    allowed_extensions = normalize_extensions(params.get("extensions", []))
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    fixer_script = params.get("fixer_script", "")

    roots = [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1

    violations = find_violations(roots, recursive, allowed_extensions, exclude_globs, mode)

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    if not fixer_script:
        print(json.dumps({
            "status": "unfixable",
            "message": f"{len(violations)} stem(s) violate the standard, but no fixer_script is configured for this attachment",
        }))
        return 0

    fixer_path = Path(fixer_script)
    if not fixer_path.exists():
        print(f"error: fixer_script does not exist: {fixer_path}", file=sys.stderr)
        return 1

    resolved, failed = [], []

    for stem in sorted(violations.keys()):
        info = violations[stem]
        argv = [
            str(fixer_path),
            "--mode", mode,
            "--stem", stem,
            "--present", json.dumps(info["present"]),
            "--missing", json.dumps(info["missing"]),
        ]
        try:
            result = subprocess.run(argv, capture_output=True, text=True, timeout=USER_SCRIPT_TIMEOUT_SECONDS)
        except subprocess.TimeoutExpired:
            failed.append(f"{stem} (fixer_script timed out after {USER_SCRIPT_TIMEOUT_SECONDS:.0f}s)")
            continue
        except OSError as e:
            failed.append(f"{stem} (failed to launch fixer_script: {e})")
            continue

        if result.returncode == 0:
            resolved.append(stem)
        else:
            reason = result.stderr.strip() or f"exited {result.returncode}"
            failed.append(f"{stem} ({reason})")

    if not failed:
        message = f"{len(resolved)} stem(s) resolved via fixer_script"
        print(json.dumps({"status": "fixed", "message": message}))
        return 0

    shown = failed[:10]
    more = f", and {len(failed) - 10} more" if len(failed) > 10 else ""
    message = (
        f"{len(resolved)} of {len(violations)} stem(s) resolved via fixer_script; "
        f"{len(failed)} still unresolved: {', '.join(shown)}{more}"
    )
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
