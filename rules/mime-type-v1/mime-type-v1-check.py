#!/usr/bin/env python3
"""
mime-type-v1-check.py - checks each file's actual content-sniffed MIME
type against an allowed or disallowed list. See mime-type-v1.toml for
param documentation.

Protocol (protocol_version 1.0, single scope):
    python mime-type-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import codecs
import fnmatch
import json
import sys
from pathlib import Path

# (offset, signature bytes, mime type) - checked in order, first match wins.
# Not exhaustive - covers common formats likely to show up in a personal
# filesystem.
SIGNATURES = [
    (0, b"\x89PNG\r\n\x1a\n", "image/png"),
    (0, b"\xff\xd8\xff", "image/jpeg"),
    (0, b"GIF87a", "image/gif"),
    (0, b"GIF89a", "image/gif"),
    (0, b"BM", "image/bmp"),
    (0, b"%PDF-", "application/pdf"),
    (0, b"PK\x03\x04", "application/zip"),
    (0, b"PK\x05\x06", "application/zip"),
    (0, b"\x1f\x8b", "application/gzip"),
    (0, b"7z\xbc\xaf\x27\x1c", "application/x-7z-compressed"),
    (0, b"Rar!\x1a\x07", "application/vnd.rar"),
    (0, b"fLaC", "audio/flac"),
    (0, b"OggS", "audio/ogg"),
    (0, b"ID3", "audio/mpeg"),
    (0, b"SQLite format 3\x00", "application/vnd.sqlite3"),
    (0, b"\x7fELF", "application/x-executable"),
    (0, b"MZ", "application/x-msdownload"),
]
# formats needing a signature check at a non-zero offset
RIFF_SUBTYPES = {b"WEBP": "image/webp", b"WAVE": "audio/wav"}

FTYP_BRANDS = {
    b"heic": "image/heic", b"heix": "image/heic", b"hevc": "image/heic", b"hevx": "image/heic",
    b"heim": "image/heic", b"heis": "image/heic",
    b"mif1": "image/heif", b"msf1": "image/heif",
    b"avif": "image/avif", b"avis": "image/avif",
    b"M4A ": "audio/mp4", b"M4B ": "audio/mp4",
    b"qt  ": "video/quicktime",
    b"3gp4": "video/3gpp", b"3gp5": "video/3gpp", b"3gp6": "video/3gpp", b"3g2a": "video/3gpp2",
}


def sniff(path: Path):
    try:
        with path.open("rb") as f:
            head = f.read(64)
    except OSError:
        return None

    for offset, sig, mime in SIGNATURES:
        if head[offset:offset + len(sig)] == sig:
            return mime

    if head[:4] == b"RIFF" and len(head) >= 12:
        subtype = head[8:12]
        if subtype in RIFF_SUBTYPES:
            return RIFF_SUBTYPES[subtype]

    if head[4:8] == b"ftyp":
        # ISO base media: one container, many formats - the major brand
        # says which (an iPhone's HEIC photo is not an MP4 video)
        return FTYP_BRANDS.get(head[8:12], "video/mp4")

    if head[:2] in (b"\xff\xfb", b"\xff\xfa"):
        return "audio/mpeg"

    # heuristic text/plain fallback: valid UTF-8, no null bytes
    if head and b"\x00" not in head:
        try:
            # final=False: the 64-byte prefix may end partway through a
            # multibyte character, which says nothing about the file
            codecs.getincrementaldecoder("utf-8")().decode(head, final=False)
            return "text/plain"
        except UnicodeDecodeError:
            pass

    return None


def iter_entries(root: Path, recursive: bool, exclude_globs: list):
    """Every entry under root, in a stable order, minus what `exclude`
    names. A glob is matched against the path relative to root and
    against the bare name, and an excluded folder takes its whole
    subtree with it - the same reading every bundled rule's `exclude`
    has. Symlinked folders are listed, never descended into."""
    def walk(folder: Path):
        try:
            children = sorted(folder.iterdir())
        except OSError:
            return
        for child in children:
            rel = child.relative_to(root).as_posix()
            if any(fnmatch.fnmatch(rel, g) or fnmatch.fnmatch(child.name, g) for g in exclude_globs):
                continue
            yield child
            if recursive and child.is_dir() and not child.is_symlink():
                yield from walk(child)

    yield from walk(root)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: mime-type-v1 has no fixer", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    allowed = set(params.get("allowed", []))
    disallowed = set(params.get("disallowed", []))
    if bool(allowed) == bool(disallowed):
        print("error: exactly one of `allowed` or `disallowed` must be a non-empty list", file=sys.stderr)
        return 1

    unknown_is_violation = params.get("unknown_is_violation", False)
    recursive = params.get("recursive", True)
    exclude_globs = params.get("exclude", [])
    if not isinstance(exclude_globs, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    files = iter_entries(root, recursive, exclude_globs)
    violations = []
    for f in files:
        if not f.is_file():
            continue
        rel = f.relative_to(root).as_posix()
        mime = sniff(f)

        if mime is None:
            if unknown_is_violation and allowed:
                violations.append((rel, "unrecognized"))
            continue

        if allowed and mime not in allowed:
            violations.append((rel, mime))
        elif disallowed and mime in disallowed:
            violations.append((rel, mime))

    if not violations:
        print(json.dumps({"status": "ok"}))
        return 0

    violations.sort(key=lambda v: v[0])
    shown = violations[:10]
    more = f", and {len(violations) - 10} more" if len(violations) > 10 else ""
    mode = f"not in the allowed list {sorted(allowed)}" if allowed else f"in the disallowed list {sorted(disallowed)}"
    parts = [f"{rel} ({mime})" for rel, mime in shown]
    message = f"{len(violations)} file(s) with a sniffed type {mode}: {', '.join(parts)}{more}"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
