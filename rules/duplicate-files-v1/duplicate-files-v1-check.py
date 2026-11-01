#!/usr/bin/env python3
"""
duplicate-files-v1-check.py - finds byte-identical files by content
hash, either within one path (--path) or only across several
(--paths). See duplicate-files-v1.toml for the full param
documentation, the scope semantics, and where the hash cache lives.

Protocol (protocol_version 1.0, both scope):
    python duplicate-files-v1-check.py --path <dir> --params '<json>'
    python duplicate-files-v1-check.py --paths <dir> --paths <dir> [...] --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import hashlib
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

CHUNK_SIZE = 1024 * 1024
CACHE_FILENAME = "duplicate-files-v1.sqlite3"

MAX_GROUPS_SHOWN = 10
MAX_FILES_SHOWN_PER_GROUP = 5


# ---------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------

class HashCache:
    """A (path, algorithm) -> digest store, valid only while the file's
    size and mtime are both unchanged.

    Every failure mode here degrades to "no caching" rather than to an
    error: an unwritable home directory, a corrupt database, a
    read-only filesystem. The cache is an optimization, and a run that
    can't use it should still produce the right answer.
    """

    def __init__(self, conn: sqlite3.Connection | None):
        self.conn = conn
        self._hits: list[tuple[int, str, str]] = []   # (seen_at, path, algorithm) to refresh
        self._writes: list[tuple] = []                # full rows to upsert

    @classmethod
    def open(cls, directory: Path | None) -> "HashCache":
        """`directory` is whatever the runner handed us via --cache-dir,
        or None when there's nowhere to cache (invoked standalone, or
        the attachment set cache = false). This rule never picks a
        location itself - see the manifest's "The hash cache"."""
        if directory is None:
            return cls(None)
        try:
            directory.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(directory / CACHE_FILENAME, timeout=10.0)
            conn.execute(
                """CREATE TABLE IF NOT EXISTS hashes (
                       path      TEXT    NOT NULL,
                       algorithm TEXT    NOT NULL,
                       size      INTEGER NOT NULL,
                       mtime_ns  INTEGER NOT NULL,
                       digest    TEXT    NOT NULL,
                       seen_at   INTEGER NOT NULL,
                       PRIMARY KEY (path, algorithm)
                   )"""
            )
            conn.commit()
            return cls(conn)
        except (OSError, sqlite3.Error) as e:
            print(f"warning: hash cache unavailable, hashing without it ({e})", file=sys.stderr)
            return cls(None)

    def lookup(self, path: str, algorithm: str, size: int, mtime_ns: int) -> str | None:
        if self.conn is None:
            return None
        try:
            row = self.conn.execute(
                "SELECT size, mtime_ns, digest FROM hashes WHERE path = ? AND algorithm = ?",
                (path, algorithm),
            ).fetchone()
        except sqlite3.Error:
            return None
        if row is None:
            return None
        cached_size, cached_mtime_ns, digest = row
        if cached_size != size or cached_mtime_ns != mtime_ns:
            return None  # stale - the file changed under us
        self._hits.append((int(time.time()), path, algorithm))
        return digest

    def store(self, path: str, algorithm: str, size: int, mtime_ns: int, digest: str) -> None:
        if self.conn is None:
            return
        self._writes.append((path, algorithm, size, mtime_ns, digest, int(time.time())))

    def flush(self, ttl_days: int) -> None:
        """One batched write at the end, not a write per file."""
        if self.conn is None:
            return
        try:
            if self._writes:
                self.conn.executemany(
                    "INSERT OR REPLACE INTO hashes"
                    " (path, algorithm, size, mtime_ns, digest, seen_at)"
                    " VALUES (?, ?, ?, ?, ?, ?)",
                    self._writes,
                )
            if self._hits:
                self.conn.executemany(
                    "UPDATE hashes SET seen_at = ? WHERE path = ? AND algorithm = ?",
                    self._hits,
                )
            swept = 0
            if ttl_days > 0:
                cutoff = int(time.time()) - ttl_days * 86400
                swept = self.conn.execute(
                    "DELETE FROM hashes WHERE seen_at < ?", (cutoff,)
                ).rowcount
            self.conn.commit()
            if swept > 0:
                # DELETE only marks pages free for reuse inside the file -
                # without this, the cache never gets smaller on disk, only
                # emptier. VACUUM rewrites the whole database, so it's
                # gated on actually having swept something: in steady
                # state nothing expires and this never runs.
                # Must come after commit() - VACUUM can't run inside a
                # transaction, and Python's sqlite3 opens one implicitly
                # for the DML above.
                self.conn.execute("VACUUM")
            self.conn.close()
        except sqlite3.Error as e:
            print(f"warning: could not update the hash cache ({e})", file=sys.stderr)


# ---------------------------------------------------------------------
# Scanning and hashing
# ---------------------------------------------------------------------

def normalize_extensions(extensions: list) -> set:
    return {str(e).lower().lstrip(".") for e in extensions}


def collect_files(root: Path, base: Path, recursive: bool, extensions: set,
                   exclude_globs: list, min_size: int):
    """Yields (abs_path, stat_result) for every file under `root` that
    passes the filters, via os.scandir() so each entry's type comes from
    the same directory read that found it - Path.rglob()/glob() yield
    plain Path objects with no cached type or stat info, so the
    is_symlink()/is_file()/stat() calls that used to follow each one
    re-hit the filesystem individually. `base` stays the original root
    across the recursion, so exclude globs keep matching the full
    relative path, not just the path within the current folder.
    Symlinked directories are not descended into, matching Path.rglob()'s
    current default. Symlinks are skipped entirely - see the manifest's
    "What is NOT reported"."""
    try:
        entries = sorted(os.scandir(root), key=lambda e: e.name)
    except OSError:
        entries = []
    for entry in entries:
        if entry.is_symlink():
            continue
        item = Path(entry.path)
        rel = item.relative_to(base).as_posix()
        if any(fnmatch.fnmatch(rel, p) or fnmatch.fnmatch(entry.name, p) for p in exclude_globs):
            continue  # for a folder, this also prunes everything below it
        if entry.is_dir():
            if recursive:
                yield from collect_files(item, base, recursive, extensions, exclude_globs, min_size)
            continue
        if not entry.is_file():
            continue
        if extensions and item.suffix.lower().lstrip(".") not in extensions:
            continue
        try:
            st = entry.stat()
        except OSError:
            continue  # vanished or unreadable between listing and stat
        if st.st_size < min_size:
            continue
        yield item, st


def compute_digest(path: Path, algorithm: str) -> str:
    h = hashlib.new(algorithm)
    with path.open("rb") as fh:
        while chunk := fh.read(CHUNK_SIZE):
            h.update(chunk)
    return h.hexdigest()


def digest_for(path: Path, st, algorithm: str, cache: HashCache) -> str:
    key = str(path)
    cached = cache.lookup(key, algorithm, st.st_size, st.st_mtime_ns)
    if cached is not None:
        return cached
    digest = compute_digest(path, algorithm)
    cache.store(key, algorithm, st.st_size, st.st_mtime_ns, digest)
    return digest


# ---------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------

def format_message(groups: list, cross: bool) -> str:
    """Groups are lists of (root, abs_path). In single scope the one
    root is implied, so paths show relative to it; in cross scope the
    whole point is which root a file came from, so they show in full."""
    shown = groups[:MAX_GROUPS_SHOWN]
    more_groups = f", and {len(groups) - MAX_GROUPS_SHOWN} more group(s)" if len(groups) > MAX_GROUPS_SHOWN else ""

    rendered = []
    for group in shown:
        files = sorted(
            str(p) if cross else p.relative_to(root).as_posix()
            for root, p in group
        )
        extra = f", +{len(files) - MAX_FILES_SHOWN_PER_GROUP} more" if len(files) > MAX_FILES_SHOWN_PER_GROUP else ""
        rendered.append("[" + ", ".join(files[:MAX_FILES_SHOWN_PER_GROUP]) + extra + "]")

    scope_note = "spanning 2+ of the given paths" if cross else "within this path"
    return (
        f"{len(groups)} group(s) of identical files {scope_note}: "
        + ", ".join(rendered)
        + more_groups
    )


# ---------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path")
    parser.add_argument("--paths", action="append")
    parser.add_argument("--params", required=True)
    parser.add_argument("--cache-dir")
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: duplicate-files-v1 has no fixer", file=sys.stderr)
        return 1

    # scope = "both": the script itself is responsible for rejecting a
    # nonsensical combination, per doc/RULES.md.
    if args.path and args.paths:
        print("error: pass either --path or --paths, not both", file=sys.stderr)
        return 1
    if not args.path and not args.paths:
        print("error: one of --path or --paths is required", file=sys.stderr)
        return 1
    if args.paths and len(args.paths) < 2:
        print("error: --paths needs 2 or more locations (use --path for one)", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    cross = args.paths is not None
    roots = [Path(p) for p in (args.paths if cross else [args.path])]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1

    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1
    raw_extensions = params.get("extensions", [])
    if not isinstance(raw_extensions, list):
        print("error: extensions must be a list", file=sys.stderr)
        return 1
    extensions = normalize_extensions(raw_extensions)

    min_size = params.get("min_size", 1)
    if not isinstance(min_size, int) or isinstance(min_size, bool) or min_size < 0:
        print("error: min_size must be a non-negative integer number of bytes", file=sys.stderr)
        return 1

    algorithm = params.get("algorithm", "blake2b")
    try:
        hashlib.new(algorithm)
    except (ValueError, TypeError):
        print(f"error: unknown hash algorithm {algorithm!r}", file=sys.stderr)
        return 1

    ttl_days = params.get("cache_ttl_days", 30)
    if not isinstance(ttl_days, int) or isinstance(ttl_days, bool) or ttl_days < 0:
        print("error: cache_ttl_days must be a non-negative integer", file=sys.stderr)
        return 1

    # -- collect, collapsing hardlinks to one entry per inode ----------
    by_size: dict[int, list] = {}
    seen_inodes = set()
    for root in roots:
        for path, st in collect_files(root, root, recursive, extensions, exclude_globs, min_size):
            identity = (st.st_dev, st.st_ino)
            if identity == (0, 0):
                # os.DirEntry.stat() leaves both at zero on Windows, which
                # would make every file look like a hardlink of the first
                try:
                    full = os.stat(path, follow_symlinks=False)
                    identity = (full.st_dev, full.st_ino)
                except OSError:
                    continue  # vanished between listing and stat
            if identity in seen_inodes:
                continue  # another name for bytes we already have
            seen_inodes.add(identity)
            by_size.setdefault(st.st_size, []).append((root, path, st))

    # -- hash only what could possibly collide -------------------------
    # Files with a unique size can't be byte-identical to anything, so
    # they're never read at all. On a typical media tree this discards
    # the large majority of candidates before any I/O happens.
    # No --cache-dir (standalone run, or the core couldn't make one) and
    # cache = false both mean the same thing here: hash everything, keep
    # nothing. Correct either way, just slower.
    cache_dir = Path(args.cache_dir) if args.cache_dir and params.get("cache", True) else None
    cache = HashCache.open(cache_dir)
    by_digest: dict[tuple[int, str], list] = {}
    try:
        for size, candidates in by_size.items():
            if len(candidates) < 2:
                continue
            for root, path, st in candidates:
                try:
                    digest = digest_for(path, st, algorithm, cache)
                except OSError as e:
                    print(f"warning: could not read {path} ({e})", file=sys.stderr)
                    continue
                by_digest.setdefault((size, digest), []).append((root, path))
    finally:
        cache.flush(ttl_days)

    # -- filter to the groups this attachment actually asked about -----
    groups = []
    for members in by_digest.values():
        if len(members) < 2:
            continue
        if cross and len({root for root, _ in members}) < 2:
            continue  # entirely inside one root - not this attachment's question
        groups.append(members)

    if not groups:
        print(json.dumps({"status": "ok"}))
        return 0

    groups.sort(key=lambda g: sorted(str(p) for _, p in g))
    print(json.dumps({"status": "violation", "message": format_message(groups, cross)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
