"""
fs_org_kit.path_keys - decides what real location a [paths."..."] catalog
key names, and whether that location escapes `root`.

A catalog key is normally relative to `root`, and `root` is the whole
point of the standard: it's the tree being governed. But a personal
filesystem doesn't stop at one tree. `~/.config/`, `/etc/`, an external
drive's mount point - all are places worth cataloging and attaching rules
to, and none of them live under a `root` of, say, `~/usr/`.

Such a key is legal, but only when the entry says so:

    [paths."/etc/nginx/"]
    outside_root = true
    purpose = "..."

Why a flag rather than just accepting an absolute key:

- It was already silently "working", wrongly. `Path("/home/me/usr") /
  "/etc/nginx"` is `/etc/nginx` - Python's path join DISCARDS the left
  side when the right is absolute. So an absolute key typo'd into a
  standard would already have sent rules walking somewhere far outside
  root, with nothing anywhere saying so. Turning that into an
  opt-in makes the escape deliberate instead of accidental.
- It's the same shape as `overrides_bundled` and `allow_missing`
  elsewhere in this project: the surprising thing is rejected by
  default, and one explicit field on the record opts out.
- The runner's sandbox (fs_org_kit.sandbox) confines a fixer's writes to
  root plus its declared targets. An out-of-root target has to be
  declared for that confinement to know about it.

`outside_root` is deliberately NOT inheritable and NOT defaultable - see
Validator._check_outside_root. It has to be written on the entry that
escapes, the same way `reason` has to be written at every rule
attachment site. A flag that could arrive via inheritance would let a
one-word edit to an unrelated entry quietly widen what the tool touches.

Three kinds of key escape root, and all three need the flag:

    "/etc/nginx/"     absolute
    "~/.config/"      home-relative (absolute once expanded)
    "../sibling/"     relative, but walks up out of root

The `..` case matters: it escapes just as completely as a leading slash,
and is easier to write by accident.
"""

from __future__ import annotations

from pathlib import Path

OUTSIDE_ROOT_ATTR = "outside_root"


def is_home_relative(key: str) -> bool:
    return key.startswith("~")


def is_absolute_key(key: str) -> bool:
    """True for a key naming an absolute location - either literally
    ("/etc/") or once `~` is expanded ("~/.config/")."""
    return key.startswith("/") or is_home_relative(key)


def walks_above_root(key: str) -> bool:
    """True for a RELATIVE key whose `..` segments take it above root.
    Purely textual - "a/../b/" stays inside and is fine, "../b/" doesn't.
    No filesystem access, so the validator can call it (doc/DESIGN.md -
    "Validator is read-only")."""
    depth = 0
    for segment in key.split("/"):
        if segment in ("", "."):
            continue
        if segment == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def escapes_root(key: str) -> bool:
    """True if this key names something outside root, by any of the three
    routes in the module docstring."""
    return is_absolute_key(key) or walks_above_root(key)


def resolve_key(root_dir: Path, key: str) -> Path:
    """The one place a catalog key becomes a real absolute path.

    Everything that touches disk goes through here so the three escape
    routes are handled identically everywhere. Note that plain
    `root_dir / key` is NOT equivalent: it silently discards root_dir
    for an absolute key and doesn't expand `~` at all, which is exactly
    the accident `outside_root` exists to surface."""
    path = Path(key)
    if is_home_relative(key):
        return path.expanduser().resolve()
    if path.is_absolute():
        return path.resolve()
    return (root_dir / key).resolve()


def comparison_key(key: str) -> str:
    """A normalized form for comparing two catalog keys against each other
    without touching disk - used for the validator's pattern-overlap
    check, where "~/x/" and "/home/me/x/" must be recognized as the same
    place. `expanduser()` reads $HOME (and the pwd database for `~user`),
    never the filesystem being validated, so this stays disk-free.

    Relative keys are returned with a leading "./" so they can never
    collide with an absolute key that happens to share their segments -
    "etc/nginx/" under root is not "/etc/nginx/"."""
    if is_absolute_key(key):
        return str(Path(key).expanduser()).rstrip("/") or "/"
    return "./" + key.strip("/")
