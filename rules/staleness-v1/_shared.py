"""
_shared.py - detection logic shared by staleness-v1-check.py and
staleness-v1-fix.py. Not a rule script itself (no -check.py/-fix.py
naming, so discovery.py never touches it).
"""

from __future__ import annotations

import re
import time
from pathlib import Path

DURATION_PATTERN = re.compile(r"^(\d+)([dwm])$")
DURATION_SECONDS = {"d": 86400, "w": 7 * 86400, "m": 30 * 86400}


def parse_duration(value: str) -> int:
    """'90d' -> seconds. Matches this project's established duration
    format: <n><unit>, no space, d/w/m."""
    m = DURATION_PATTERN.match(str(value).strip())
    if not m:
        raise ValueError(f"not a recognized duration (expected e.g. '90d', '2w', '3m'): {value!r}")
    number, unit = m.groups()
    return int(number) * DURATION_SECONDS[unit]


def resolve_destination(destination: str, root: Path, now: float | None = None) -> Path:
    """Where the fixer moves a violating item.

    strftime placeholders are expanded against the current time, so a
    dated destination names a different folder as time passes -
    "_arch/%Y" files each archived item under the year it was archived,
    which is what an archive "separated by year" actually needs. A value
    with no placeholder renders to itself, which is every attachment
    written before this was added.

    A relative value resolves against root's PARENT - root is the
    scanned folder, so a sibling archive is the common case. An absolute
    or `~`-relative value is used as-is, which is how you point the
    fixer at the OS trash folder instead of an archive."""
    stamp = time.localtime(now if now is not None else time.time())
    path = Path(time.strftime(destination, stamp)).expanduser()
    return path if path.is_absolute() else root.parent / path


def effective_timestamp(item: Path, basis: str) -> float:
    """The timestamp used to judge one direct child's staleness. A file
    uses its own timestamp. A folder uses the MOST RECENT timestamp
    among every file recursively inside it (a folder's own mtime often
    only reflects direct-listing changes, not deep edits) - falling
    back to the folder's own timestamp only if it's entirely empty."""
    stat_attr = "st_atime" if basis == "atime" else "st_mtime"

    if item.is_file():
        return getattr(item.stat(), stat_attr)

    newest = None
    for f in item.rglob("*"):
        if f.is_file():
            try:
                ts = getattr(f.stat(), stat_attr)
            except OSError:
                continue
            if newest is None or ts > newest:
                newest = ts
    if newest is not None:
        return newest
    return getattr(item.stat(), stat_attr)


def find_violations(root: Path, mode: str, threshold_seconds: int, basis: str, exclude_globs: list) -> list:
    """Returns [(item_path, age_seconds), ...] for every direct child of
    root that violates `mode` against `threshold_seconds`."""
    import fnmatch

    now = time.time()
    violations = []
    for item in sorted(root.iterdir()):
        if any(fnmatch.fnmatch(item.name, p) for p in exclude_globs):
            continue
        ts = effective_timestamp(item, basis)
        age = now - ts

        if mode == "stale" and age > threshold_seconds:
            violations.append((item, age))
        elif mode == "active" and age < threshold_seconds:
            violations.append((item, age))

    return violations


def format_age(seconds: float) -> str:
    days = seconds / 86400
    if days >= 1:
        return f"{days:.0f}d"
    return f"{seconds / 3600:.1f}h"
