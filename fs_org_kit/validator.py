#!/usr/bin/env python3
"""
validator.py - checks a TOML file against the fs-org-std grammar defined in
fs-org-std.template.toml. The file being checked can be named anything; it's
validated against the *standard*, not against a specific filename.

This does NOT hardcode field names, enums or requiredness - it reads
them from the file itself (see fs_org_kit.fields), so a standard names
its own fields and this stays correct. Rule catalog validation (scope,
params, required fields) is driven by discovery.py, which reads
manifests from disk rather than from an embedded [rules] table.

Usage:
    python -m fs_org_kit.validator path/to/your-file.toml
    python -m fs_org_kit.validator path/to/your-file.toml --strict
    python -m fs_org_kit.validator path/to/your-file.toml --no-color
    python -m fs_org_kit.validator path/to/your-file.toml --no-warnings
    python -m fs_org_kit.validator path/to/your-file.toml --only paths,rules
    python -m fs_org_kit.validator path/to/your-file.toml --ignore-warning empty-list-item,unknown-param
    python -m fs_org_kit.validator path/to/your-file.toml --validate-only
    python -m fs_org_kit.validator path/to/your-file.toml --lint-only

Output lines are in the usual compiler/linter format so editors and
terminals can jump straight to the problem:

    path/to/your-file.toml:42: [ERROR] paths."media/pic/".lifecycle: ...
    path/to/your-file.toml:99: [WARNING] paths."media/pic/".not_for: ... (empty-list-item)

Line numbers are best-effort: resolved by matching each issue's location
against the nearest enclosing table header in the file, not a full TOML
AST, so very occasionally (e.g. deeply nested duplicate headers) they'll
point at the start of the right block rather than the exact field.

Flags:
    --no-warnings           don't print individual warning lines. The
                             summary table and warning count still reflect
                             them - this only hides the line-by-line detail.
    --only CATEGORY[,...]   only check/report these categories (repeatable,
                             or comma-separated). Categories: paths,
                             paths.rules, paths.cross, folders,
                             folders.rules, meta.
    --ignore-warning CODE[,...]
                             fully ignore warnings with this code (repeatable,
                             or comma-separated) - not printed, not counted,
                             not reflected in the summary table. Every
                             warning line shows its code in parentheses.
    --validate-only          only run structural/schema checks - required
                             fields, enum membership, rule references,
                             scope, params, version compatibility. Skips
                             style/convention checks. Mutually exclusive
                             with --lint-only.
    --lint-only              only run style/convention checks - path key
                             slashes, reserved-name prefix, empty
                             placeholder entries, and similar. Skips
                             structural/schema checks. Mutually exclusive
                             with --validate-only. Every check's kind
                             (validation/lint) is listed by --list-warnings.
    --strict                treat warnings as errors for the exit code
    --no-color               disable colored output

By default both validation and linting run together; these two flags
narrow a single run to one or the other, they don't turn linting off
by default.

Exit codes:
    0  no errors (warnings may still be present)
    1  one or more errors found
    2  the file could not be read/parsed, or an unknown --only category
       was given
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from fs_org_kit.discovery import DiscoveryIssue, IssueLevel, RuleEntry, Tier, discover_rules
from fs_org_kit.fields import ATTRIBUTES, GROUP, RULES, STRUCTURAL_KEYS, FieldSpec, parse_field_spec
from fs_org_kit.inherit import InheritIssue, ResolvedEntry, RuleAttachment, own_fields, resolve_entries
from fs_org_kit.param_refs import expand_params
from fs_org_kit.path_keys import comparison_key
from fs_org_kit.path_patterns import is_pattern, patterns_may_overlap

# the schema major version this validator understands - bump this
# deliberately whenever a breaking (major-version) grammar change is made
# to fs-org-std.template.toml, alongside updating the checks themselves
SUPPORTED_SCHEMA_MAJOR = 2

# Keys under [paths] / [folders.reserved] that are schema-level config
# rather than an entry, so iterating either namespace's entries skips
# them. This is knowledge about the grammar, and lives with the module
# that checks the grammar - a param `{ref}` pointing at one of these
# tables hands the rule the whole thing, meta keys included, and the
# rule decides what it wants (see fs_org_kit.param_refs).
META_KEYS_UNDER_PATHS = {"attributes", "rules", "cross"}
META_KEYS_UNDER_RESERVED = {"prefix"}


# ---------------------------------------------------------------------
# Source-location resolution (best-effort, regex-based - not a full AST)
# ---------------------------------------------------------------------

_ARRAY_HEADER_RE = re.compile(r'^\[\[(.+)\]\]$')
_TABLE_HEADER_RE = re.compile(r'^\[(.+)\]$')
_TOP_KEY_RE = re.compile(r'^([A-Za-z0-9_-]+)\s*=')
_INDEX_RE = re.compile(r'^(.*)\[(\d+)\]$')


def _index_source(text: str) -> tuple[dict[str, list[int]], dict[str, int]]:
    """Map literal TOML header text -> the line number(s) it appears on,
    and bare top-level key -> its line number. Used to give issues an
    approximate source line without a full TOML parser/AST."""
    header_occurrences: dict[str, list[int]] = {}
    key_lines: dict[str, int] = {}

    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        line = re.sub(r"\s*#.*$", "", raw_line).strip()
        if not line:
            continue

        m = _ARRAY_HEADER_RE.match(line)
        if m:
            header_occurrences.setdefault(m.group(1).strip(), []).append(lineno)
            continue

        m = _TABLE_HEADER_RE.match(line)
        if m:
            header_occurrences.setdefault(m.group(1).strip(), []).append(lineno)
            continue

        if not raw_line[:1].isspace():
            m = _TOP_KEY_RE.match(line)
            if m:
                key_lines.setdefault(m.group(1), lineno)

    return header_occurrences, key_lines


class StandardLoadError(Exception):
    """A standard file couldn't be read or parsed - the message is ready
    to print to stderr as-is; the caller exits 2."""


def load_standard(path: Path) -> tuple[str, dict[str, Any]]:
    """Read and parse the standard at `path`. Shared by validator.py's,
    runner.py's, and doc.py's `main()`, which otherwise each open, decode,
    and error-report the same file the same way."""
    try:
        raw_text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise StandardLoadError(f"{path} not found")

    try:
        with path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise StandardLoadError(f"{path} is not valid TOML: {e}")

    return raw_text, data


def build_validator(
    path: Path, raw_text: str, data: dict[str, Any], *, include_external: bool, bundled_rules_dir: Path | None
) -> "Validator":
    header_occurrences, key_lines = _index_source(raw_text)
    standard_dir = path.resolve().parent
    return Validator(
        data, standard_dir, header_occurrences, key_lines,
        include_external=include_external, bundled_rules_dir=bundled_rules_dir,
    )


def _split_location(location: str) -> list[str]:
    """Split a dotted location string on top-level dots, respecting
    double-quoted path segments (which may themselves contain no dots
    here, but keeping this quote-aware costs nothing and is future-safe)."""
    segments: list[str] = []
    current: list[str] = []
    in_quotes = False
    for ch in location:
        if ch == '"':
            in_quotes = not in_quotes
            current.append(ch)
        elif ch == "." and not in_quotes:
            segments.append("".join(current))
            current = []
        else:
            current.append(ch)
    segments.append("".join(current))
    return segments


def _resolve_line(
    location: str, header_occurrences: dict[str, list[int]], key_lines: dict[str, int]
) -> int | None:
    raw_segments = _split_location(location)
    index: int | None = None
    clean_segments: list[str] = []
    for seg in raw_segments:
        m = _INDEX_RE.match(seg)
        if m:
            clean_segments.append(m.group(1))
            index = int(m.group(2))
        else:
            clean_segments.append(seg)

    # try the longest header prefix first, then progressively shorter ones
    for end in range(len(clean_segments), 0, -1):
        header_text = ".".join(clean_segments[:end])
        lines = header_occurrences.get(header_text)
        if lines:
            if index is not None and index < len(lines):
                return lines[index]
            return lines[0]

    if clean_segments and clean_segments[0] in key_lines:
        return key_lines[clean_segments[0]]
    return None


def _classify_location(location: str) -> str:
    """Map an issue's dotted location to one of the categories used by
    --only and the summary table. Order matters: more specific prefixes
    (paths.cross, paths.rules, folders.rules) must be checked before the
    generic paths./folders./rules. fallbacks."""
    if location.startswith("paths.cross"):
        return "paths.cross"
    if location.startswith("paths.rules"):
        return "paths.rules"
    if location.startswith("paths"):
        return "paths"
    if location.startswith("folders.rules"):
        return "folders.rules"
    if location.startswith("folders"):
        return "folders"
    if location.startswith("rules"):
        return "rules"
    return "meta"  # root, meta.*, and anything else top-level


# ---------------------------------------------------------------------
# Issue reporting
# ---------------------------------------------------------------------

@dataclass
class Issue:
    level: str      # "error" | "warning"
    location: str   # dotted path into the TOML, e.g. paths."path/a/".lifecycle
    message: str
    line: int | None = None
    code: str = ""  # stable slug for warnings, usable with --ignore-warning
    kind: str = "validation"  # "validation" (schema/structural correctness) | "lint" (style/convention)


_COLOR = {"error": "\033[31m", "warning": "\033[33m", "reset": "\033[0m", "dim": "\033[2m"}


def _format_issue(issue: Issue, filename: str, color: bool) -> str:
    where = f"{filename}:{issue.line}" if issue.line is not None else filename
    tag = issue.level.upper()
    suffix = f" ({issue.code})" if issue.code else ""
    if color:
        c = _COLOR[issue.level]
        tag = f"{c}{tag}{_COLOR['reset']}"
        loc = f"{_COLOR['dim']}{issue.location}{_COLOR['reset']}"
    else:
        loc = issue.location
    return f"{where}: [{tag}] {loc}: {issue.message}{suffix}"


# All warning codes in use, with their kind and a short description - used
# for --help text, --list-warnings, and to decide --validate-only/--lint-only
# filtering; not enforced, so a typo'd --ignore-warning value just silently
# matches nothing rather than erroring.
WARNING_CODES = {
    "root-trailing-slash":         ("lint",       "root doesn't end with a trailing slash"),
    "version-format":              ("lint",       "schema_version/standard_version doesn't look like major.minor"),
    "no-paths":                    ("lint",       'no standardized [paths."..."] entries found'),
    "missing-path-attribute-list": ("validation", "the paths namespace declares no fields at all"),
    "path-trailing-slash":         ("lint",       "a path key doesn't end with a trailing slash"),
    "reserved-name-prefix":        ("lint",       "a reserved folder name doesn't start with `_`"),
    "unknown-path-field":          ("validation", "an entry has a field its namespace never declared"),
    "missing-grouping-enum":       ("validation", "a grouping field has no vocabulary under enums.<namespace>.<field>"),
    "empty-list-item":             ("lint",       "a list field has empty placeholder entries"),
    "unknown-param":               ("validation", "an attachment passes a param not declared in the rule manifest"),
    "rule-discovery-warning":      ("validation", "non-fatal issue found during rule discovery (collision, suspicious flag)"),
    "inherit-issue":               ("validation", "non-fatal issue resolving `inherit` (dead exclude_rules entry, etc.)"),
    "unknown-tag-field":           ("validation", "a tag namespace declares a key nothing reads"),
    "empty-tag-vocabulary":        ("validation", "a tag namespace declares no values"),
}

# What a [tags."<namespace>"] table may carry. `values` is the vocabulary
# itself; the rest describes it. Closed, and checked - a key nothing
# reads is a typo doing nothing, the same stance discovery takes on a
# rule manifest's fields.
TAG_NAMESPACE_KEYS = {"values", "multi", "description"}


# Which fields an entry may carry, which of them are required, and which
# are enum-backed all come from the standard itself - see
# fs_org_kit.fields. No field name is hardcoded here.

DEFAULT_RESERVED_PREFIX = "_"


class Validator:
    def __init__(
        self,
        data: dict[str, Any],
        standard_dir: Path,
        header_occurrences: dict[str, list[int]] | None = None,
        key_lines: dict[str, int] | None = None,
        include_external: bool = False,
        bundled_rules_dir: Path | None = None,
    ):
        self.data = data
        self.standard_dir = standard_dir
        self.include_external = include_external
        self.bundled_rules_dir = bundled_rules_dir
        self.header_occurrences = header_occurrences or {}
        self.key_lines = key_lines or {}
        self.issues: list[Issue] = []
        self.rule_catalog: dict[str, RuleEntry] = {}   # populated by _load_rule_catalog
        self.resolved_paths: dict[str, ResolvedEntry] = {}     # populated by _load_inheritance
        self.resolved_folders: dict[str, ResolvedEntry] = {}   # populated by _load_inheritance
        # what each namespace declares its entries may carry - parsed once
        # here, reused by the doc generator (see fs_org_kit.fields)
        self.path_fields = FieldSpec("paths")      # populated by _load_field_specs
        self.folder_fields = FieldSpec("folders")  # populated by _load_field_specs
        self.known_path_keys: set[str] = set()
        self.schema_major: int | None = None
        # category -> [(component_id, location_prefix), ...], used to build
        # the ok/warnings/broken summary by component type
        self.components: dict[str, list[tuple[str, str]]] = {}

    def _register(self, category: str, component_id: str, location_prefix: str) -> None:
        self.components.setdefault(category, []).append((component_id, location_prefix))

    # -- helpers ------------------------------------------------------

    def error(self, location: str, message: str, kind: str = "validation") -> None:
        line = _resolve_line(location, self.header_occurrences, self.key_lines)
        self.issues.append(Issue("error", location, message, line, kind=kind))

    def warning(self, location: str, message: str, code: str, kind: str | None = None) -> None:
        line = _resolve_line(location, self.header_occurrences, self.key_lines)
        resolved_kind = kind if kind is not None else WARNING_CODES.get(code, ("validation", ""))[0]
        self.issues.append(Issue("warning", location, message, line, code, resolved_kind))

    # -- entry point ----------------------------------------------------

    def run(self) -> list[Issue]:
        self._check_top_level()
        self._check_meta()
        if not self._schema_major_supported():
            # the grammar itself may have changed incompatibly - running
            # v1-shaped checks against a different major version would
            # likely just produce a flood of misleading noise, so stop here
            return self.issues
        self._load_field_specs()
        self._load_rule_catalog()
        self._load_inheritance()
        self._check_paths()
        self._check_folders()
        self._check_tags()
        return self.issues

    def _schema_major_supported(self) -> bool:
        return self.schema_major is None or self.schema_major == SUPPORTED_SCHEMA_MAJOR

    def summarize(self, issues: list[Issue] | None = None) -> dict[str, dict[str, int]]:
        """Roll issues up per component (one path, one cross-set, one rule,
        one reserved folder, ...) grouped by category, for the ok/warnings/
        broken breakdown printed at the end of a run. Pass a filtered issues
        list (e.g. after --ignore-warning/--only) to keep the table
        consistent with what was actually printed; defaults to everything
        this validator found."""
        pool = self.issues if issues is None else issues
        summary: dict[str, dict[str, int]] = {}
        for category, comps in self.components.items():
            counts = {"ok": 0, "ok_with_warnings": 0, "broken": 0, "total": len(comps)}
            for _component_id, prefix in comps:
                related = [
                    i for i in pool
                    if i.location == prefix or i.location.startswith((prefix + ".", prefix + "["))
                ]
                if any(i.level == "error" for i in related):
                    counts["broken"] += 1
                elif any(i.level == "warning" for i in related):
                    counts["ok_with_warnings"] += 1
                else:
                    counts["ok"] += 1
            summary[category] = counts
        return summary

    # -- top-level shape ------------------------------------------------

    def _check_top_level(self) -> None:
        required = ("root", "meta", "paths", "folders", "enums")
        for key in required:
            if key not in self.data:
                self.error(key, "required top-level table is missing")

        root = self.data.get("root")
        if root is not None:
            if not isinstance(root, str):
                self.error("root", "must be a string")
            elif not root.endswith("/"):
                self.warning("root", "expected a trailing slash, e.g. \"~/usr/\"", "root-trailing-slash")

    def _check_meta(self) -> None:
        meta = self.data.get("meta", {})
        versions: dict[str, tuple[int, ...] | None] = {}
        for field_name in ("schema_version", "standard_version"):
            value = meta.get(field_name)
            if value is None:
                self.error(f"meta.{field_name}", "missing")
                versions[field_name] = None
            elif not isinstance(value, str):
                self.error(f"meta.{field_name}", "must be a string, e.g. \"1.0\"")
                versions[field_name] = None
            else:
                parsed = _parse_version(value)
                if parsed is None:
                    self.warning(f"meta.{field_name}", f"'{value}' doesn't look like a major.minor version", "version-format")
                versions[field_name] = parsed

        for field_name in ("schema_date", "standard_date"):
            if field_name not in meta:
                self.error(f"meta.{field_name}", "missing")

        schema_v = versions.get("schema_version")
        standard_v = versions.get("standard_version")
        self.schema_major = schema_v[0] if schema_v is not None else None

        if schema_v is not None and standard_v is not None and schema_v[0] != standard_v[0]:
            self.error(
                "meta.standard_version",
                f"major version ({standard_v[0]}) doesn't match meta.schema_version's major version ({schema_v[0]})",
            )

        if self.schema_major is not None and self.schema_major != SUPPORTED_SCHEMA_MAJOR:
            self.error(
                "meta.schema_version",
                f"schema major version {self.schema_major} isn't supported by this validator "
                f"(supports major version {SUPPORTED_SCHEMA_MAJOR}) - skipping remaining checks",
            )

    # -- field declarations (attributes / grouping / enums) ------------------

    def _load_field_specs(self) -> None:
        """Read what each namespace says its entries may carry, before any
        entry is checked against it. Both namespaces are read the same way
        and independently - `folders` can declare a different set of fields
        from `paths` - though the vocabularies under `enums` are shared."""
        for namespace, attr in (("paths", "path_fields"), ("folders", "folder_fields")):
            spec, issues = parse_field_spec(self.data, namespace)
            setattr(self, attr, spec)
            for issue in issues:
                if issue.level == "error":
                    self.error(issue.location, issue.message)
                else:
                    self.warning(issue.location, issue.message, issue.code)

    # -- rule catalog (from discovery) -------------------------------------

    def _load_rule_catalog(self) -> None:
        """Run discovery and bridge the results into this validator's issue
        list. Discovery errors become validator errors; discovery warnings
        become validator warnings (ignorable with --ignore-warning
        rule-discovery-warning). After this runs, self.rule_catalog is
        populated and ready for _check_rule_instances calls."""
        catalog, disc_issues = discover_rules(
            self.standard_dir,
            bundled_rules_dir=self.bundled_rules_dir,
            include_external=self.include_external,
        )

        for di in disc_issues:
            location = f"rules.{di.rule_id}" if di.rule_id else "rules"
            if di.level == IssueLevel.ERROR:
                self.error(location, di.message)
            else:
                self.warning(location, di.message, "rule-discovery-warning")

        self.rule_catalog = catalog

    def _load_inheritance(self) -> None:
        """Resolve `inherit` and standard-wide defaults for [paths."..."]
        and [folders.reserved."..."] entries, populating self.resolved_paths
        / self.resolved_folders. Runs independently for each namespace -
        a path can only inherit from another path, a reserved folder entry
        only from another reserved folder entry."""
        paths = self.data.get("paths", {})
        path_entries = {k: v for k, v in paths.items() if k not in META_KEYS_UNDER_PATHS and isinstance(v, dict)}
        self.resolved_paths, path_issues = resolve_entries(path_entries, "paths")
        self._bridge_inherit_issues(path_issues, "paths")

        reserved = self.data.get("folders", {}).get("reserved", {})
        folder_entries = {k: v for k, v in reserved.items() if k not in META_KEYS_UNDER_RESERVED and isinstance(v, dict)}
        self.resolved_folders, folder_issues = resolve_entries(folder_entries, "folders.reserved")
        self._bridge_inherit_issues(folder_issues, 'folders.reserved')

    def _bridge_inherit_issues(self, issues: list[InheritIssue], loc_prefix: str) -> None:
        for issue in issues:
            loc = f'{loc_prefix}."{issue.key}"' if issue.key else loc_prefix
            if issue.level == "error":
                self.error(loc, issue.message)
            else:
                self.warning(loc, issue.message, "inherit-issue")

    # -- rule instances (attached under paths / folders / cross) --------------

    def _check_rule_instances(
        self, rules_table: Any, location: str, context: str = "single",
        component_category: str | None = None,
    ) -> None:
        if not isinstance(rules_table, dict):
            return

        for rule_name, instances in rules_table.items():
            loc = f"{location}.rules.{rule_name}"
            if rule_name not in self.rule_catalog:
                self.error(loc, f"rule `{rule_name}` not found in any rules tier (bundled, rules.own/, rules.external/)")
                continue

            entry: RuleEntry = self.rule_catalog[rule_name]

            if context == "single" and entry.scope not in ("single", "both"):
                self.error(loc, f"rule `{rule_name}` has scope `{entry.scope}` - can't be attached to a single path/folder")
            if context == "cross" and entry.scope not in ("cross", "both"):
                self.error(loc, f"rule `{rule_name}` has scope `{entry.scope}` - can't be attached under paths.cross")

            param_names = set(entry.params_names)
            required_params = param_names - set(entry.params_defaults)

            if not isinstance(instances, list):
                instances = [instances]

            for i, inst in enumerate(instances):
                inst_loc = f"{loc}[{i}]"
                if component_category:
                    self._register(component_category, f"{rule_name}[{i}]", inst_loc)
                self._check_instance(inst, inst_loc, rule_name, param_names, required_params)

    def _check_instance(
        self, inst: Any, inst_loc: str, rule_id: str, param_names: set[str], required_params: set[str]
    ) -> None:
        """The per-attachment body shared by `_check_rule_instances` (raw
        TOML) and `_check_resolved_rule_instances` (post-inheritance) -
        both need `reason`/`params` checked identically, so a divergence
        between the two callers would only be in how they get here, not
        in what "valid" means once they do."""
        if not isinstance(inst, dict):
            self.error(inst_loc, "expected a table")
            return

        if not inst.get("reason"):
            self.error(f"{inst_loc}.reason", "missing a non-empty `reason` (required at every attachment site)")

        inst_params = inst.get("params", {})
        if not isinstance(inst_params, dict):
            self.error(f"{inst_loc}.params", "expected a table")
            return

        for pname in inst_params:
            if pname not in param_names:
                self.warning(
                    f"{inst_loc}.params.{pname}",
                    f"`{pname}` is not declared in `{rule_id}`'s manifest params.names",
                    "unknown-param",
                )

        missing = required_params - set(inst_params)
        if missing:
            self.error(
                f"{inst_loc}.params",
                f"missing required param(s) with no default in `{rule_id}` manifest: {sorted(missing)}",
            )

        self._check_param_refs(inst_params, f"{inst_loc}.params")

    # -- paths ------------------------------------------------------------

    # -- pattern-key overlap (validation) ------------------------------------

    def _check_pattern_overlaps(self, keys: list[str], raw_paths: dict[str, Any]) -> None:
        """A glob-style [paths."..."] key (fs_org_kit.path_patterns) can
        match many real folders, sharing one entry's attributes/rules
        across all of them. Two catalog keys that could both match the
        same real folder is a structural problem - which entry's
        purpose/lifecycle/rules would actually apply is ambiguous - so
        it's an error here, not left for the runner to discover against
        real disk state (this check needs no filesystem access at all;
        see patterns_may_overlap's own docs for what "may overlap"
        means and its deliberately conservative approximation). Two
        purely literal keys are skipped entirely - distinct TOML keys
        can never collide, so there's nothing to check.

        A pattern overlapping another PATTERN is always an error -
        there's no inherent precedence between two wildcards, so which
        one's attributes/rules should win is genuinely ambiguous.

        A pattern overlapping a LITERAL is also an error, UNLESS that
        literal entry explicitly declares inherit.attributes,
        inherit.group or inherit.rules pointing at that exact pattern
        key - the
        deliberate, documented way to override one instance of a
        pattern's shared attributes/rules for a specific real folder
        (see doc/DESIGN.md). This mirrors overrides_bundled elsewhere
        in this project: a collision is rejected by default, and only
        an explicit, on-the-record reference opts out of that."""
        patterned = [k for k in keys if is_pattern(k)]
        if not patterned:
            return
        # Compared in normalized form (fs_org_kit.path_keys.comparison_key)
        # so an out-of-root key can't collide with a same-looking key under
        # root ("/etc/*/" vs "etc/*/"), while two spellings of the SAME
        # out-of-root place still do ("~/x/*/" vs "/home/me/x/*/").
        normalized = {k: comparison_key(k) for k in keys}
        for a, b in combinations(keys, 2):
            if not is_pattern(a) and not is_pattern(b):
                continue
            if not patterns_may_overlap(normalized[a], normalized[b]):
                continue
            if self._pattern_overlap_is_sanctioned(a, b, raw_paths):
                continue
            self.error(
                f'paths."{a}"',
                f'may match the same folder(s) as paths."{b}" - overlapping catalog entries would leave it '
                f"ambiguous which entry's fields/rules actually apply (a literal entry can override one "
                f"instance of a pattern via inherit.attributes/inherit.group/inherit.rules - "
                f"see doc/DESIGN.md)",
            )

    @staticmethod
    def _pattern_overlap_is_sanctioned(a: str, b: str, raw_paths: dict[str, Any]) -> bool:
        if is_pattern(a) and is_pattern(b):
            return False  # two patterns never have a sanctioned override
        literal, pattern = (b, a) if is_pattern(a) else (a, b)
        entry = raw_paths.get(literal, {})
        inherit = entry.get("inherit") if isinstance(entry, dict) else None
        if not isinstance(inherit, dict):
            return False
        return any(inherit.get(source) == pattern for source in (ATTRIBUTES, GROUP, RULES))

    def _check_paths(self) -> None:
        paths = self.data.get("paths", {})

        ordered_path_keys = [k for k in paths if k not in META_KEYS_UNDER_PATHS]
        self.known_path_keys = set(ordered_path_keys)
        if not self.known_path_keys:
            self.warning("paths", "no standardized path entries found", "no-paths")

        self._check_pattern_overlaps(ordered_path_keys, paths)

        self._check_rule_instances(paths.get("rules"), "paths", context="single", component_category="paths.rules")

        if not self.path_fields.is_declared():
            self.warning(
                "paths.attributes.names",
                "no fields declared for path entries (paths.attributes.names / "
                "paths.attributes.group.names) - can't check unknown fields",
                "missing-path-attribute-list",
            )

        for key in self.known_path_keys:
            entry = paths[key]
            loc = f'paths."{key}"'
            self._register("paths", key, loc)

            if not key.endswith("/"):
                self.warning(loc, "path keys should end with a trailing slash", "path-trailing-slash")

            if not isinstance(entry, dict):
                self.error(loc, "expected a table")
                continue

            self._check_entry_shape(entry, loc)

            # an entry carrying ONLY a `rules` table (and no `inherit`)
            # exists purely because TOML implicitly creates parent tables -
            # someone wrote [paths."<key>".rules.<rule-name>] without ever
            # declaring what the path is. That's a mistaken/misattached
            # rule, not an under-filled-out entry. An entry whose only
            # other content is `inherit` is different - a purely-inherited
            # entry is legitimate, its own fields all come from its source.
            resolved = self.resolved_paths.get(key)
            declared = bool(own_fields(entry, ATTRIBUTES)) or bool(own_fields(entry, GROUP))
            has_inherit = isinstance(entry.get("inherit"), dict) and bool(entry.get("inherit"))
            if not declared and not has_inherit:
                self.error(
                    loc,
                    f"path isn't declared - a rule is attached under paths.\"{key}\".rules, "
                    f"but nothing says what paths.\"{key}\" is",
                )
            else:
                self._check_entry_fields(entry, resolved, loc, self.path_fields)

            if resolved is not None:
                self._check_resolved_rule_instances(resolved.rules, loc, context="single")

        for i, cross in enumerate(paths.get("cross", [])):
            loc = f"paths.cross[{i}]"
            self._register("paths.cross", f"cross[{i}]", loc)
            referenced = cross.get("paths", [])
            # cross-path constraints may reference ANY path set, cataloged
            # or not - so we only check shape here, not membership against
            # the [paths."..."] catalog
            if not referenced:
                self.error(f"{loc}.paths", "list is empty")
            elif not all(isinstance(p, str) for p in referenced):
                self.error(f"{loc}.paths", "must be a list of path strings")
            self._check_rule_instances(cross.get("rules"), loc, context="cross")

    # -- folders ------------------------------------------------------------

    def _check_folders(self) -> None:
        folders = self.data.get("folders", {})
        self._check_rule_instances(folders.get("rules"), "folders", context="single", component_category="folders.rules")

        reserved = folders.get("reserved", {})
        reserved_prefix = reserved.get("prefix", DEFAULT_RESERVED_PREFIX)
        if not isinstance(reserved_prefix, str) or not reserved_prefix:
            self.error("folders.reserved.prefix", "must be a non-empty string")
            reserved_prefix = DEFAULT_RESERVED_PREFIX

        reserved_names = [k for k in reserved if k not in META_KEYS_UNDER_RESERVED]
        if reserved_names and not self.folder_fields.is_declared():
            # every field on these entries is then both unchecked and
            # unrendered - the generated docs would show the names alone
            self.warning(
                "folders.attributes.names",
                "reserved folder entries exist, but the folders namespace declares no fields "
                "(folders.attributes.names / folders.attributes.group.names)",
                "missing-path-attribute-list",
            )
        for name in reserved_names:
            entry = reserved[name]
            loc = f'folders.reserved."{name}"'
            self._register("folders", name, loc)
            if not name.startswith(reserved_prefix):
                self.warning(loc, f"reserved folder names are expected to start with '{reserved_prefix}'", "reserved-name-prefix")
            if not isinstance(entry, dict):
                self.error(loc, "expected a table")
                continue

            self._check_entry_shape(entry, loc)

            resolved = self.resolved_folders.get(name)
            self._check_entry_fields(entry, resolved, loc, self.folder_fields)

            if resolved is not None:
                self._check_resolved_rule_instances(resolved.rules, loc, context="single")

    # -- tags ----------------------------------------------------------------

    def _check_tags(self) -> None:
        """[tags."<ns>"] declares a vocabulary that things on disk carry -
        never a value, which is why nothing here looks at the filesystem.
        Checked about as lightly as [enums]: that a namespace has the
        shape a rule receiving it can rely on, and no more.

        [tags] is optional - a standard that tags nothing simply omits it.
        """
        tags = self.data.get("tags")
        if tags is None:
            return
        if not isinstance(tags, dict):
            self.error("tags", "expected a table of tag namespaces")
            return

        for namespace, declaration in tags.items():
            loc = f"tags.{namespace}"

            if isinstance(declaration, str):
                self.error(
                    loc,
                    "expected a table - a bare string here is the pre-2.1 flat glossary form; "
                    f'declare the vocabulary under [tags.{namespace}.values] instead',
                )
                continue
            if not isinstance(declaration, dict):
                self.error(loc, "expected a table")
                continue

            for key in sorted(set(declaration) - TAG_NAMESPACE_KEYS):
                self.warning(
                    f"{loc}.{key}",
                    f"nothing reads `{key}` (valid: {', '.join(sorted(TAG_NAMESPACE_KEYS))})",
                    "unknown-tag-field",
                )

            if "multi" in declaration and not isinstance(declaration["multi"], bool):
                self.error(f"{loc}.multi", "must be true or false")
            if "description" in declaration and not isinstance(declaration["description"], str):
                self.error(f"{loc}.description", "must be a string")

            values = declaration.get("values")
            if values is None or (isinstance(values, dict) and not values):
                self.warning(
                    f"{loc}.values",
                    "declares no values - a rule pointed at this namespace has nothing to check against",
                    "empty-tag-vocabulary",
                )
                continue
            if not isinstance(values, dict):
                self.error(f"{loc}.values", "expected a table of value = \"meaning\"")
                continue

            for value, meaning in values.items():
                if not isinstance(meaning, str):
                    self.error(f"{loc}.values.{value}", "must be a string describing what the value means")

    # -- inherit table shape ------------------------------------------------

    def _check_entry_shape(self, entry: dict[str, Any], loc: str) -> None:
        """`group`, `rules` and `inherit` are an entry's structural keys;
        everything else on it is a documentation field, checked against
        the declaration elsewhere."""
        for key in STRUCTURAL_KEYS:
            if key in entry and not isinstance(entry[key], dict):
                self.error(f"{loc}.{key}", "expected a table")

        inherit = entry.get("inherit")
        if inherit is None or not isinstance(inherit, dict):
            return
        known_keys = {ATTRIBUTES, GROUP, RULES, "exclude_rules"}
        for key in inherit:
            if key not in known_keys:
                self.warning(
                    f"{loc}.inherit.{key}",
                    "field isn't a recognized `inherit` key (doc/group/rules/exclude_rules)",
                    "unknown-path-field",
                )

    # -- resolved rule instances (attached to a path or reserved folder,
    #    after inheritance has already been flattened) ----------------------

    def _check_resolved_rule_instances(
        self, resolved_rules: dict[str, list[RuleAttachment]], location: str, context: str
    ) -> None:
        for rule_id, attachments in resolved_rules.items():
            loc = f"{location}.rules.{rule_id}"
            if rule_id not in self.rule_catalog:
                self.error(loc, f"rule `{rule_id}` not found in any rules tier (bundled, rules.own/, rules.external/)")
                continue

            entry: RuleEntry = self.rule_catalog[rule_id]

            if context == "single" and entry.scope not in ("single", "both"):
                self.error(loc, f"rule `{rule_id}` has scope `{entry.scope}` - can't be attached to a single path/folder")

            param_names = set(entry.params_names)
            required_params = param_names - set(entry.params_defaults)

            for i, attachment in enumerate(attachments):
                origin_note = f' (inherited from "{attachment.origin_key}")' if attachment.origin_key else ""
                inst_loc = f"{loc}[{i}]{origin_note}"
                self._check_instance(attachment.instance, inst_loc, rule_id, param_names, required_params)

    def _check_param_refs(self, inst_params: dict[str, Any], loc: str) -> None:
        """A param value may be {ref = "dotted.path"} instead of a
        literal - see fs_org_kit.param_refs. Catches a broken/misshapen
        reference here, at validate-time, rather than letting the
        runner discover it only once it's about to build a rule's JSON
        payload."""
        _, ref_errors = expand_params(inst_params, self.data)
        for err in ref_errors:
            self.error(loc, err)

    # -- shared entry-field checks (paths + reserved folders) ------------------

    def _check_entry_fields(
        self, raw_entry: dict[str, Any], resolved: ResolvedEntry | None, loc: str, spec: FieldSpec
    ) -> None:
        """Each of an entry's three tables is checked against what its
        namespace declared for it - see fs_org_kit.fields. Values come
        from the RESOLVED entry (inheritance and defaults already
        applied); the raw entry is only consulted for what was written
        where."""
        resolved_by_kind = {
            ATTRIBUTES: resolved.attributes if resolved else {},
            GROUP: resolved.group if resolved else {},
        }

        for kind in (ATTRIBUTES, GROUP):
            declared = set(spec.names(kind))
            if spec.is_declared():
                for field_name in own_fields(raw_entry, kind):
                    if field_name not in declared:
                        self.warning(
                            f"{self._field_loc(loc, kind, field_name)}",
                            f"field isn't declared in {spec.declaration_location(kind)}",
                            "unknown-path-field",
                        )

            values = resolved_by_kind[kind]
            for field_name in spec.names(kind):
                if field_name in spec.required(kind) and not values.get(field_name):
                    self.error(
                        self._field_loc(loc, kind, field_name),
                        "required field is empty or missing, even after inheritance",
                    )
                if kind == ATTRIBUTES:
                    self._check_attribute_field(values.get(field_name), field_name, loc, spec)
                else:
                    self._check_grouping_field(values.get(field_name), field_name, loc, spec)

    @staticmethod
    def _field_loc(loc: str, kind: str, field_name: str) -> str:
        """Documentation fields sit directly on the entry; grouping fields
        sit in its `group` table - the reported location follows."""
        return f"{loc}.{field_name}" if kind == ATTRIBUTES else f"{loc}.{kind}.{field_name}"

    def _check_attribute_field(self, value: Any, field_name: str, loc: str, spec: FieldSpec) -> None:
        """A documentation field is free-form prose - nothing reads its
        value, so the only structural claim worth making is that it's
        renderable: a string, or a list of strings. A standard may still
        close its value set by declaring one under `enums.attributes.<field>`."""
        if value is None:
            return  # requiredness is checked separately, from the declaration
        field_loc = self._field_loc(loc, ATTRIBUTES, field_name)

        if isinstance(value, str):
            values = [value]
        elif isinstance(value, list) and all(isinstance(item, str) for item in value):
            values = value
            if any(not item for item in value):
                self.warning(field_loc, "contains empty placeholder entries", "empty-list-item")
        else:
            self.error(field_loc, "must be a string or a list of strings")
            return

        allowed = spec.attribute_values.get(field_name)
        if not allowed:
            return
        enum_loc = spec.enum_location(ATTRIBUTES, field_name)
        for item in values:
            if item and item not in allowed:
                self.error(field_loc, f"'{item}' is not a value in {enum_loc}")

    def _check_grouping_field(self, value: Any, field_name: str, loc: str, spec: FieldSpec) -> None:
        """A grouping field's whole point is a closed vocabulary - entries
        only sort into buckets if they agree on what the buckets are. A
        field declared in `<namespace>.group.multi` holds a LIST of values
        (content that's partly self-authored and partly generated, say);
        every other one holds exactly one."""
        if value is None:
            return  # requiredness is checked separately, from the declaration

        field_loc = self._field_loc(loc, GROUP, field_name)
        enum_loc = spec.enum_location(GROUP, field_name)
        allowed = spec.group_values.get(field_name, frozenset())

        if spec.is_multi(field_name):
            if not isinstance(value, list):
                self.error(field_loc, f'must be a list of values from {enum_loc}, e.g. ["self"]')
                return
            values = value
        else:
            if isinstance(value, list):
                self.error(
                    field_loc,
                    f"must be a single value from {enum_loc} - add it to {spec.namespace}.group.multi "
                    f"to allow several",
                )
                return
            values = [value]

        for item in values:
            if not isinstance(item, str):
                self.error(field_loc, f"'{item}' should be a string from {enum_loc}")
            elif allowed and item not in allowed:
                self.error(field_loc, f"'{item}' is not a value in {enum_loc}")


def _parse_version(value: str) -> tuple[int, ...] | None:
    parts = value.split(".")
    if len(parts) < 2 or not all(p.isdigit() for p in parts):
        return None
    return tuple(int(p) for p in parts)


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

CATEGORY_LABELS = {
    "paths":         "paths",
    "paths.rules":   "path rules (blanket)",
    "paths.cross":   "cross-path sets",
    "folders":       "reserved folders",
    "folders.rules": "folder rules (blanket)",
}
CATEGORY_ORDER = ("paths", "paths.rules", "paths.cross", "folders", "folders.rules")
KNOWN_CATEGORIES = (*CATEGORY_ORDER, "meta")


def _parse_comma_list(raw: list[str] | None) -> set[str] | None:
    if not raw:
        return None
    result: set[str] = set()
    for item in raw:
        for part in item.split(","):
            part = part.strip()
            if part:
                result.add(part)
    return result


def _print_summary_table(validator: Validator, issues: list[Issue], only: set[str] | None, color: bool) -> None:
    summary = validator.summarize(issues)
    if not summary:
        return

    columns = ["Category", "OK", "Warn", "Broken", "Total"]
    rows = []
    for category in CATEGORY_ORDER:
        if category not in summary:
            continue
        if only is not None and category not in only:
            continue
        counts = summary[category]
        rows.append([
            CATEGORY_LABELS.get(category, category),
            str(counts["ok"]),
            str(counts["ok_with_warnings"]),
            str(counts["broken"]),
            str(counts["total"]),
        ])
    if not rows:
        return

    widths = [max(len(columns[c]), *(len(row[c]) for row in rows)) for c in range(len(columns))]

    def fmt_row(cells: list[str]) -> str:
        padded = [cells[0].ljust(widths[0])] + [cells[c].rjust(widths[c]) for c in range(1, len(cells))]
        return "  ".join(padded)

    print("Summary")
    print(fmt_row(columns))
    print("  ".join("-" * w for w in widths))
    for row in rows:
        if color and row[3] != "0":
            broken_col = f"{_COLOR['error']}{row[3].rjust(widths[3])}{_COLOR['reset']}"
            line = "  ".join(
                [row[0].ljust(widths[0]), row[1].rjust(widths[1]), row[2].rjust(widths[2]), broken_col, row[4].rjust(widths[4])]
            )
            print(line)
        else:
            print(fmt_row(row))
    print()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("path", type=Path, help="path to a TOML file to check against the fs-org-std standard")
    parser.add_argument("--strict", action="store_true", help="treat warnings as errors for the exit code")
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument("--no-warnings", action="store_true", help="don't print individual warning lines")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--validate-only", action="store_true",
        help="only run structural/schema checks (required fields, enums, rule references, "
             "scope, params, versions) - skips style/convention checks",
    )
    mode.add_argument(
        "--lint-only", action="store_true",
        help="only run style/convention checks (path key slashes, reserved-name prefix, "
             "empty placeholder entries, ...) - skips structural/schema checks",
    )
    parser.add_argument(
        "--only", action="append", metavar="CATEGORY",
        help=f"only check/report these categories (repeatable, or comma-separated): {', '.join(KNOWN_CATEGORIES)}",
    )
    parser.add_argument(
        "--ignore-warning", action="append", metavar="CODE",
        help="fully ignore warnings with this code (repeatable, or comma-separated); "
             "see the docstring or --list-warnings for the full code list",
    )
    parser.add_argument("--list-warnings", action="store_true", help="print all warning codes and exit")
    parser.add_argument("--include-external", action="store_true", help="also discover rules.external/ (never included by default)")
    parser.add_argument("--rules-dir", type=Path, default=None, help="override where bundled rules are discovered from")
    args = parser.parse_args(argv)

    if args.list_warnings:
        for code, (kind, desc) in sorted(WARNING_CODES.items()):
            print(f"{code:28} [{kind:10}] {desc}")
        return 0

    only = _parse_comma_list(args.only)
    if only is not None:
        unknown = only - set(KNOWN_CATEGORIES)
        if unknown:
            print(f"error: unknown categor{'y' if len(unknown) == 1 else 'ies'}: {', '.join(sorted(unknown))}", file=sys.stderr)
            print(f"       known categories: {', '.join(KNOWN_CATEGORIES)}", file=sys.stderr)
            return 2

    ignore_codes = _parse_comma_list(args.ignore_warning) or set()

    try:
        raw_text, data = load_standard(args.path)
    except StandardLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    validator = build_validator(
        args.path, raw_text, data, include_external=args.include_external, bundled_rules_dir=args.rules_dir,
    )
    issues = validator.run()

    # --validate-only / --lint-only filter by kind, same spot as --only
    # and --ignore-warning so the printed list, counts, and summary table
    # all stay consistent with each other
    if args.validate_only:
        issues = [i for i in issues if i.kind == "validation"]
    elif args.lint_only:
        issues = [i for i in issues if i.kind == "lint"]

    # --ignore-warning drops issues entirely: not printed, not counted,
    # not reflected in the summary table
    if ignore_codes:
        issues = [i for i in issues if not (i.level == "warning" and i.code in ignore_codes)]

    # --only filters by category, also affecting printing/counting/summary
    if only is not None:
        issues = [i for i in issues if _classify_location(i.location) in only]

    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    color = not args.no_color and sys.stdout.isatty() and not os.environ.get("NO_COLOR")

    # --no-warnings only affects what's PRINTED line-by-line - the summary
    # table and the warning count below still reflect the real state
    to_print = [i for i in issues if not (args.no_warnings and i.level == "warning")]

    # read top-to-bottom like the file itself: by line, then location text;
    # issues with no resolved line (rare) sort last
    def sort_key(issue: Issue) -> tuple[int, str]:
        return (issue.line if issue.line is not None else 10**9, issue.location)

    for issue in sorted(to_print, key=sort_key):
        print(_format_issue(issue, str(args.path), color))

    print()
    _print_summary_table(validator, issues, only, color)

    summary = f"{len(errors)} error(s), {len(warnings)} warning(s)"
    print(f"{_COLOR['dim']}{summary}{_COLOR['reset']}" if color else summary)

    if errors or (args.strict and warnings):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
