"""
fs_org_kit.path_keys - decides what real location a [paths."..."] catalog
key names.

A catalog key is normally relative to `root`, and `root` is the whole
point of the standard: it's the tree being governed. But a personal
filesystem doesn't stop at one tree. `~/.config/`, `/etc/`, an external
drive's mount point - all are places worth cataloging and attaching rules
to, and none of them live under a `root` of, say, `~/usr/`. So a key may
be relative, absolute, home-relative, or walk up out of root, and this
module is the single place any of those becomes a real path.

That single place is the point: `root_dir / key` is NOT equivalent, and
gets two of those four cases wrong (see `resolve_key`). Never use a bare
join.
"""

from __future__ import annotations

import posixpath
from pathlib import Path


def is_home_relative(key: str) -> bool:
    return key.startswith("~")


def is_absolute_key(key: str) -> bool:
    """True for a key naming an absolute location - either literally
    ("/etc/") or once `~` is expanded ("~/.config/"). A drive-letter
    path ("C:/x/") counts on Windows, the same answer `resolve_key`'s
    `is_absolute()` gives there."""
    return key.startswith("/") or is_home_relative(key) or Path(key).is_absolute()


def resolve_key(root_dir: Path, key: str) -> Path:
    """The one place a catalog key becomes a real absolute path.

    Everything that touches disk goes through here, so every kind of key
    resolves identically everywhere. A plain `root_dir / key` silently
    discards root_dir when the key is absolute, and never expands `~` at
    all - which is why this exists and a bare join doesn't appear
    anywhere else."""
    path = Path(key)
    if is_home_relative(key):
        return path.expanduser().resolve()
    if path.is_absolute():
        return path.resolve()
    return (root_dir / key).resolve()


def comparison_key(key: str, root: str | None = None) -> str:
    """A normalized form for comparing two catalog keys against each other
    without touching disk - used for the validator's pattern-overlap
    check, where "~/x/" and "/home/me/x/" must be recognized as the same
    place. `expanduser()` reads $HOME (and the pwd database for `~user`),
    never the filesystem being validated, so this stays disk-free.

    Given the standard's `root` string, and that root is absolute or
    `~`-relative, a relative key is placed under it first - otherwise
    "prj/a/" and "~/usr/prj/a/" (with root "~/usr/") would compare as
    two places when the runner resolves them to one. `..` and `.`
    segments are collapsed for the same reason ("a/../b/" is "b/").

    Relative keys that can't be placed (no root, or a relative root) are
    returned with a leading "./" so they can never collide with an
    absolute key that happens to share their segments - "etc/nginx/"
    under root is not "/etc/nginx/"."""
    if not is_absolute_key(key) and root and is_absolute_key(root):
        key = root.rstrip("/") + "/" + key
    if is_absolute_key(key):
        return posixpath.normpath(Path(key).expanduser().as_posix())
    return "./" + posixpath.normpath(key)
