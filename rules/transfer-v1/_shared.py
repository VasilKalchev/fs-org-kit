"""
Selection and transfer logic shared by transfer-v1's checker and fixer.

The two scripts have to agree exactly on what would move: the checker
reports it and the fixer acts on it, and a disagreement between them
would mean the fixer touching something the report never mentioned.
Kept in one module rather than duplicated for that reason - both
scripts are in this directory, so the import resolves whether they run
standalone or through the runner.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DURATION_PATTERN = re.compile(r"^(\d+)\s*([dwm])$")
# Matches this project's established duration vocabulary: <n><unit>, no
# space, d/w/m.
DURATION_SECONDS = {"d": 86400, "w": 604800, "m": 2592000}

OPERATIONS = ("move", "copy", "sync")
DIRECTIONS = ("forward", "reverse")
CONFLICT_MODES = ("rename", "skip", "fail")
VERB_PAST = {"move": "moved", "copy": "copied", "sync": "synced"}

MAX_REPORTED = 8


def parse_duration(value: str) -> int:
    m = DURATION_PATTERN.match(str(value).strip())
    if not m:
        raise ValueError(f"not a recognized duration (expected e.g. '3d', '2w', '1m'): {value!r}")
    number, unit = m.groups()
    return int(number) * DURATION_SECONDS[unit]


def resolve_target(raw: str, source: Path, now: float | None = None) -> Path:
    """The transfer's destination. The runner has already turned the
    declared catalog path into an absolute string (expanding `~`,
    resolving it against root) - what's left here is strftime, so a
    dated target names a different folder each day, and `{name}`, the
    source's own basename, for one attachment reused across several
    `paths.cross` blocks."""
    stamp = time.localtime(now if now is not None else time.time())
    rendered = time.strftime(raw.replace("{name}", source.name), stamp)
    return Path(rendered)


def matches_any(name: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


@dataclass
class Settings:
    source: Path
    target: Path
    operation: str
    exclude: list
    recursive: bool
    min_age_seconds: int
    on_conflict: str
    create_target: bool


class BadParams(Exception):
    """A problem with the attachment, not with the filesystem - both
    scripts exit nonzero with the reason on stderr, which the runner
    reports as `broken` rather than as a violation."""


def read_settings(raw_params: str, paths: list[str]) -> Settings:
    """Parse and validate one attachment. Shared so the checker and
    fixer reject exactly the same attachments for exactly the same
    reasons."""
    try:
        params = json.loads(raw_params)
    except json.JSONDecodeError as e:
        raise BadParams(f"--params is not valid JSON: {e}")

    if len(paths) != 2:
        raise BadParams(f"transfer-v1 is a cross-scope rule and needs exactly 2 paths, got {len(paths)}")

    operation = params.get("operation")
    if operation not in OPERATIONS:
        raise BadParams(f"operation must be one of {list(OPERATIONS)}, got {operation!r}")

    direction = params.get("direction")
    if direction not in DIRECTIONS:
        raise BadParams(f"direction must be one of {list(DIRECTIONS)}, got {direction!r}")

    source_spec, target_spec = paths if direction == "forward" else list(reversed(paths))

    source = Path(source_spec)
    if not source.is_dir():
        raise BadParams(f"source is not a directory: {source}")

    exclude = params.get("exclude", [])
    if not isinstance(exclude, list):
        raise BadParams("exclude must be a list of glob strings")

    on_conflict = params.get("on_conflict", "rename")
    if on_conflict not in CONFLICT_MODES:
        raise BadParams(f"on_conflict must be one of {list(CONFLICT_MODES)}, got {on_conflict!r}")

    min_age = params.get("min_age", "")
    try:
        min_age_seconds = parse_duration(min_age) if min_age else 0
    except ValueError as e:
        raise BadParams(str(e))

    try:
        target = resolve_target(target_spec, source)
    except (ValueError, OSError) as e:
        raise BadParams(f"target {target_spec!r} could not be resolved: {e}")

    if target == source:
        raise BadParams(f"source and target resolve to the same path ({source})")

    return Settings(
        source=source, target=target, operation=operation, exclude=exclude,
        recursive=bool(params.get("recursive", False)),
        min_age_seconds=min_age_seconds, on_conflict=on_conflict,
        create_target=bool(params.get("create_target", True)),
    )


def select_entries(
    source: Path,
    target: Path,
    exclude: list,
    recursive: bool,
    min_age_seconds: int,
    now: float | None = None,
) -> list[Path]:
    """Everything in source eligible to transfer, in a stable order.
    Anything at or under the target is skipped so a dated target that
    happens to sit inside the source it's fed from can't consume
    itself."""
    now = time.time() if now is None else now
    resolved_target = target.resolve() if target.exists() else target
    selected: list[Path] = []

    def is_target(candidate: Path, candidate_is_dir: bool) -> bool:
        # Only a directory can contain the target, so only a directory
        # needs the resolve() call that answers that - a plain path
        # comparison is enough to rule out a file.
        if not candidate_is_dir:
            return candidate == resolved_target
        probe = candidate.resolve() if candidate.exists() else candidate
        return probe == resolved_target or resolved_target.is_relative_to(probe)

    def consider(item: Path) -> None:
        if matches_any(item.name, exclude):
            return
        if min_age_seconds:
            try:
                if now - item.lstat().st_mtime < min_age_seconds:
                    return
            except OSError:
                return
        selected.append(item)

    def walk(folder: Path) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            child_is_dir = child.is_dir()
            if is_target(child, child_is_dir):
                continue
            if recursive and child_is_dir and not child.is_symlink():
                walk(child)
            else:
                consider(child)

    walk(source)
    return selected


def already_at_target(entry: Path, target: Path) -> bool:
    """Whether an entry of this name already exists at the target - the
    only question "copy" and "sync" ask before deciding an entry is
    still outstanding. Matched by name only, same as basename-sync-v1;
    this rule doesn't diff content."""
    return os.path.lexists(target / entry.name)


def pending(settings: Settings) -> list[Path]:
    """Entries still outstanding - what the checker reports and the
    fixer acts on.

    "move" reports every selected entry regardless of the target: the
    point of a move is that source ends up without it, so its continued
    presence in source is itself the violation. "copy" and "sync" only
    report an entry the target doesn't have yet - once it's there,
    source is *supposed* to still hold its own copy, so that isn't
    evidence anything is still outstanding."""
    entries = select_entries(
        settings.source, settings.target, settings.exclude,
        settings.recursive, settings.min_age_seconds,
    )
    if settings.operation == "move":
        return entries
    return [e for e in entries if not already_at_target(e, settings.target)]


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def summarize(items: list, limit: int = MAX_REPORTED, total: int | None = None) -> str:
    """A comma-joined preview of a name list, truncated with a "+N more"
    tail - used in both the checker's and fixer's status messages.

    `total` overrides the "more" count for a caller that only built
    `items` up to `limit` in the first place (the checker doesn't stringify
    every pending entry just to report the first few)."""
    total = len(items) if total is None else total
    shown = ", ".join(items[:limit])
    return shown + (f", ... ({total - limit} more)" if total > limit else "")


def unfixable(message: str) -> int:
    print(json.dumps({"status": "unfixable", "message": message}))
    return 0


def destination_for(entry: Path, target: Path, on_conflict: str) -> Path | None:
    """Where one entry lands under "move" or "copy", or None when it
    should be skipped.

    Nothing is ever overwritten under any setting - this rule transfers
    things the standard said were fine to relocate or duplicate, which
    is exactly when silently destroying an existing copy would go
    unnoticed.
    """
    candidate = target / entry.name
    if not os.path.lexists(candidate):
        return candidate
    if on_conflict == "skip":
        return None
    if on_conflict == "fail":
        raise FileExistsError(str(candidate))
    stem, suffix = entry.stem, entry.suffix
    for n in range(2, 1000):
        candidate = target / f"{stem}-{n}{suffix}"
        if not os.path.lexists(candidate):
            return candidate
    raise FileExistsError(f"{target / entry.name} (and 998 numbered alternatives)")
