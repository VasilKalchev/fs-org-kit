"""
Selection logic shared by collect-v1's checker and fixer.

The two scripts have to agree exactly on what would move: the checker
reports it and the fixer acts on it, and a disagreement between them
would mean the fixer moving something the report never mentioned. Kept
in one module rather than duplicated for that reason - both scripts are
in this directory, so the import resolves whether they're run standalone
or through the runner.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

DURATION_PATTERN = re.compile(r"^(\d+)\s*([dwm])$")
# Matches this project's established duration vocabulary (see
# rule.template.toml): <n><unit>, no space, d/w/m.
DURATION_SECONDS = {"d": 86400, "w": 604800, "m": 2592000}

CONFLICT_MODES = ("rename", "skip", "fail")


def parse_duration(value: str) -> int:
    m = DURATION_PATTERN.match(str(value).strip())
    if not m:
        raise ValueError(f"not a recognized duration (expected e.g. '3d', '2w', '1m'): {value!r}")
    number, unit = m.groups()
    return int(number) * DURATION_SECONDS[unit]


def resolve_target(target: str, source: Path, now: float | None = None) -> Path:
    """The destination for this sweep. strftime placeholders are expanded
    against the current time, so a dated target names a different folder
    each day; {name} is the swept folder's own basename, which lets one
    attachment serve several paths."""
    stamp = time.localtime(now if now is not None else time.time())
    rendered = time.strftime(target.replace("{name}", source.name), stamp)
    path = Path(rendered).expanduser()
    return path if path.is_absolute() else (source / path)


def matches_any(name: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(name, g) for g in globs)


@dataclass
class Settings:
    source: Path
    target: Path
    keep: list
    move: list
    recursive: bool
    min_age_seconds: int
    on_conflict: str
    create_target: bool


class BadParams(Exception):
    """A problem with the attachment, not with the filesystem - both
    scripts exit nonzero with the reason on stderr, which the runner
    reports as `broken` rather than as a violation."""


def read_settings(raw_params: str, path: str) -> Settings:
    """Parse and validate one attachment. Shared so the checker and fixer
    reject exactly the same attachments for exactly the same reasons -
    the fixer acting on an attachment the checker refused would be a
    silent divergence between what's reported and what's done."""
    try:
        params = json.loads(raw_params)
    except json.JSONDecodeError as e:
        raise BadParams(f"--params is not valid JSON: {e}")

    source = Path(path)
    if not source.is_dir():
        raise BadParams(f"--path is not a directory: {source}")

    target_spec = params.get("target", "")
    if not isinstance(target_spec, str) or not target_spec:
        raise BadParams("target is required - a sweep with a guessed destination can't be undone")

    keep, move = params.get("keep", []), params.get("move", [])
    for name, value in (("keep", keep), ("move", move)):
        if not isinstance(value, list):
            raise BadParams(f"{name} must be a list of glob strings")

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
        raise BadParams(f"target resolves to the path being swept ({source}) - nothing could move")

    return Settings(
        source=source, target=target, keep=keep, move=move,
        recursive=bool(params.get("recursive", False)),
        min_age_seconds=min_age_seconds, on_conflict=on_conflict,
        create_target=bool(params.get("create_target", True)),
    )


def selected_for(settings: Settings) -> list[Path]:
    return select_entries(
        settings.source, settings.target, settings.keep, settings.move,
        settings.recursive, settings.min_age_seconds,
    )


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def select_entries(
    source: Path,
    target: Path,
    keep: list,
    move: list,
    recursive: bool,
    min_age_seconds: int,
    now: float | None = None,
) -> list[Path]:
    """Everything that should be swept, in a stable order.

    `move`, when non-empty, inverts the default from "everything" to
    "only these"; `keep` subtracts either way. Anything at or under the
    target is skipped so a target living inside the swept path can't
    sweep itself.
    """
    now = time.time() if now is None else now
    resolved_target = target.resolve() if target.exists() else target
    selected: list[Path] = []

    def is_target(candidate: Path) -> bool:
        probe = candidate.resolve() if candidate.exists() else candidate
        return probe == resolved_target or resolved_target.is_relative_to(probe)

    def consider(item: Path) -> None:
        name = item.name
        if move and not matches_any(name, move):
            return
        if keep and matches_any(name, keep):
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
            if is_target(child):
                continue
            if recursive and child.is_dir() and not child.is_symlink():
                walk(child)
            else:
                consider(child)

    walk(source)
    return selected


def destination_for(entry: Path, target: Path, on_conflict: str) -> Path | None:
    """Where one entry lands, or None when it should be skipped.

    Nothing is ever overwritten under any setting - this rule moves
    things the standard called unimportant enough to sweep, which is
    exactly when destroying an older copy of the same name would go
    unnoticed.
    """
    candidate = target / entry.name
    if not candidate.exists() and not candidate.is_symlink():
        return candidate
    if on_conflict == "skip":
        return None
    if on_conflict == "fail":
        raise FileExistsError(str(candidate))
    stem, suffix = entry.stem, entry.suffix
    for n in range(2, 1000):
        candidate = target / f"{stem}-{n}{suffix}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise FileExistsError(f"{target / entry.name} (and 998 numbered alternatives)")
