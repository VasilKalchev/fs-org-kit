#!/usr/bin/env python3
"""
link-policy-v1-check.py - constrains which kinds of entry may appear
under a path. See link-policy-v1.toml for the arrangement this exists
for, why classification is link-first, and why there's no fixer.

Protocol (protocol_version 1.0, single scope):
    python link-policy-v1-check.py --path <dir> --params '<json>'

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

POLICIES = ("allowed", "forbidden", "required")
KINDS = ("files", "folders", "links")

# Same vocabulary as link-integrity-v1, so "what counts as a link" means
# the same thing in both rules. A rule is a standalone script and can't
# import from a sibling.
LINK_KINDS = ("symlink", "desktop", "shortcut", "webloc")
LINK_SUFFIXES = {".desktop": "desktop", ".lnk": "shortcut", ".url": "shortcut",
                 ".webloc": "webloc", ".alias": "webloc"}

MAX_REPORTED = 8


def is_excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def classify(item: Path, link_kinds: set) -> str:
    """"links", "folders", or "files" - link-first, so a .desktop entry is
    a link rather than the file it also is. See the manifest."""
    if item.is_symlink():
        return "links" if "symlink" in link_kinds else "files"
    if LINK_SUFFIXES.get(item.suffix.lower()) in link_kinds:
        return "links"
    return "folders" if item.is_dir() else "files"


def scan(root: Path, base: Path, recursive: bool, exclude: list, link_kinds: set,
         found: dict) -> None:
    try:
        children = sorted(root.iterdir())
    except OSError:
        return
    for child in children:
        rel = child.relative_to(base).as_posix()
        if is_excluded(rel, exclude):
            continue
        kind = classify(child, link_kinds)
        found[kind].append(rel)
        # Only a real directory is descended into. A symlink to one is a
        # link here, and following it would both leave the scope and risk
        # looping through a link to an ancestor.
        if kind == "folders" and recursive:
            scan(child, base, recursive, exclude, link_kinds, found)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: link-policy-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    policies = {kind: params.get(kind, "allowed") for kind in KINDS}
    for kind, policy in policies.items():
        if policy not in POLICIES:
            print(f"error: {kind} must be one of {list(POLICIES)}, got {policy!r}", file=sys.stderr)
            return 1

    link_kinds = params.get("link_kinds", list(LINK_KINDS))
    recursive = bool(params.get("recursive", False))
    exclude = params.get("exclude", [])

    if not isinstance(link_kinds, list):
        print("error: link_kinds must be a list", file=sys.stderr)
        return 1
    unknown = [k for k in link_kinds if k not in LINK_KINDS]
    if unknown:
        print(f"error: unknown link kind(s) {unknown}; known: {list(LINK_KINDS)}", file=sys.stderr)
        return 1
    if not isinstance(exclude, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1
    if all(policy == "allowed" for policy in policies.values()):
        # Nothing is constrained, so this attachment can only ever report
        # ok. Saying so beats a green result nobody asked a question for.
        print("error: files, folders and links are all 'allowed' - this attachment constrains nothing",
              file=sys.stderr)
        return 1
    if policies["links"] != "allowed" and not link_kinds:
        print("error: a policy is set on links, but link_kinds is empty - nothing would ever count as one",
              file=sys.stderr)
        return 1

    found: dict[str, list[str]] = {kind: [] for kind in KINDS}
    scan(root, root, recursive, exclude, set(link_kinds), found)

    problems: list[str] = []
    for kind in KINDS:
        entries = found[kind]
        if policies[kind] == "forbidden" and entries:
            shown = ", ".join(entries[:MAX_REPORTED])
            if len(entries) > MAX_REPORTED:
                shown += f", ... ({len(entries) - MAX_REPORTED} more)"
            problems.append(f"{len(entries)} {kind} present but forbidden: {shown}")
        elif policies[kind] == "required" and not entries:
            problems.append(f"no {kind} found, but {kind} are required here")

    if not problems:
        print(json.dumps({"status": "ok"}))
        return 0
    print(json.dumps({"status": "violation", "message": "; ".join(problems)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
