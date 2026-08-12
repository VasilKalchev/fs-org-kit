#!/usr/bin/env python3
"""
doc.py - validates a populated standard, then generates Markdown
documentation from it: table of contents, one section per part of the
standard, and (optionally) Mermaid diagrams.

Usage:
    python -m fs_org_kit.doc path/to/your-file.toml
    python -m fs_org_kit.doc path/to/your-file.toml --output docs/standard.md
    python -m fs_org_kit.doc path/to/your-file.toml --sections overview,paths,rules
    python -m fs_org_kit.doc path/to/your-file.toml --no-diagrams
    python -m fs_org_kit.doc path/to/your-file.toml --diagrams tree,rules

Documents the RESOLVED standard, not the raw TOML - an inherited
`purpose` shows up with its actual value, marked as inherited, not
blank. This reuses fs_org_kit.validator directly (its resolved_paths /
resolved_folders / rule_catalog), the same way the runner does, rather
than re-parsing inheritance or re-running discovery itself.

Validates first and aborts on any validation error (exit 2) - same
stance the runner takes. Documenting a standard that doesn't validate
would produce confidently-wrong output: a rules table listing rules
that don't actually resolve, an inheritance note citing an undefined
parent. Validation warnings don't block, but go to stderr so they can't
corrupt piped stdout.

Exit codes:
    0  generated fine
    2  the standard is unreadable or has validation errors
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # Python < 3.11
    import tomli as tomllib  # type: ignore[no-redef]

from fs_org_kit.discovery import RuleEntry
from fs_org_kit.inherit import ResolvedEntry, RuleAttachment
from fs_org_kit.validator import Validator, _index_source

ALL_SECTIONS = ("overview", "paths", "cross", "folders", "rules", "enums", "abbreviations", "tags")
ALL_DIAGRAMS = ("tree", "lifecycle", "rules", "cross")
MERMAID_NODE_LIMIT = 40
KNOWN_LIFECYCLE_ORDER = ("transient", "temporary", "ongoing", "archival")


# ---------------------------------------------------------------------
# Slugs / anchors
#
# Explicit <a id="..."> anchors are emitted before every heading rather
# than relying on a renderer's auto-slugify of heading text - that way
# ToC links work identically everywhere (GitHub, VS Code preview, a
# plain markdown-to-html pipeline), not just renderers that happen to
# slugify the same way GitHub does.
#
# Because anchors are explicit, there's no need to mimic GitHub's exact
# slug algorithm either. Every anchor is prefixed by its section kind
# (slug_for("path", key) -> "path-..."), which makes collisions between
# DIFFERENT sections structurally impossible, and within one section
# collisions are already rare (path keys, rule ids, and folder names
# are each unique within their own namespace). A residual, very unlikely
# case - two path keys that both slugify to the same string once
# slashes/punctuation are stripped - isn't defended against with a
# dedup counter; this is documentation, not a safety-critical index, and
# doing so would require a two-pass registry to keep cross-references
# correct regardless of render order. Noted here rather than silently
# assumed away.
# ---------------------------------------------------------------------

def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[/_\s]+", "-", text)
    text = re.sub(r"[^a-z0-9-]", "", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return text or "section"


def slug_for(prefix: str, name: str) -> str:
    return _slugify(f"{prefix}-{name}")


def _format_value(v: Any) -> str:
    """Render a Python value (from parsed TOML) the way it would look
    written in TOML, not Python's repr - a reader of the generated docs
    is also a reader of the actual TOML file, so `true`/`[]` matches
    what they already know, where `True`/Py-repr would look foreign."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, str):
        return f'"{v}"' if v else '""'
    if isinstance(v, list):
        return "[" + ", ".join(_format_value(x) for x in v) + "]"
    return str(v)


def link(text: str, slug: str | None) -> str:
    return f"[{text}](#{slug})" if slug else text


# ---------------------------------------------------------------------
# Rule attachment reverse index
# ---------------------------------------------------------------------

@dataclass
class RuleAttachmentSite:
    rule_id: str
    location_label: str
    location_slug: str | None
    reason: str
    params: dict[str, Any]
    origin_key: str | None = None


def collect_rule_sites(
    data: dict[str, Any],
    resolved_paths: dict[str, ResolvedEntry],
    resolved_folders: dict[str, ResolvedEntry],
) -> dict[str, list[RuleAttachmentSite]]:
    sites: dict[str, list[RuleAttachmentSite]] = {}

    def add(rule_id: str, label: str, slug: str | None, inst: dict[str, Any], origin_key: str | None = None) -> None:
        sites.setdefault(rule_id, []).append(
            RuleAttachmentSite(rule_id, label, slug, inst.get("reason", ""), inst.get("params", {}), origin_key)
        )

    def add_raw_table(table: Any, label: str, slug: str | None) -> None:
        if not isinstance(table, dict):
            return
        for rule_id, instances in table.items():
            if not isinstance(instances, list):
                instances = [instances]
            for inst in instances:
                if isinstance(inst, dict):
                    add(rule_id, label, slug, inst)

    for key, resolved in resolved_paths.items():
        for rule_id, attachments in resolved.rules.items():
            for a in attachments:
                add(rule_id, key, slug_for("path", key), a.instance, a.origin_key)

    paths = data.get("paths", {})
    add_raw_table(paths.get("rules"), "every cataloged path (blanket)", None)

    for i, cross in enumerate(paths.get("cross", [])):
        if isinstance(cross, dict):
            add_raw_table(cross.get("rules"), f"Cross-Path Set {i + 1}", slug_for("cross", str(i + 1)))

    for name, resolved in resolved_folders.items():
        for rule_id, attachments in resolved.rules.items():
            for a in attachments:
                add(rule_id, f"folders.reserved.\"{name}\"", slug_for("folder", name), a.instance, a.origin_key)

    add_raw_table(data.get("folders", {}).get("rules"), "every folder under root (blanket)", None)

    return sites


# ---------------------------------------------------------------------
# Mermaid diagrams
# ---------------------------------------------------------------------

def _mermaid_escape(text: str) -> str:
    return text.replace('"', "'").replace("[", "(").replace("]", ")")


def _path_parent_key(key: str) -> str:
    trimmed = key.rstrip("/")
    if "/" not in trimmed:
        return ""
    return trimmed.rsplit("/", 1)[0] + "/"


def build_tree_diagram(resolved_paths: dict[str, ResolvedEntry]) -> str | None:
    keys = sorted(resolved_paths.keys())
    if not keys or len(keys) > MERMAID_NODE_LIMIT:
        return None

    node_id = {k: f"n{i}" for i, k in enumerate(keys)}
    lines = ["```mermaid", "graph TD", '    root["(root)"]']
    for k in keys:
        lines.append(f'    {node_id[k]}["{_mermaid_escape(k)}"]')
    for k in keys:
        parent = _path_parent_key(k)
        target = node_id.get(parent, "root")
        lines.append(f"    {target} --> {node_id[k]}")
    lines.append("```")
    return "\n".join(lines)


def build_lifecycle_diagram(lifecycle_enum: dict[str, Any]) -> str | None:
    if set(lifecycle_enum.keys()) != set(KNOWN_LIFECYCLE_ORDER):
        return None
    lines = ["```mermaid", "graph LR"]
    for i, val in enumerate(KNOWN_LIFECYCLE_ORDER):
        lines.append(f'    l{i}["{val}"]')
    for i in range(len(KNOWN_LIFECYCLE_ORDER) - 1):
        lines.append(f"    l{i} --> l{i + 1}")
    lines.append("```")
    return "\n".join(lines)


def build_rules_diagram(sites_by_rule: dict[str, list[RuleAttachmentSite]]) -> str | None:
    if not sites_by_rule:
        return None
    rule_ids = sorted(sites_by_rule.keys())
    unique_sites = sorted({s.location_label for sites in sites_by_rule.values() for s in sites})
    if len(rule_ids) + len(unique_sites) > MERMAID_NODE_LIMIT:
        return None

    rule_node = {r: f"r{i}" for i, r in enumerate(rule_ids)}
    site_node = {s: f"s{i}" for i, s in enumerate(unique_sites)}
    lines = ["```mermaid", "graph LR"]
    for r in rule_ids:
        lines.append(f'    {rule_node[r]}["{_mermaid_escape(r)}"]')
    for s in unique_sites:
        lines.append(f'    {site_node[s]}("{_mermaid_escape(s)}")')

    seen = set()
    for rid in rule_ids:
        for site in sites_by_rule[rid]:
            edge = (rule_node[rid], site_node[site.location_label])
            if edge not in seen:
                seen.add(edge)
                lines.append(f"    {rule_node[rid]} --- {site_node[site.location_label]}")
    lines.append("```")
    return "\n".join(lines)


def build_cross_diagram(cross: dict[str, Any], index: int) -> str | None:
    members = cross.get("paths", [])
    if not isinstance(members, list) or not members:
        return None
    lines = ["```mermaid", "graph LR", f'    cs["Set {index + 1}"]']
    for i, m in enumerate(members):
        if not isinstance(m, str):
            continue
        lines.append(f'    m{i}["{_mermaid_escape(m)}"]')
        lines.append(f"    cs --- m{i}")
    lines.append("```")
    return "\n".join(lines)


# ---------------------------------------------------------------------
# Doc builder
# ---------------------------------------------------------------------

class DocBuilder:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.toc_entries: list[tuple[int, str, str]] = []

    def heading(self, level: int, title: str, slug: str, in_toc: bool = True) -> None:
        self.lines.append(f'<a id="{slug}"></a>')
        self.lines.append(f"{'#' * level} {title}")
        self.lines.append("")
        if in_toc:
            self.toc_entries.append((level, title, slug))

    def line(self, text: str = "") -> None:
        self.lines.append(text)

    def render_toc(self) -> list[str]:
        if not self.toc_entries:
            return []
        out = ["## Table of Contents", ""]
        base_level = min(lvl for lvl, _, _ in self.toc_entries)
        for level, title, slug in self.toc_entries:
            indent = "  " * (level - base_level)
            out.append(f"{indent}- [{title}](#{slug})")
        out.append("")
        return out


# ---------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------

def render_overview(b: DocBuilder, data: dict[str, Any], resolved_paths: dict, diagrams: set[str]) -> None:
    b.heading(2, "Overview", slug_for("section", "overview"))
    meta = data.get("meta", {})
    root = data.get("root", "")

    b.line(f"- **Root**: `{root}`")
    if meta.get("description"):
        b.line(f"- {meta['description']}")
    b.line(f"- **Schema version**: {meta.get('schema_version', '?')} ({meta.get('schema_date', '?')})")
    b.line(f"- **Standard version**: {meta.get('standard_version', '?')} ({meta.get('standard_date', '?')})")
    b.line(f"- **Cataloged paths**: {len(resolved_paths)}")
    paths_cross = data.get("paths", {}).get("cross", [])
    b.line(f"- **Cross-path sets**: {len(paths_cross) if isinstance(paths_cross, list) else 0}")
    reserved = data.get("folders", {}).get("reserved", {})
    reserved_count = len([k for k in reserved if k != "prefix"]) if isinstance(reserved, dict) else 0
    b.line(f"- **Reserved folders**: {reserved_count}")
    b.line()

    if "tree" in diagrams:
        diagram = build_tree_diagram(resolved_paths)
        if diagram:
            b.line("**Path hierarchy:**")
            b.line()
            b.line(diagram)
            b.line()
        elif len(resolved_paths) > MERMAID_NODE_LIMIT:
            b.line(f"*(path hierarchy diagram skipped - {len(resolved_paths)} paths exceeds the {MERMAID_NODE_LIMIT}-node readability limit)*")
            b.line()


def _render_attribute_table(b: DocBuilder, resolved: ResolvedEntry, raw: dict[str, Any]) -> None:
    attrs = resolved.attributes
    inherited_from = raw.get("inherit", {}).get("attributes") if isinstance(raw.get("inherit"), dict) else None

    def marker(field_name: str) -> str:
        if inherited_from and field_name not in raw:
            return f" *(inherited from `{inherited_from}`)*"
        return ""

    rows = []
    if attrs.get("purpose"):
        rows.append(("Purpose", attrs["purpose"] + marker("purpose")))
    if attrs.get("notes"):
        rows.append(("Notes", attrs["notes"] + marker("notes")))
    if attrs.get("lifecycle"):
        rows.append(("Lifecycle", f"[`{attrs['lifecycle']}`](#{slug_for('section', 'enums')}){marker('lifecycle')}"))
    if attrs.get("origin"):
        origin_str = ", ".join(f"`{o}`" for o in attrs["origin"])
        rows.append(("Origin", f"{origin_str}{marker('origin')}"))
    if attrs.get("see_also"):
        # a list of catalog keys, or a single one as a bare string - both
        # shapes are in the wild, and a list must not reach the table as
        # its Python repr
        see_also = attrs["see_also"]
        if isinstance(see_also, list):
            see_also = ", ".join(f"`{s}`" for s in see_also if s)
        if see_also:
            rows.append(("See also", see_also))
    if attrs.get("allow_missing"):
        rows.append(("May be missing", "yes"))
    if attrs.get("outside_root"):
        rows.append(("Outside root", "yes - this entry deliberately points outside the governed tree"))

    if rows:
        b.line("| Field | Value |")
        b.line("|---|---|")
        for label, value in rows:
            b.line(f"| {label} | {value} |")
        b.line()

    for label, field_name in (("Use for", "use_for"), ("Not for", "not_for")):
        values = [v for v in attrs.get(field_name, []) if v]
        if values:
            b.line(f"**{label}:**")
            for v in values:
                b.line(f"- {v}")
            b.line()


def _render_rule_attachments(b: DocBuilder, resolved: ResolvedEntry) -> None:
    if not resolved.rules:
        return
    b.line("**Attached rules:**")
    b.line()
    b.line("| Rule | Reason | Params |")
    b.line("|---|---|---|")
    for rule_id, attachments in sorted(resolved.rules.items()):
        rule_slug = slug_for("rule", rule_id)
        for a in attachments:
            reason = a.instance.get("reason", "")
            params = a.instance.get("params", {})
            params_str = ", ".join(f"`{k}={_format_value(v)}`" for k, v in params.items()) if params else ""
            origin_note = f" *(inherited from `{a.origin_key}`)*" if a.origin_key else ""
            b.line(f"| {link(f'`{rule_id}`', rule_slug)}{origin_note} | {reason} | {params_str} |")
    b.line()


def render_paths(b: DocBuilder, resolved_paths: dict[str, ResolvedEntry]) -> None:
    if not resolved_paths:
        return
    b.heading(2, "Paths", slug_for("section", "paths"))
    for key in sorted(resolved_paths.keys()):
        resolved = resolved_paths[key]
        b.heading(3, f"`{key}`", slug_for("path", key))
        _render_attribute_table(b, resolved, resolved.raw)
        _render_rule_attachments(b, resolved)


def render_cross(b: DocBuilder, data: dict[str, Any], diagrams: set[str]) -> None:
    paths = data.get("paths", {})
    cross_sets = paths.get("cross", [])
    if not isinstance(cross_sets, list) or not cross_sets:
        return
    b.heading(2, "Cross-Path Sets", slug_for("section", "cross"))
    for i, cross in enumerate(cross_sets):
        if not isinstance(cross, dict):
            continue
        b.heading(3, f"Set {i + 1}", slug_for("cross", str(i + 1)))
        members = cross.get("paths", [])
        if members:
            member_links = ", ".join(link(f"`{m}`", slug_for("path", m)) for m in members)
            b.line(f"**Members**: {member_links}")
            b.line()

        if "cross" in diagrams:
            diagram = build_cross_diagram(cross, i)
            if diagram:
                b.line(diagram)
                b.line()

        rules_table = cross.get("rules", {})
        if isinstance(rules_table, dict) and rules_table:
            b.line("**Attached rules:**")
            b.line()
            b.line("| Rule | Reason | Params |")
            b.line("|---|---|---|")
            for rule_id, instances in sorted(rules_table.items()):
                if not isinstance(instances, list):
                    instances = [instances]
                rule_slug = slug_for("rule", rule_id)
                for inst in instances:
                    if not isinstance(inst, dict):
                        continue
                    reason = inst.get("reason", "")
                    params = inst.get("params", {})
                    params_str = ", ".join(f"`{k}={_format_value(v)}`" for k, v in params.items()) if params else ""
                    b.line(f"| {link(f'`{rule_id}`', rule_slug)} | {reason} | {params_str} |")
            b.line()


def render_folders(b: DocBuilder, data: dict[str, Any], resolved_folders: dict[str, ResolvedEntry]) -> None:
    if not resolved_folders:
        return
    b.heading(2, "Reserved Folders", slug_for("section", "folders"))
    reserved = data.get("folders", {}).get("reserved", {})
    prefix = reserved.get("prefix", "_") if isinstance(reserved, dict) else "_"
    b.line(f"Reserved-name prefix: `{prefix}`")
    b.line()
    for name in sorted(resolved_folders.keys()):
        resolved = resolved_folders[name]
        b.heading(3, f"`{name}`", slug_for("folder", name))
        _render_attribute_table(b, resolved, resolved.raw)
        _render_rule_attachments(b, resolved)


def render_rules(b: DocBuilder, rule_catalog: dict[str, RuleEntry], sites_by_rule: dict[str, list[RuleAttachmentSite]], diagrams: set[str]) -> None:
    attached_ids = sorted(sites_by_rule.keys())
    if not attached_ids:
        return
    b.heading(2, "Rules", slug_for("section", "rules"))

    if "rules" in diagrams:
        diagram = build_rules_diagram(sites_by_rule)
        if diagram:
            b.line(diagram)
            b.line()

    for rule_id in attached_ids:
        b.heading(3, f"`{rule_id}`", slug_for("rule", rule_id))
        entry = rule_catalog.get(rule_id)
        if entry is None:
            b.line("*(not found in the discovered rule catalog)*")
            b.line()
            continue

        b.line(f"{entry.purpose}" if entry.purpose else "*(no purpose documented)*")
        b.line()
        b.line("| | |")
        b.line("|---|---|")
        b.line(f"| Tier | {entry.tier.value} |")
        b.line(f"| Version | {entry.version} |")
        b.line(f"| Severity | `{entry.severity}` |")
        b.line(f"| Scope | `{entry.scope}` |")
        b.line(f"| Fixable | {'yes' if entry.has_fixer else 'no'} |")
        b.line()

        if entry.params_names:
            b.line("**Params:**")
            b.line()
            b.line("| Name | Default | Required |")
            b.line("|---|---|---|")
            for pname in entry.params_names:
                has_default = pname in entry.params_defaults
                default_str = f"`{_format_value(entry.params_defaults[pname])}`" if has_default else ""
                required = "no" if has_default else "yes"
                b.line(f"| `{pname}` | {default_str} | {required} |")
            b.line()

        sites = sites_by_rule[rule_id]
        b.line(f"**Attached at {len(sites)} location(s):**")
        b.line()
        for site in sorted(sites, key=lambda s: s.location_label):
            origin_note = f" *(inherited from `{site.origin_key}`)*" if site.origin_key else ""
            b.line(f"- {link(f'`{site.location_label}`', site.location_slug)}{origin_note} - {site.reason}")
        b.line()


def render_enums(b: DocBuilder, data: dict[str, Any], diagrams: set[str]) -> None:
    enums = data.get("enums", {})
    paths_enums = enums.get("paths", {})
    lifecycle = paths_enums.get("lifecycle", {})
    origin = paths_enums.get("origin", {})
    if not lifecycle and not origin:
        return

    b.heading(2, "Enums", slug_for("section", "enums"))

    if lifecycle:
        b.line("**Lifecycle:**")
        b.line()
        b.line("| Value | Meaning |")
        b.line("|---|---|")
        for val, desc in lifecycle.items():
            b.line(f"| `{val}` | {desc} |")
        b.line()
        if "lifecycle" in diagrams:
            diagram = build_lifecycle_diagram(lifecycle)
            if diagram:
                b.line(diagram)
                b.line()

    if origin:
        b.line("**Origin:**")
        b.line()
        b.line("| Value | Meaning |")
        b.line("|---|---|")
        for val, desc in origin.items():
            b.line(f"| `{val}` | {desc} |")
        b.line()


def render_abbreviations(b: DocBuilder, data: dict[str, Any]) -> None:
    abbreviations = data.get("abbreviations", {})
    if not isinstance(abbreviations, dict) or not abbreviations:
        return
    b.heading(2, "Abbreviations", slug_for("section", "abbreviations"))
    b.line("| Abbreviation | Meaning |")
    b.line("|---|---|")
    for k in sorted(abbreviations.keys(), key=str.lower):
        b.line(f"| `{k}` | {abbreviations[k]} |")
    b.line()


def render_tags(b: DocBuilder, data: dict[str, Any]) -> None:
    tags = data.get("tags", {})
    if not isinstance(tags, dict) or not tags:
        return
    b.heading(2, "Tags", slug_for("section", "tags"))
    b.line("| Tag | Meaning |")
    b.line("|---|---|")
    for k in sorted(tags.keys(), key=str.lower):
        b.line(f"| `{k}` | {tags[k]} |")
    b.line()


# ---------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------

def generate(
    data: dict[str, Any],
    validator: Validator,
    sections: set[str],
    diagrams: set[str],
    title: str | None,
    include_toc: bool,
) -> str:
    b = DocBuilder()

    meta = data.get("meta", {})
    doc_title = title or f"{Path(data.get('root', 'Standard')).name or 'Standard'} - fs-org-std"

    sites_by_rule = collect_rule_sites(data, validator.resolved_paths, validator.resolved_folders)

    # rendered in this fixed order regardless of `sections` filtering,
    # so cross-references are always to a section that's either already
    # rendered above, or will exist below - order itself doesn't matter
    # for correctness (anchors are computed, not registered - see the
    # slug/anchor note above), only for reading flow
    if "overview" in sections:
        render_overview(b, data, validator.resolved_paths, diagrams)
    if "paths" in sections:
        render_paths(b, validator.resolved_paths)
    if "cross" in sections:
        render_cross(b, data, diagrams)
    if "folders" in sections:
        render_folders(b, data, validator.resolved_folders)
    if "rules" in sections:
        render_rules(b, validator.rule_catalog, sites_by_rule, diagrams)
    if "enums" in sections:
        render_enums(b, data, diagrams)
    if "abbreviations" in sections:
        render_abbreviations(b, data)
    if "tags" in sections:
        render_tags(b, data)

    body = "\n".join(b.lines)
    toc = "\n".join(b.render_toc()) if include_toc else ""

    parts = [
        f"# {doc_title}",
        "",
        f"> Generated from `fs-org-std.toml` - standard v{meta.get('standard_version', '?')}, "
        f"schema v{meta.get('schema_version', '?')}",
        "",
    ]
    if toc:
        parts.append(toc)
    parts.append(body)
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def _parse_list_arg(value: str | None, valid: tuple[str, ...]) -> set[str]:
    if value is None:
        return set(valid)
    requested = {v.strip() for v in value.split(",") if v.strip()}
    unknown = requested - set(valid)
    if unknown:
        raise ValueError(f"unknown value(s) {sorted(unknown)} - valid options: {', '.join(valid)}")
    return requested


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("path", type=Path, help="path to a populated fs-org-std.toml")
    parser.add_argument("--output", type=Path, default=None, help="write to a file instead of stdout")
    parser.add_argument("--sections", default=None, help=f"comma-separated: {','.join(ALL_SECTIONS)} (default: all)")
    parser.add_argument("--exclude-sections", default=None, help="comma-separated section names to drop after --sections is applied")
    parser.add_argument("--diagrams", default=None, help=f"comma-separated: {','.join(ALL_DIAGRAMS)} (default: all)")
    parser.add_argument("--no-diagrams", action="store_true", help="disable all Mermaid diagrams")
    parser.add_argument("--no-toc", action="store_true", help="skip the table of contents")
    parser.add_argument("--include-external", action="store_true", help="also discover rules.external/ (never included by default)")
    parser.add_argument("--rules-dir", type=Path, default=None, help="override where bundled rules are discovered from")
    parser.add_argument("--title", default=None, help="override the document title")
    args = parser.parse_args(argv)

    try:
        sections = _parse_list_arg(args.sections, ALL_SECTIONS)
        if args.exclude_sections:
            exclude = _parse_list_arg(args.exclude_sections, ALL_SECTIONS)
            sections -= exclude
        diagrams = set() if args.no_diagrams else _parse_list_arg(args.diagrams, ALL_DIAGRAMS)
    except ValueError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    try:
        raw_text = args.path.read_text(encoding="utf-8")
    except FileNotFoundError:
        print(f"error: {args.path} not found", file=sys.stderr)
        return 2

    try:
        with args.path.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        print(f"error: {args.path} is not valid TOML: {e}", file=sys.stderr)
        return 2

    standard_dir = args.path.resolve().parent
    header_occurrences, key_lines = _index_source(raw_text)
    validator = Validator(
        data, standard_dir, header_occurrences, key_lines,
        include_external=args.include_external, bundled_rules_dir=args.rules_dir,
    )
    issues = validator.run()
    errors = [i for i in issues if i.level == "error"]
    warnings = [i for i in issues if i.level == "warning"]

    if errors:
        print(
            f"error: {args.path} has {len(errors)} validation error(s) - fix these before generating docs "
            f"(run `python -m fs_org_kit.validator {args.path}` for details)",
            file=sys.stderr,
        )
        return 2

    if warnings:
        print(f"note: {len(warnings)} validation warning(s) - docs generated anyway (see the validator for details)", file=sys.stderr)

    markdown = generate(data, validator, sections, diagrams, args.title, not args.no_toc)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)

    return 0


if __name__ == "__main__":
    sys.exit(main())
