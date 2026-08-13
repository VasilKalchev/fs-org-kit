"""
fs_org_kit.path_patterns - detects, statically compares, and (runner-side
only) expands glob-style [paths."..."] catalog keys against the real
filesystem.

The problem: a [paths."..."] entry is normally one exact location. A
personal filesystem often has many structurally-identical folders under
one prefix (one per client, one per numbered project, ...) that all
deserve the same purpose/lifecycle/rules without hand-maintaining a
separate, otherwise-identical catalog entry per folder. A glob-style key
fills that gap - one entry, many real matches, all sharing the same
attributes and rule attachments (attachments run once per real match -
unlike [[folders.rules]], which is one invocation on root with the rule
itself doing the walking).

Syntax is the same vocabulary already used everywhere for `exclude`
params - fnmatch/pathlib.Path.glob: `*` (one path segment), `**`
(any number of segments, recursive), `?`, `[abc]`. No brace-expansion
({1..3}) - it has no stdlib support (a bash-ism, not part of Python's
glob/fnmatch), and a character class ([1-3]) already covers the common
numeric-range case with zero extra code.

Detection needs no wrapper syntax - a key is a pattern if it contains a
glob metacharacter (*, ?, [), since a literal path can't legitimately
contain those characters anyway (see naming-pattern-v1's portable-
charset doc comment, and illegal-names-v1's history).

Two very different operations live here, deliberately kept apart along
the validator/runner line DESIGN.md draws:

- Overlap detection (`patterns_may_overlap`) is validator work - a
  purely static comparison of two catalog KEY STRINGS, no filesystem
  access. Two keys "may overlap" if there's some real relative path
  both could match, checked segment-by-segment. Deliberately
  conservative: it can flag a pair that could never truly collide on
  real content (e.g. [abc] vs [xyz] at the same segment position are
  treated as "may overlap", even though they can't actually share a
  character) - a false positive here costs a human a rename or an
  explicit adjustment; a false negative would be a silently-broken
  standard where two entries fight over the same real folder, disagree
  on its purpose/rules, and nothing ever tells you. `**`'s
  variable-length matching makes an exact non-overlap proof much more
  involved, so it isn't attempted beyond comparing each side's literal
  prefix before its first `**` - see `patterns_may_overlap`.

- Expansion (`expand_pattern`) is runner work - it walks the real
  filesystem and can only run once there's a real directory tree to
  walk. The validator never does this (see doc/DESIGN.md - "Validator
  is read-only"). A pattern matching zero real folders contributes no
  invocations and is reported nowhere - the same treatment a literal
  path that isn't on disk gets, so there's no separate concept here.
"""

from __future__ import annotations

from pathlib import Path

_GLOB_CHARS = set("*?[")


def is_pattern(key: str) -> bool:
    return any(c in _GLOB_CHARS for c in key)


def _segments(key: str) -> list[str]:
    return [s for s in key.split("/") if s]


def _segment_is_wildcard(segment: str) -> bool:
    return any(c in _GLOB_CHARS for c in segment)


def patterns_may_overlap(key_a: str, key_b: str) -> bool:
    """True if there's any real relative path both key_a and key_b could
    match, determined purely from the two strings - no filesystem
    access. See the module docstring for the conservative-approximation
    tradeoffs (never a false negative, occasionally a false positive).
    Two literal keys (no glob metacharacters in either) always compare
    False here unless they're the same string, since distinct TOML keys
    can never be equal - callers only need to call this on keys where
    at least one is a pattern."""
    segs_a, segs_b = _segments(key_a), _segments(key_b)

    def prefix_before_starstar(segs: list[str]) -> list[str]:
        return segs[: segs.index("**")] if "**" in segs else segs

    prefix_a, prefix_b = prefix_before_starstar(segs_a), prefix_before_starstar(segs_b)
    has_starstar = "**" in segs_a or "**" in segs_b

    if not has_starstar and len(segs_a) != len(segs_b):
        return False  # fixed-length patterns can't match the same string

    # `**` means segments past it could shift by any amount, so only the
    # fixed prefix before it is compared - zip() stops at the shorter
    # prefix, which is the correct, conservative thing to do here
    for a, b in zip(prefix_a, prefix_b):
        if a == b:
            continue
        if _segment_is_wildcard(a) or _segment_is_wildcard(b):
            continue  # conservatively compatible
        return False  # two different literal segments here - can't overlap

    return True


def expand_pattern(root_dir: Path, key: str) -> list[Path]:
    """Runner-only: walks the real filesystem and returns every existing
    directory matching `key`, sorted for deterministic invocation order.
    Non-directory matches are excluded - a [paths."..."] entry is always a
    folder.

    `key` is normally a pattern relative to root_dir. It may also name
    somewhere outside root (see fs_org_kit.path_keys), in which case
    globbing starts from the filesystem anchor instead: Path.glob
    rejects an absolute pattern outright, so the pattern is split into
    its anchor and the rest."""
    pattern = key.rstrip("/")
    base = Path(pattern).expanduser() if pattern.startswith("~") else Path(pattern)
    if base.is_absolute():
        anchor = Path(base.anchor)
        return sorted(p for p in anchor.glob(str(base.relative_to(anchor))) if p.is_dir())
    return sorted(p for p in root_dir.glob(pattern) if p.is_dir())
