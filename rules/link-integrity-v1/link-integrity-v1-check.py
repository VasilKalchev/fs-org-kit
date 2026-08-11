#!/usr/bin/env python3
"""
link-integrity-v1-check.py - reports links whose target no longer exists,
across the several unrelated formats that all mean "link". See
link-integrity-v1.toml for which kinds are checked, what can actually be
verified without a network, and why there's no fixer.

Protocol (protocol_version 1.0, single scope):
    python link-integrity-v1-check.py --path <dir> --params '<json>'

stdout: exactly one JSON line - {"status": "ok"}
                               | {"status": "violation", "message": "..."}
exit code: 0 = ran fine (read stdout for the verdict)
           nonzero = this invocation is broken - stderr has why
"""

import argparse
import fnmatch
import json
import os
import shutil
import struct
import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

KINDS = ("symlink", "desktop", "shortcut", "webloc")
FOREIGN_MODES = ("skip", "report")
MAX_REPORTED = 8
MAX_CHAIN = 40

# A .lnk always opens with a 76-byte header whose first field is its own
# size and whose second is a fixed class id. Both are checked before any
# offset in the file is trusted.
LNK_HEADER_SIZE = 0x4C
LNK_CLSID = bytes([0x01, 0x14, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00,
                   0xC0, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x46])
LNK_HAS_TARGET_ID_LIST = 0x01
LNK_HAS_LINK_INFO = 0x02
LINK_INFO_HAS_LOCAL_PATH = 0x01


def is_excluded(rel_path: str, globs: list) -> bool:
    return any(fnmatch.fnmatch(rel_path, g) or fnmatch.fnmatch(Path(rel_path).name, g) for g in globs)


# ---------------------------------------------------------------------
# One result per link examined
# ---------------------------------------------------------------------

OK, BROKEN, FOREIGN, UNVERIFIABLE = "ok", "broken", "foreign", "unverifiable"


def looks_foreign(target: str) -> bool:
    """A Windows path on a machine that has no drive letters, or vice
    versa. Judged by shape rather than by os.name so the answer doesn't
    change with where the check happens to run."""
    if os.name == "nt":
        return target.startswith("/")
    return len(target) > 1 and target[1] == ":" and target[0].isalpha()


def resolve_local(target: str, base: Path) -> str:
    """The verdict for a target naming a local path. A relative target is
    resolved against the link's own directory, which is how every one of
    these formats defines it."""
    if looks_foreign(target):
        return FOREIGN
    path = Path(target)
    if not path.is_absolute():
        path = base / path
    return OK if path.exists() else BROKEN


# --- symlinks --------------------------------------------------------

def check_symlink(link: Path, follow_chains: bool) -> tuple[str, str]:
    try:
        raw = os.readlink(link)
    except OSError as e:
        return BROKEN, f"unreadable symlink ({e.strerror})"

    seen: set[Path] = set()
    current = link
    for _ in range(MAX_CHAIN):
        if not current.is_symlink():
            break
        resolved = current.parent / os.readlink(current)
        if resolved in seen:
            return BROKEN, f"symlink cycle via {raw}"
        seen.add(resolved)
        current = resolved
        if not follow_chains:
            break

    try:
        exists = current.exists()
    except OSError as e:
        # ELOOP - the OS itself refuses to traverse it
        return BROKEN, f"symlink cycle ({e.strerror})"
    return (OK, "") if exists else (BROKEN, f"-> {raw}")


# --- freedesktop .desktop --------------------------------------------

def parse_desktop(path: Path) -> dict:
    """The [Desktop Entry] group's key=value pairs. Deliberately not
    configparser: .desktop values routinely contain '%' and ';' and
    unescaped '%' makes configparser's interpolation raise."""
    values: dict[str, str] = {}
    in_group = False
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("[") and line.endswith("]"):
            in_group = line == "[Desktop Entry]"
            continue
        if not in_group or not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        values.setdefault(key.strip(), value.strip())
    return values


def check_desktop(path: Path) -> tuple[str, str]:
    entry = parse_desktop(path)
    entry_type = entry.get("Type", "")

    if entry_type == "Link":
        url = entry.get("URL", "")
        if not url:
            return BROKEN, "Type=Link with no URL"
        return check_url(url, path.parent)

    if entry_type == "Application":
        exec_line = entry.get("Exec", "")
        if not exec_line:
            return BROKEN, "Type=Application with no Exec"
        # Exec is a command line with field codes (%f, %U, ...); only the
        # program itself can be checked for existence.
        program = exec_line.split()[0].strip('"')
        if "/" in program:
            return resolve_local(program, path.parent), f"Exec -> {program}"
        return (OK, "") if shutil.which(program) else (BROKEN, f"Exec -> {program} (not on PATH)")

    # Type=Directory, or an entry with no Type at all - nothing to break.
    return OK, ""


# --- URL-bearing formats ---------------------------------------------

def check_url(url: str, base: Path) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme in ("", "file"):
        target = unquote(parsed.path if parsed.scheme == "file" else url)
        if not target:
            return BROKEN, f"unusable URL {url!r}"
        return resolve_local(target, base), f"-> {target}"
    # http(s) and friends: counted, never judged - see the manifest.
    return UNVERIFIABLE, f"{parsed.scheme}: URL"


def check_url_file(path: Path) -> tuple[str, str]:
    """.url - an INI file whose [InternetShortcut] group holds URL=."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return BROKEN, f"unreadable ({e.strerror})"
    for line in text.splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key.strip().lower() == "url":
            return check_url(value.strip(), path.parent)
    return BROKEN, "no URL= line"


def check_webloc(path: Path) -> tuple[str, str]:
    """.webloc - a plist with one URL. plistlib handles both the XML and
    the binary form, which is what makes this worth doing properly."""
    import plistlib
    try:
        with path.open("rb") as f:
            data = plistlib.load(f)
    except Exception:
        return BROKEN, "not a readable plist"
    url = data.get("URL") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url:
        return BROKEN, "plist has no URL"
    return check_url(url, path.parent)


# --- Windows .lnk ----------------------------------------------------

def read_lnk_target(path: Path) -> tuple[str, str]:
    """The local path stored in a shell link, or ("", reason).

    Only the LinkInfo structure is parsed - it holds a plain
    LocalBasePath, while the LinkTargetIDList before it is a chain of
    shell item ids that needs the shell namespace to interpret. Every
    offset is bounds-checked before use: this is attacker-adjacent
    binary parsing of files that arrive from elsewhere.
    """
    try:
        blob = path.read_bytes()
    except OSError as e:
        return "", f"unreadable ({e.strerror})"

    if len(blob) < LNK_HEADER_SIZE:
        return "", "truncated shell link"
    header_size, = struct.unpack_from("<I", blob, 0)
    if header_size != LNK_HEADER_SIZE or blob[4:20] != LNK_CLSID:
        return "", "not a shell link"

    flags, = struct.unpack_from("<I", blob, 20)
    offset = LNK_HEADER_SIZE

    if flags & LNK_HAS_TARGET_ID_LIST:
        if len(blob) < offset + 2:
            return "", "truncated target id list"
        id_list_size, = struct.unpack_from("<H", blob, offset)
        offset += 2 + id_list_size

    if not flags & LNK_HAS_LINK_INFO:
        return "", "shell link stores no local path"
    if len(blob) < offset + 28:
        return "", "truncated link info"

    info_start = offset
    info_size, info_header_size, info_flags = struct.unpack_from("<III", blob, info_start)
    if info_size < 28 or info_start + info_size > len(blob):
        return "", "link info runs past end of file"
    if not info_flags & LINK_INFO_HAS_LOCAL_PATH:
        return "", "shell link points at a network location"

    local_offset, = struct.unpack_from("<I", blob, info_start + 16)
    suffix_offset, = struct.unpack_from("<I", blob, info_start + 24)

    def read_cstring(at: int) -> str:
        absolute = info_start + at
        if not 0 < at < info_size or absolute >= len(blob):
            return ""
        end = blob.find(b"\x00", absolute, info_start + info_size)
        end = len(blob) if end == -1 else end
        return blob[absolute:end].decode("mbcs" if os.name == "nt" else "latin-1", errors="replace")

    base = read_cstring(local_offset)
    if not base:
        return "", "shell link has an empty local path"
    return base + read_cstring(suffix_offset), ""


def check_lnk(path: Path) -> tuple[str, str]:
    target, problem = read_lnk_target(path)
    if not target:
        return (UNVERIFIABLE, problem) if "network" in problem else (BROKEN, problem)
    return resolve_local(target, path.parent), f"-> {target}"


# ---------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------

def classify(item: Path, kinds: set) -> str:
    """Which checker applies, or "" for something that isn't a link.
    Symlink wins over suffix: a symlink named x.desktop is a symlink.
    Finder aliases ride along with "webloc" rather than getting a kind of
    their own - both are macOS-only, and an alias is only ever counted,
    never resolved, so a separate switch would control nothing."""
    if item.is_symlink():
        return "symlink" if "symlink" in kinds else ""
    suffix = item.suffix.lower()
    if suffix == ".desktop" and "desktop" in kinds:
        return "desktop"
    if suffix in (".lnk", ".url") and "shortcut" in kinds:
        return "shortcut"
    if suffix == ".webloc" and "webloc" in kinds:
        return "webloc"
    if suffix == ".alias" and "webloc" in kinds:
        return "alias"
    return ""


def check_one(item: Path, kind: str, follow_chains: bool) -> tuple[str, str]:
    if kind == "symlink":
        return check_symlink(item, follow_chains)
    if kind == "desktop":
        return check_desktop(item)
    if kind == "shortcut":
        return check_lnk(item) if item.suffix.lower() == ".lnk" else check_url_file(item)
    if kind == "webloc":
        return check_webloc(item)
    # macOS Finder alias - see the manifest; counted, never guessed at.
    return UNVERIFIABLE, "macOS Finder alias (opaque bookmark blob)"


def walk(root: Path, base: Path, recursive: bool, exclude: list, kinds: set,
         follow_chains: bool, results: list) -> None:
    try:
        children = sorted(root.iterdir())
    except OSError:
        return
    for child in children:
        rel = child.relative_to(base).as_posix()
        if is_excluded(rel, exclude):
            continue
        kind = classify(child, kinds)
        if kind:
            verdict, detail = check_one(child, kind, follow_chains)
            results.append((verdict, rel, detail))
            continue
        if child.is_dir() and recursive:
            walk(child, base, recursive, exclude, kinds, follow_chains, results)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: link-integrity-v1 has no fixer", file=sys.stderr)
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

    kinds = params.get("kinds", list(KINDS))
    recursive = bool(params.get("recursive", True))
    exclude = params.get("exclude", [])
    foreign_mode = params.get("foreign_links", "skip")
    follow_chains = bool(params.get("follow_chains", True))

    if not isinstance(kinds, list) or not kinds:
        print("error: kinds must be a non-empty list", file=sys.stderr)
        return 1
    unknown = [k for k in kinds if k not in KINDS]
    if unknown:
        print(f"error: unknown link kind(s) {unknown}; known: {list(KINDS)}", file=sys.stderr)
        return 1
    if not isinstance(exclude, list):
        print("error: exclude must be a list of glob strings", file=sys.stderr)
        return 1
    if foreign_mode not in FOREIGN_MODES:
        print(f"error: foreign_links must be one of {list(FOREIGN_MODES)}, got {foreign_mode!r}", file=sys.stderr)
        return 1

    results: list[tuple[str, str, str]] = []
    walk(root, root, recursive, exclude, set(kinds), follow_chains, results)

    broken = [(rel, detail) for verdict, rel, detail in results if verdict == BROKEN]
    foreign = [rel for verdict, rel, _ in results if verdict == FOREIGN]
    unverifiable = sum(1 for verdict, _, _ in results if verdict == UNVERIFIABLE)

    reported = list(broken)
    if foreign_mode == "report":
        reported += [(rel, "target belongs to another platform") for rel in foreign]

    if not reported:
        print(json.dumps({"status": "ok"}))
        return 0

    shown = ", ".join(f"{rel} ({detail})" if detail else rel for rel, detail in reported[:MAX_REPORTED])
    if len(reported) > MAX_REPORTED:
        shown += f", ... ({len(reported) - MAX_REPORTED} more)"
    message = f"{len(reported)} broken link(s) of {len(results)} checked: {shown}"
    if unverifiable:
        message += f"; {unverifiable} link(s) could not be verified (remote URL or opaque alias)"
    if foreign and foreign_mode == "skip":
        message += f"; {len(foreign)} link(s) target another platform and were skipped"
    print(json.dumps({"status": "violation", "message": message}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
