#!/usr/bin/env python3
"""
cache.py - the single source of truth for where rules keep cached state,
and the only tool that manages it.

Most rules are stateless: they read the filesystem, decide, and exit.
A few need to remember something between runs so they don't redo
expensive work (duplicate-files-v1 caches file hashes so unchanged
files aren't re-read every time).

A rule does NOT get to decide where that lives. It declares
`uses_cache = true` in its manifest, and the runner hands it a
ready-made directory via `--cache-dir` at invocation time. A rule that
doesn't declare it never receives the flag; a rule invoked without the
flag - standalone on the CLI, say - must run correctly without caching
at all. Caching is a service the core provides, not something a rule
arranges for itself.

That inversion is the whole point of this module. If every caching rule
resolved its own location, the core would have no inventory of what
exists, no way to report on it, and no way to clear it - and each rule
would carry its own copy of the per-platform path logic below, free to
disagree with the others. Instead there is one root, one layout, and one
place that knows both:

    <root>/rules/<rule-id>/        e.g. .../fs-org-kit/rules/duplicate-files-v1/

The per-rule subdirectory means this module can clear one rule's cache
without knowing anything about what that rule stores inside it, which is
exactly the boundary the runner<->script protocol draws everywhere else.

Location, in order of precedence:
    $FS_ORG_KIT_CACHE_DIR                  if set (tests, and manual override)
    $XDG_CACHE_HOME/fs-org-kit/            Linux/BSD, else ~/.cache/fs-org-kit/
    ~/Library/Caches/fs-org-kit/           macOS
    %LOCALAPPDATA%\\fs-org-kit\\             Windows

Cache directory, never the config directory and never inside the tree
being scanned: everything here is regenerable, so deleting it costs one
slow run and can never change a verdict. Config directories get backed
up, synced between machines, and sometimes committed to version
control, none of which should happen to a local file index - and this
project's whole premise is that stray files in a user's folders are a
problem.

Nothing deletes this automatically, including `pip uninstall`, which
removes only the files pip installed and has no post-uninstall hook.
Clearing it is a deliberate, always-safe act:

    python -m fs_org_kit.cache --list
    python -m fs_org_kit.cache --clear
    python -m fs_org_kit.cache --clear duplicate-files-v1
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from pathlib import Path

from fs_org_kit.discovery import RULE_DIR_PATTERN
from fs_org_kit.validator import use_utf8_output

ENV_OVERRIDE = "FS_ORG_KIT_CACHE_DIR"
APP_DIR_NAME = "fs-org-kit"
RULES_SUBDIR = "rules"


def cache_root() -> Path:
    """The base directory for everything this project caches."""
    override = os.environ.get(ENV_OVERRIDE)
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        base = os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local"
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / APP_DIR_NAME


def is_valid_rule_id(rule_id: str) -> bool:
    """A single `<name>-v<major>` path component - the only shape a
    rule's cache directory ever has (see fs_org_kit.discovery)."""
    return (
        bool(RULE_DIR_PATTERN.match(rule_id))
        and rule_id not in (".", "..")
        and "/" not in rule_id and "\\" not in rule_id
        and Path(rule_id).name == rule_id
        and not Path(rule_id).is_absolute()
    )


def rule_cache_dir(rule_id: str) -> Path:
    """Where one rule's cached state lives. Not created by this call -
    see ensure_rule_cache_dir."""
    return cache_root() / RULES_SUBDIR / rule_id


def ensure_rule_cache_dir(rule_id: str) -> Path | None:
    """Create and return a rule's cache directory, or None if it can't
    be created. None means "run without caching" - never an error: a
    read-only or full filesystem should cost speed, not correctness."""
    directory = rule_cache_dir(rule_id)
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError:
        return None
    return directory


# ---------------------------------------------------------------------
# Management
# ---------------------------------------------------------------------

def _directory_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def list_caches() -> list[tuple[str, Path, int]]:
    """(rule_id, directory, size in bytes) for every rule cache present,
    sorted by rule id. A rule that has never run has no directory and
    doesn't appear."""
    container = cache_root() / RULES_SUBDIR
    if not container.is_dir():
        return []
    found = []
    for child in sorted(container.iterdir()):
        if child.is_dir():
            found.append((child.name, child, _directory_size(child)))
    return found


def clear(rule_id: str | None = None) -> list[str]:
    """Delete one rule's cache, or every rule's cache when rule_id is
    None. Returns the rule ids actually removed.

    A rule id is a directory name, nothing else. Anything that would
    resolve elsewhere - "..", an absolute path, a name with a separator -
    is refused before any deletion: `container / "/home/me"` is
    `/home/me`, and this function ends in rmtree."""
    if rule_id is not None:
        if not is_valid_rule_id(rule_id):
            raise ValueError(f"not a rule id: {rule_id!r} (expected a name like duplicate-files-v1)")
        directory = rule_cache_dir(rule_id)
        if not directory.is_dir():
            return []
        shutil.rmtree(directory)
        return [rule_id]

    removed = [name for name, _, _ in list_caches()]
    container = cache_root() / RULES_SUBDIR
    if container.is_dir():
        shutil.rmtree(container)
    return removed


def _human(size: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="fs-org-cache",
        description="Inspect and clear the caches fs-org-kit rules keep between runs.",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--list", action="store_true",
                       help="show every rule cache present, and its size")
    group.add_argument("--clear", nargs="?", const="", metavar="RULE_ID",
                       help="delete one rule's cache, or all of them if no rule is named")
    group.add_argument("--path", action="store_true",
                       help="print the cache root and exit")
    args = parser.parse_args()
    use_utf8_output()

    if args.path:
        print(cache_root())
        return 0

    if args.clear is not None:
        target = args.clear or None
        try:
            removed = clear(target)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        if not removed:
            print(f"nothing cached for {target}" if target else "nothing cached")
        else:
            for name in removed:
                print(f"cleared {name}")
        return 0

    # --list, and the default with no flags
    caches = list_caches()
    print(f"cache root: {cache_root()}")
    if not caches:
        print("(nothing cached)")
        return 0
    width = max(len(name) for name, _, _ in caches)
    total = 0
    for name, _, size in caches:
        print(f"  {name:<{width}}  {_human(size):>9}")
        total += size
    print(f"  {'total':<{width}}  {_human(total):>9}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
