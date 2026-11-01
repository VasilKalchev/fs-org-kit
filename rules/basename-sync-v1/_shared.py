"""
_shared.py - detection logic shared by basename-sync-v1-check.py and
basename-sync-v1-fix.py. Not a rule script itself (no -check.py/-fix.py
naming, so discovery.py never touches it) - just a sibling module the two
scripts in this directory both import, so the actual "what counts as a
violation" logic is defined in exactly one place. Both scripts remain
independently runnable and testable; this is local organization within
one rule's own directory, not a cross-rule framework.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path


def normalize_extensions(extensions: list) -> set:
    return {str(e).lower().lstrip(".") for e in extensions}


def extension_of(file: Path) -> str:
    suffix = file.suffix.lower()
    return suffix[1:] if suffix else "none"


def is_excluded(relative_posix: str, exclude_globs: list) -> bool:
    """Matched against the path relative to its root, or the bare name -
    the same reading every bundled rule's `exclude` has."""
    name = relative_posix.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(relative_posix, p) or fnmatch.fnmatch(name, p) for p in exclude_globs)


def scan_root(root: Path, recursive: bool, allowed_extensions: set, exclude_globs: list) -> dict:
    """Returns {stem: [extension, ...]} for one root. `stem` is the
    relative-path-minus-extension (posix-style) if recursive, or just the
    bare filename-minus-extension if not - matching only happens within
    the same folder structure position when recursive."""
    files = root.rglob("*") if recursive else root.glob("*")
    result: dict = {}
    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        if is_excluded(rel, exclude_globs):
            continue
        ext = extension_of(f)
        if allowed_extensions and ext not in allowed_extensions:
            continue
        stem = f.relative_to(root).with_suffix("").as_posix() if recursive else f.stem
        result.setdefault(stem, []).append(ext)
    return result


def find_violations(roots: list, recursive: bool, allowed_extensions: set, exclude_globs: list, mode: str) -> dict:
    """roots: list of Path. Returns {stem: {"present": {root_str: [ext, ...]}, "missing": [root_str, ...]}}
    - only stems that actually violate `mode` are included."""
    per_root = {str(r): scan_root(r, recursive, allowed_extensions, exclude_globs) for r in roots}
    all_stems = set()
    for stems in per_root.values():
        all_stems.update(stems.keys())

    violations: dict = {}
    root_strs = [str(r) for r in roots]

    for stem in sorted(all_stems):
        present = {rs: per_root[rs][stem] for rs in root_strs if stem in per_root[rs]}
        missing = [rs for rs in root_strs if rs not in present]

        if mode == "shared":
            if missing:
                violations[stem] = {"present": present, "missing": missing}
        elif mode == "exclusive":
            if len(present) >= 2:
                violations[stem] = {"present": present, "missing": []}

    return violations
