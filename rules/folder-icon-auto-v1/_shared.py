"""
Matching and .directory handling shared by folder-icon-auto-v1's checker
and fixer.

The checker reports which icon a folder should get and the fixer writes
it; any disagreement between them would mean writing something the
report never described, so the decision lives in one place. Both scripts
sit in this directory, so the import resolves whether they run standalone
or through the runner.

The .directory reading and writing here is deliberately a copy of
folder-icon-inherit-v1's, not a shared import: a rule is a standalone
unit that has to keep working when copied into someone's rules.own/, and
one rule reaching into another's directory would break the moment either
moved. The icon-name grammar is identical on purpose - the two rules are
meant to be attached to the same tree and compose in either order.
"""

from __future__ import annotations

import fnmatch
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

DIRECTORY_FILE = ".directory"
GROUP = "[Desktop Entry]"
ICON_KEY = "Icon"
COLOR_PLACEHOLDER = "{color}"

DEFAULT_COLORS = [
    "black", "blue", "brown", "cyan", "green", "grey",
    "magenta", "orange", "red", "violet", "yellow",
]

CONDITION_KEYS = ("name", "contains", "contains_any", "ratio", "empty")


class BadParams(Exception):
    """A problem with the attachment, not the filesystem - both scripts
    exit nonzero with the reason on stderr, which the runner reports as
    `broken` rather than as a violation."""


@dataclass
class Matcher:
    icon: str
    name: re.Pattern | None = None
    contains: list = field(default_factory=list)
    contains_any: list = field(default_factory=list)
    ratio: float = 0.0
    empty: bool | None = None


@dataclass
class Settings:
    root: Path
    matchers: list
    default_color: str
    colors: list
    prefix: str
    recursive: bool
    exclude: list


def parse_color(icon: str, prefix: str, colors: list) -> str:
    """The color token in an existing icon name, or "" when it has none.
    Same grammar as folder-icon-inherit-v1: <prefix>-<color>-<variant>."""
    if not icon or (icon != prefix and not icon.startswith(prefix + "-")):
        return ""
    remainder = icon[len(prefix):].lstrip("-")
    head = remainder.partition("-")[0]
    return head if head in colors else ""


def read_icon(folder: Path) -> str:
    """The Icon= value from this folder's .directory, or "". Deliberately
    not configparser - desktop-entry values routinely contain '%', which
    its interpolation rejects."""
    try:
        text = (folder / DIRECTORY_FILE).read_text(encoding="utf-8", errors="replace")
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
    """Set Icon= while leaving every other key and group intact - a
    .directory often carries sort order, view mode and a custom name that
    have nothing to do with icons."""
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


def build_matchers(raw: object) -> list:
    if not isinstance(raw, list) or not raw:
        raise BadParams("match must be a non-empty list of tables")
    matchers = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            raise BadParams(f"match[{i}] must be a table")
        icon = item.get("icon", "")
        if not isinstance(icon, str) or not icon:
            raise BadParams(f"match[{i}] needs a non-empty `icon`")
        unknown = [k for k in item if k not in CONDITION_KEYS and k != "icon"]
        if unknown:
            raise BadParams(f"match[{i}] has unknown key(s) {unknown}; known: {list(CONDITION_KEYS)}")
        if not any(k in item for k in CONDITION_KEYS):
            # An entry with no condition matches everything from wherever
            # it sits in the list, which is never what was meant.
            raise BadParams(f"match[{i}] has no condition - it would match every folder")

        pattern = None
        if "name" in item:
            try:
                pattern = re.compile(item["name"])
            except (re.error, TypeError) as e:
                raise BadParams(f"match[{i}].name is not a valid regex: {e}")

        for key in ("contains", "contains_any"):
            if key in item and (not isinstance(item[key], list) or not all(isinstance(g, str) for g in item[key])):
                raise BadParams(f"match[{i}].{key} must be a list of glob strings")

        ratio = item.get("ratio", 0.0)
        if not isinstance(ratio, (int, float)) or isinstance(ratio, bool) or not 0.0 <= ratio <= 1.0:
            raise BadParams(f"match[{i}].ratio must be a number between 0 and 1")
        if ratio and not item.get("contains_any"):
            raise BadParams(f"match[{i}].ratio needs contains_any - there'd be nothing to take a fraction of")

        empty = item.get("empty")
        if empty is not None and not isinstance(empty, bool):
            raise BadParams(f"match[{i}].empty must be true or false")

        matchers.append(Matcher(
            icon=icon, name=pattern,
            contains=list(item.get("contains", [])),
            contains_any=list(item.get("contains_any", [])),
            ratio=float(ratio), empty=empty,
        ))
    return matchers


def read_settings(raw_params: str, path: str) -> Settings:
    try:
        params = json.loads(raw_params)
    except json.JSONDecodeError as e:
        raise BadParams(f"--params is not valid JSON: {e}")

    root = Path(path)
    if not root.is_dir():
        raise BadParams(f"--path is not a directory: {root}")

    colors = params.get("colors", DEFAULT_COLORS)
    if not isinstance(colors, list) or not colors or not all(isinstance(c, str) for c in colors):
        raise BadParams("colors must be a non-empty list of strings")

    prefix = params.get("icon_prefix", "folder")
    if not isinstance(prefix, str) or not prefix:
        raise BadParams("icon_prefix must be a non-empty string")

    default_color = params.get("default_color", "blue")
    if not isinstance(default_color, str) or default_color not in colors:
        raise BadParams(f"default_color {default_color!r} is not in colors {colors}")

    exclude = params.get("exclude", [])
    if not isinstance(exclude, list):
        raise BadParams("exclude must be a list of glob strings")

    return Settings(
        root=root, matchers=build_matchers(params.get("match")),
        default_color=default_color, colors=colors, prefix=prefix,
        recursive=bool(params.get("recursive", False)), exclude=exclude,
    )


def folder_matches(folder: Path, matcher: Matcher) -> bool:
    """Every condition in one entry must hold - they're ANDed. Only direct
    children are considered: recursing would let one stray file redefine
    a whole tree's icon, and would turn a cheap listing into a full walk."""
    if matcher.name is not None and not matcher.name.search(folder.name):
        return False

    needs_listing = matcher.contains or matcher.contains_any or matcher.empty is not None
    if not needs_listing:
        return True
    try:
        children = list(folder.iterdir())
    except OSError:
        return False
    names = [c.name for c in children]

    if matcher.empty is not None and matcher.empty != (not names):
        return False
    if any(not any(fnmatch.fnmatch(n, g) for n in names) for g in matcher.contains):
        return False
    if matcher.contains_any:
        hits = [n for n in names if any(fnmatch.fnmatch(n, g) for g in matcher.contains_any)]
        if not hits:
            return False
        if matcher.ratio:
            files = [c.name for c in children if c.is_file()]
            if not files or len(hits) / len(files) < matcher.ratio:
                return False
    return True


def resolve_icon(template: str, current: str, settings: Settings) -> str:
    """`{color}` becomes the color the folder already has, so this rule
    assigns meaning without disturbing an existing color scheme. Only a
    folder with no color falls back to default_color."""
    if COLOR_PLACEHOLDER not in template:
        return template
    color = parse_color(current, settings.prefix, settings.colors) or settings.default_color
    return template.replace(COLOR_PLACEHOLDER, color)


def evaluate(settings: Settings, excluded) -> list[tuple[str, str, str]]:
    """(relative path, current icon, desired icon) per folder whose icon
    doesn't already match what its first matching rule asks for."""
    findings = []

    def walk(folder: Path) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            if not child.is_dir() or child.is_symlink():
                continue
            rel = child.relative_to(settings.root).as_posix()
            if excluded(rel, settings.exclude):
                continue
            for matcher in settings.matchers:
                if not folder_matches(child, matcher):
                    continue
                current = read_icon(child)
                desired = resolve_icon(matcher.icon, current, settings)
                if current != desired:
                    findings.append((rel, current, desired))
                break  # ordered, first match wins - see the manifest
            if settings.recursive:
                walk(child)

    walk(settings.root)
    return findings


def fail(message: str) -> int:
    print(f"error: {message}", file=sys.stderr)
    return 1
