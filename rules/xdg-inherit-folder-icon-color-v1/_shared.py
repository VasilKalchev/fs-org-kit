"""
.directory reading and writing, shared by xdg-inherit-folder-icon-color-v1's
checker and fixer.

The two scripts must agree exactly on how an icon name decomposes and on
what the desired name is: the checker reports a mismatch and the fixer
resolves it, and any disagreement would mean the fixer writing something
the report never described. Both scripts are in this directory, so the
import resolves whether they run standalone or through the runner.

THE FILE

A folder's custom icon lives in a `.directory` file inside it, in
freedesktop desktop-entry format - a freedesktop.org standard:

    [Desktop Entry]
    Icon=folder-yellow-public

It doesn't work on Windows or macOS. The file may not exist at all, and
when it does it often carries other keys and other groups unrelated to
the icon - only `Icon=` under `[Desktop Entry]` is ever touched.

THE NAME

An icon name decomposes as <prefix>-<color>-<variant>, e.g.
folder-yellow-public: `prefix` says it's a folder icon, `color` is one of
the theme's colorways, `variant` is the overlay glyph. Any of the three
may be absent - "folder-yellow" has no variant, "folder" neither.

Splitting it this way is what lets color be inherited independently of
meaning: a child keeps saying what it is while taking on its parent's
color.
"""

from __future__ import annotations

import fnmatch
import json
import sys
from dataclasses import dataclass
from pathlib import Path

DIRECTORY_FILE = ".directory"
GROUP = "[Desktop Entry]"
ICON_KEY = "Icon"

# Breeze's folder colorways. Overridable per attachment via `colors`,
# since another icon theme may name them differently - the rule only
# needs to know which token in an icon name IS the color.
DEFAULT_COLORS = [
    "black", "blue", "brown", "cyan", "green", "grey",
    "magenta", "orange", "red", "violet", "yellow",
]


@dataclass(frozen=True)
class IconName:
    prefix: str
    color: str
    variant: str

    def render(self) -> str:
        return "-".join(part for part in (self.prefix, self.color, self.variant) if part)


def parse_icon(name: str, prefix: str, colors: list) -> IconName:
    """Decompose an icon name. A name that doesn't start with `prefix` is
    returned with an empty prefix and everything in `variant`, which is
    how an unmanaged icon (a custom or absolute-path one) stays
    recognizable as something not to take apart."""
    if not name:
        return IconName("", "", "")
    if name != prefix and not name.startswith(prefix + "-"):
        return IconName("", "", name)
    remainder = name[len(prefix):].lstrip("-")
    if not remainder:
        return IconName(prefix, "", "")
    head, _, tail = remainder.partition("-")
    if head in colors:
        return IconName(prefix, head, tail)
    return IconName(prefix, "", remainder)


def read_icon(folder: Path) -> str:
    """The Icon= value from this folder's .directory, or "" if there
    isn't one. Deliberately not configparser: desktop-entry values
    routinely contain '%', which configparser's interpolation rejects."""
    entry = folder / DIRECTORY_FILE
    try:
        text = entry.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    in_group = False
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            in_group = stripped == GROUP
            continue
        if not in_group or "=" not in stripped or stripped.startswith("#"):
            continue
        key, _, value = stripped.partition("=")
        if key.strip() == ICON_KEY:
            return value.strip()
    return ""


def write_icon(folder: Path, icon: str) -> None:
    """Set Icon= in this folder's .directory, leaving every other key and
    group intact. A .directory often carries sort order, view mode and a
    custom name that have nothing to do with icons, and rewriting the
    file wholesale would silently discard them."""
    entry = folder / DIRECTORY_FILE
    try:
        lines = entry.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []

    output: list[str] = []
    in_group = False
    replaced = False
    group_end = -1

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            if in_group and not replaced:
                group_end = len(output)
            in_group = stripped == GROUP
        elif in_group and "=" in stripped and stripped.partition("=")[0].strip() == ICON_KEY:
            output.append(f"{ICON_KEY}={icon}")
            replaced = True
            continue
        output.append(line)

    if not replaced:
        if GROUP not in (line.strip() for line in output):
            output = [GROUP, f"{ICON_KEY}={icon}"] + output
        elif group_end >= 0:
            output.insert(group_end, f"{ICON_KEY}={icon}")
        else:
            output.append(f"{ICON_KEY}={icon}")

    entry.write_text("\n".join(output) + "\n", encoding="utf-8")


def desired_icon(current: str, parent_color: str, prefix: str, colors: list) -> str:
    """What a child's icon should be: the parent's color, the child's own
    variant. That split is the point - a child keeps saying what it is
    while taking on its parent's color."""
    parsed = parse_icon(current, prefix, colors)
    variant = parsed.variant if parsed.prefix else ""
    return IconName(prefix, parent_color, variant).render()


ON_DIFFERENT = ("change", "warn", "ignore")

# What one child folder needs, if anything.
SET, RECOLOR, WARN, UNMANAGED = "set", "recolor", "warn", "unmanaged"


@dataclass
class Settings:
    root: Path
    parent_color: str
    colors: list
    prefix: str
    on_different_color: str
    recursive: bool
    exclude: list
    skip_unset: bool


class BadParams(Exception):
    """A problem with the attachment, not the filesystem - both scripts
    exit nonzero with the reason on stderr, which the runner reports as
    `broken` rather than as a violation."""


def read_settings(raw_params: str, path: str) -> Settings:
    """Parse and validate one attachment. Shared so the checker and fixer
    refuse exactly the same attachments - a fixer acting on one the
    checker rejected would write something never reported."""
    try:
        params = json.loads(raw_params)
    except json.JSONDecodeError as e:
        raise BadParams(f"--params is not valid JSON: {e}")

    root = Path(path)
    if not root.is_dir():
        raise BadParams(f"--path is not a directory: {root}")

    colors = params.get("colors", DEFAULT_COLORS)
    if not isinstance(colors, list) or not all(isinstance(c, str) for c in colors) or not colors:
        raise BadParams("colors must be a non-empty list of strings")

    prefix = params.get("icon_prefix", "folder")
    if not isinstance(prefix, str) or not prefix:
        raise BadParams("icon_prefix must be a non-empty string")

    on_different = params.get("on_different_color", "change")
    if on_different not in ON_DIFFERENT:
        raise BadParams(f"on_different_color must be one of {list(ON_DIFFERENT)}, got {on_different!r}")

    exclude = params.get("exclude", [])
    if not isinstance(exclude, list):
        raise BadParams("exclude must be a list of glob strings")

    color = params.get("color", "")
    if not isinstance(color, str):
        raise BadParams("color must be a string")
    if color and color not in colors:
        raise BadParams(f"color {color!r} is not in colors {colors}")
    if not color:
        color = parse_icon(read_icon(root), prefix, colors).color

    return Settings(
        root=root, parent_color=color, colors=colors, prefix=prefix,
        on_different_color=on_different, recursive=bool(params.get("recursive", False)),
        exclude=exclude, skip_unset=bool(params.get("skip_unset", False)),
    )


def evaluate(settings: Settings) -> list[tuple[str, str, str, str]]:
    """(action, relative path, current icon, desired icon) per child that
    isn't already correct."""
    findings = []
    for folder in child_folders(settings.root, settings.recursive, settings.exclude):
        rel = folder.relative_to(settings.root).as_posix()
        current = read_icon(folder)
        parsed = parse_icon(current, settings.prefix, settings.colors)

        if current and not parsed.prefix:
            # A custom or absolute-path icon. Recoloring it would compose
            # a name from a variant that was never a variant, throwing
            # away whatever was deliberately set - so it is only ever
            # reported, never rewritten.
            findings.append((UNMANAGED, rel, current, ""))
            continue
        if not current:
            if not settings.skip_unset:
                findings.append((SET, rel, "", IconName(settings.prefix, settings.parent_color, "").render()))
            continue
        if parsed.color == settings.parent_color:
            continue
        if settings.on_different_color == "ignore":
            continue
        action = RECOLOR if settings.on_different_color == "change" else WARN
        findings.append((action, rel, current, desired_icon(current, settings.parent_color, settings.prefix, settings.colors)))
    return findings


# Reporting/exclusion helpers shared by this rule's checker and fixer.
# They live here rather than in each script because both need them
# identically, and `excluded` was previously passed into evaluate() as a
# callback from the very modules that should be importing it.
MAX_REPORTED = 8


def excluded(rel_path: str, globs: list) -> bool:
    """A folder is excluded when its path relative to root matches a
    glob, or when its bare name does - so "*.git" catches one at any
    depth without a "**/" prefix."""
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def summarize(items: list, limit: int = MAX_REPORTED) -> str:
    shown = ", ".join(items[:limit])
    return shown + (f", ... ({len(items) - limit} more)" if len(items) > limit else "")


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1


def child_folders(root: Path, recursive: bool, exclude: list) -> list[Path]:
    """Real subdirectories, in a stable order. Symlinks are not followed:
    a link's target is somewhere else, and writing a .directory into it
    would change a folder outside the tree being governed."""
    found: list[Path] = []

    def walk(folder: Path) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            if excluded(child.relative_to(root).as_posix(), exclude):
                continue
            found.append(child)
            if recursive:
                walk(child)

    walk(root)
    return found
