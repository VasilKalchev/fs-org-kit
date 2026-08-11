#!/usr/bin/env python3
"""
changed-since-v1-check.py - reports what changed under a path since the
last run, from a cached snapshot. See changed-since-v1.toml for why the
first run is never a violation, what counts as a change, and the three
report formats.

Protocol (protocol_version 1.0, single scope):
    python changed-since-v1-check.py --path <dir> --params '<json>'
                                     [--cache-dir <dir>]

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why

--cache-dir is optional by protocol: without it there is nowhere to keep
a baseline, so every run is a first run and reports ok. The rule never
picks a location of its own - see fs_org_kit/cache.py for why.
"""

import argparse
import fnmatch
import hashlib
import json
import sys
from pathlib import Path

TRACK_MODES = ("mtime", "size", "both")
REPORT_MODES = ("summary", "list", "tree")

ADDED, REMOVED, MODIFIED = "+", "-", "~"
SNAPSHOT_VERSION = 1


def is_excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


def snapshot(root: Path, recursive: bool, exclude: list) -> dict:
    """{relative path: [size, mtime_ns]} for everything under root.

    A directory is recorded as [-1, -1]: tracked by presence only, never
    by its own timestamps. A directory's mtime moves whenever anything
    inside it is added or removed, so tracking it would report the same
    edit twice when recursive (once for the file, once for its folder)
    and would report deep edits even when NOT recursive - which is
    precisely what that setting says not to look at.

    The -1 size doubles as the marker that makes a path changing from a
    file to a directory read as one modification rather than as two
    unrelated entries.

    Symlinks are recorded from their own lstat, not their target's -
    following one would report changes to a file outside this tree.
    """
    found: dict[str, list] = {}

    def walk(folder: Path) -> None:
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            rel = child.relative_to(root).as_posix()
            if is_excluded(rel, exclude):
                continue
            try:
                info = child.lstat()
            except OSError:
                continue
            is_dir = child.is_dir() and not child.is_symlink()
            found[rel] = [-1, -1] if is_dir else [info.st_size, info.st_mtime_ns]
            if is_dir and recursive:
                walk(child)

    walk(root)
    return found


def differs(before: list, after: list, track: str) -> bool:
    if before[0] != after[0] and track in ("size", "both"):
        return True
    if before[1] != after[1] and track in ("mtime", "both"):
        return True
    # A file turning into a directory (or back) is a change under any
    # tracking mode - the -1 sentinel makes that visible even when the
    # mode being tracked happens to match.
    return (before[0] == -1) != (after[0] == -1)


def compare(before: dict, after: dict, track: str) -> list[tuple[str, str]]:
    changes = [(ADDED, rel) for rel in after if rel not in before]
    changes += [(REMOVED, rel) for rel in before if rel not in after]
    changes += [
        (MODIFIED, rel) for rel in after
        if rel in before and differs(before[rel], after[rel], track)
    ]
    return sorted(changes, key=lambda c: (c[1], c[0]))


def render_tree(changes: list[tuple[str, str]]) -> str:
    """The changed paths as an indented tree with unchanged branches
    collapsed away - an intermediate directory appears only because
    something under it changed, and carries no marker of its own.

    A deep change reads as its position in the hierarchy rather than as
    a long path repeated on every line, which is the whole reason to
    draw it this way instead of listing.
    """
    tree: dict = {}
    for marker, rel in changes:
        node = tree
        parts = rel.split("/")
        for part in parts[:-1]:
            node = node.setdefault(part, {})
        node.setdefault(parts[-1], {})["__mark__"] = marker

    lines: list[str] = []

    def draw(node: dict, prefix: str) -> None:
        names = sorted(k for k in node if k != "__mark__")
        for i, name in enumerate(names):
            last = i == len(names) - 1
            child = node[name]
            marker = child.get("__mark__", " ")
            lines.append(f"{prefix}{'`-- ' if last else '|-- '}{marker} {name}")
            draw(child, prefix + ("    " if last else "|   "))

    draw(tree, "")
    return "\n".join(lines)


def render(changes: list[tuple[str, str]], mode: str, limit: int) -> str:
    counts = {
        "added": sum(1 for m, _ in changes if m == ADDED),
        "removed": sum(1 for m, _ in changes if m == REMOVED),
        "modified": sum(1 for m, _ in changes if m == MODIFIED),
    }
    headline = f"{len(changes)} change(s) since the last run: " + ", ".join(
        f"{n} {label}" for label, n in counts.items() if n
    )

    shown = changes[:limit]
    omitted = len(changes) - len(shown)

    if mode == "summary":
        listing = ", ".join(f"{m}{rel}" for m, rel in shown)
        return f"{headline}: {listing}" + (f", ... ({omitted} more)" if omitted else "")
    body = "\n".join(f"{m} {rel}" for m, rel in shown) if mode == "list" else render_tree(shown)
    return headline + "\n" + body + (f"\n... ({omitted} more)" if omitted else "")


def snapshot_path(cache_dir: Path, target: Path) -> Path:
    """One snapshot file per scanned path, since a single rule can be
    attached to many. Named by digest rather than by the path itself:
    a path contains separators and characters a filename can't hold."""
    digest = hashlib.sha256(str(target).encode("utf-8")).hexdigest()[:32]
    return cache_dir / f"{digest}.json"


def load_snapshot(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(data, dict) or data.get("version") != SNAPSHOT_VERSION:
        # An unreadable or older snapshot is treated as no snapshot: a
        # baseline is regenerable, so the cost is one silent run, never
        # a wrong comparison against a format that meant something else.
        return None
    entries = data.get("entries")
    return entries if isinstance(entries, dict) else None


def store_snapshot(path: Path, entries: dict) -> None:
    try:
        path.write_text(json.dumps({"version": SNAPSHOT_VERSION, "entries": entries}), encoding="utf-8")
    except OSError:
        pass  # an unwritable cache costs a comparison, never a wrong answer


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: changed-since-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    recursive = bool(params.get("recursive", True))
    exclude = params.get("exclude", [])
    track = params.get("track", "both")
    report = params.get("report", "summary")
    max_reported = params.get("max_reported", 20)
    update_baseline = bool(params.get("update_baseline", True))

    if not isinstance(exclude, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1
    if track not in TRACK_MODES:
        print(f"error: track must be one of {list(TRACK_MODES)}, got {track!r}", file=sys.stderr)
        return 1
    if report not in REPORT_MODES:
        print(f"error: report must be one of {list(REPORT_MODES)}, got {report!r}", file=sys.stderr)
        return 1
    if not isinstance(max_reported, int) or isinstance(max_reported, bool) or max_reported < 1:
        print(f"error: max_reported must be a positive integer, got {max_reported!r}", file=sys.stderr)
        return 1

    current = snapshot(root, recursive, exclude)

    if args.cache_dir is None:
        # No baseline is possible, so every run is a first run. Reporting
        # ok is the honest answer; inventing a comparison is not.
        print(json.dumps({"status": "ok"}))
        return 0

    cache_dir = Path(args.cache_dir)
    stored_at = snapshot_path(cache_dir, root.resolve())
    previous = load_snapshot(stored_at)

    if previous is None:
        store_snapshot(stored_at, current)
        print(json.dumps({"status": "ok"}))
        return 0

    changes = compare(previous, current, track)

    if not changes:
        print(json.dumps({"status": "ok"}))
        return 0

    if update_baseline:
        store_snapshot(stored_at, current)

    print(json.dumps({"status": "violation", "message": render(changes, report, max_reported)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
