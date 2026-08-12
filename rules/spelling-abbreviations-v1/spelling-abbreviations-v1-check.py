#!/usr/bin/env python3
"""
spelling-abbreviations-v1-check.py - checks that words in file/folder
names are either correctly spelled or a known abbreviation. See
spelling-abbreviations-v1.toml for the full param documentation.

Requires the pyspellchecker package (pip install pyspellchecker).

Protocol (protocol_version 1.0, single scope):
    python spelling-abbreviations-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path

WORD_SPLIT = re.compile(r"[-_\s]+")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: spelling-abbreviations-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        from spellchecker import SpellChecker
    except ImportError:
        print("error: pyspellchecker isn't installed - run: pip install pyspellchecker", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    # Either a literal list of abbreviations, or the standard's whole
    # [abbreviations] table handed over by a {ref = "..."} - iterating
    # the table yields its keys, which is what this needs; the meanings
    # beside them are documentation and ignored here.
    abbreviations = {a.lower() for a in params.get("abbreviations", [])}
    ignore = {w.lower() for w in params.get("ignore", [])}
    languages = params.get("languages", ["en"])
    if not isinstance(languages, list) or not languages:
        print("error: languages must be a non-empty list of language codes", file=sys.stderr)
        return 1
    min_word_length = params.get("min_word_length", 3)
    numbers_ok = params.get("numbers_ok", True)
    target = params.get("target", "both")
    if target not in ("files", "folders", "both"):
        print(f"error: target must be 'files', 'folders', or 'both', got {target!r}", file=sys.stderr)
        return 1
    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    spellcheckers = []
    for language in languages:
        try:
            spellcheckers.append(SpellChecker(language=language))
        except Exception as e:
            print(f"error: could not initialize spell checker for language {language!r}: {e}", file=sys.stderr)
            return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    items = root.rglob("*") if recursive else root.glob("*")
    violations = []
    for item in items:
        is_dir = item.is_dir()
        if is_dir and target == "files":
            continue
        if not is_dir and target == "folders":
            continue

        rel = item.relative_to(root).as_posix()
        if any(fnmatch.fnmatch(rel, p) for p in exclude_globs):
            continue

        name_to_split = item.name if is_dir else item.stem
        words = [w for w in WORD_SPLIT.split(name_to_split) if w]

        candidates = []
        for w in words:
            if len(w) < min_word_length:
                continue
            if numbers_ok and w.isdigit():
                continue
            wl = w.lower()
            if wl in abbreviations or wl in ignore:
                continue
            candidates.append(w)

        if not candidates:
            continue

        lowered = [c.lower() for c in candidates]
        unknown_sets = [spell.unknown(lowered) for spell in spellcheckers]
        misspelled = set.intersection(*unknown_sets)
        if misspelled:
            violations.append((rel, sorted(misspelled)))

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    violations.sort(key=lambda v: v[0])
    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    parts = [f"{rel} ({', '.join(words)})" for rel, words in shown]
    message = f"{len(violations)} item(s) with unrecognized word(s): {', '.join(parts)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
