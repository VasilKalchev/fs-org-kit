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
        return "video/mp4"

    if head[:2] in (b"\xff\xfb", b"\xff\xfa"):
        return "audio/mpeg"

    # heuristic text/plain fallback: valid UTF-8, no null bytes
    if head and b"\x00" not in head:
        try:
            head.decode("utf-8")
            return "text/plain"
        except UnicodeDecodeError:
            pass

    return None


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

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    files = root.rglob("*") if recursive else root.glob("*")
    violations = []
    for f in files:
        if not f.is_file():
            continue
        mime = sniff(f)
        rel = f.relative_to(root).as_posix()

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
