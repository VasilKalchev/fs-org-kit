#!/usr/bin/env python3
"""
doc.py - validates a populated standard, then generates Markdown
documentation from it: a table of contents and one section per part of
the standard.

Usage:
    python -m fs_org_kit.doc path/to/your-file.toml
    python -m fs_org_kit.doc path/to/your-file.toml --output docs/standard.md

Documents the RESOLVED standard, not the raw TOML - an inherited
`purpose` shows up with its actual value. This reuses fs_org_kit.validator
directly (its resolved_paths / resolved_folders), the same way the
runner does, rather than re-parsing inheritance or re-running discovery
itself.

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
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fs_org_kit.fields import ATTRIBUTES, GROUP, FieldSpec, iter_rule_instances
from fs_org_kit.inherit import ResolvedEntry
from fs_org_kit.validator import (
    DEFAULT_RESERVED_PREFIX, StandardLoadError, Validator, add_discovery_args, load_and_validate,
    use_utf8_output,
)


# ---------------------------------------------------------------------
# Slugs / anchors
#
# Explicit <a id="..."> anchors placed before each heading, linked to by
# a prefixed slug scheme, turned out not to be honored by the renderers
# this is actually read in - a plain link to the anchor a renderer
# auto-generates from the heading text does work. So slug_for() computes
# exactly that: the same transform the renderer applies to a heading's
# visible text (backticks are code-span syntax, not part of the
# rendered text, so they're stripped before lowercasing). Every call
# site MUST pass the exact text that appears in the corresponding
# heading, or the two will diverge.
#
# Heading-anchor generation isn't part of CommonMark - every renderer
# invents its own, and they disagree on whitespace specifically: GitHub
# and most static-site generators hyphenate it, Obsidian percent-encodes
# it as %20. There's no anchor string that satisfies both. Obsidian is
# the default target since that's what these docs are actually read in;
# this is expected to become a configurable target rather than a
# hardcoded choice.
#
# This also gives up the prior scheme's structural guarantee against
# collisions between different sections (a rule id and a path could in
# principle slugify to the same anchor) - acceptable since this is
# documentation, not a safety-critical index, and matching what the
# renderer actually does is what makes the links work at all.
# ---------------------------------------------------------------------

def slug_for(title: str) -> str:
    text = title.strip().strip("`")
    text = text.lower()
    return re.sub(r"\s+", "%20", text)


def link(text: str, slug: str | None) -> str:
    return f"[{text}](#{slug})" if slug else text


def cell(text: object) -> str:
    """A standard's prose made safe for one Markdown table cell (or list
    item): a `|` would end the cell early, and a newline - natural in a
    multi-line TOML string - would end the row."""
    return str(text).replace("|", "\\|").replace("\r\n", "\n").replace("\n", "<br>")


# ---------------------------------------------------------------------
# Rule attachment reverse index
# ---------------------------------------------------------------------

@dataclass
class RuleAttachmentSite:
    location_label: str
    location_slug: str | None
    reason: str


def collect_rule_sites(
    data: dict[str, Any],
    resolved_paths: dict[str, ResolvedEntry],
    resolved_folders: dict[str, ResolvedEntry],
) -> dict[str, list[RuleAttachmentSite]]:
    sites: dict[str, list[RuleAttachmentSite]] = {}

    def add(rule_id: str, label: str, slug: str | None, inst: dict[str, Any]) -> None:
        sites.setdefault(rule_id, []).append(
            RuleAttachmentSite(label, slug, inst.get("reason", ""))
        )

    def add_raw_table(table: Any, label: str, slug: str | None) -> None:
        for rule_id, instances in iter_rule_instances(table):
            for inst in instances:
                if isinstance(inst, dict):
                    add(rule_id, label, slug, inst)

    for key, resolved in resolved_paths.items():
        for rule_id, attachments in resolved.rules.items():
            for a in attachments:
                add(rule_id, key, slug_for(f"`{key}`"), a.instance)

    paths = data.get("paths", {})
    add_raw_table(paths.get("rules"), "every cataloged path (blanket)", None)

    for i, cross in enumerate(paths.get("cross", [])):
        if isinstance(cross, dict):
            add_raw_table(cross.get("rules"), f"Cross-Path Set {i + 1}", slug_for(f"Set {i + 1}"))

    for name, resolved in resolved_folders.items():
        for rule_id, attachments in resolved.rules.items():
            for a in attachments:
                add(rule_id, f"folders.reserved.\"{name}\"", slug_for(f"`{name}`"), a.instance)

    add_raw_table(data.get("folders", {}).get("rules"), "every folder under root (blanket)", None)

    return sites


# ---------------------------------------------------------------------
# Doc builder
# ---------------------------------------------------------------------

class DocBuilder:
    def __init__(self) -> None:
        self.lines: list[str] = []
        self.toc_entries: list[tuple[int, str, str]] = []

    def heading(self, level: int, title: str, slug: str, in_toc: bool = True) -> None:
        self.lines.append(f"{'#' * level} {title}")
        self.lines.append("")
        if in_toc:
            self.toc_entries.append((level, title, slug))

    def toc_entry(self, level: int, title: str, slug: str) -> None:
        """Add a ToC line not backed by a heading of its own - used to
        nest path entries by directory depth (see _add_path_toc_tree)
        rather than one flat entry per heading level."""
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

def render_overview(
    b: DocBuilder, data: dict[str, Any], resolved_paths: dict, resolved_folders: dict
) -> None:
    b.heading(2, "Overview", slug_for("Overview"))
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
    b.line(f"- **Reserved folders**: {len(resolved_folders)}")
    b.line()


def _field_label(name: str) -> str:
    """`use_for` -> "Use for". The standard names its own fields; this is
    the whole of the presentation logic applied to them."""
    text = name.replace("_", " ").strip()
    return text[:1].upper() + text[1:]


def _string_values(value: Any) -> list[str]:
    """Both shapes a field can hold, flattened - a bare string, or a list
    of them, with empty placeholder entries dropped."""
    if isinstance(value, str):
        return [value] if value else []
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str) and v]
    return []


def _render_attribute_table(b: DocBuilder, resolved: ResolvedEntry, spec: FieldSpec) -> None:
    """Renders whatever the standard declared, in the order it declared
    it: single-valued fields as table rows, list-valued ones as bullets
    below. Grouping values link to the vocabulary that defines them."""
    rows: list[tuple[str, str]] = []
    bullet_lists: list[tuple[str, list[str]]] = []

    for name in spec.attribute_names:
        value = resolved.attributes.get(name)
        if isinstance(value, str) and value:
            rows.append((_field_label(name), cell(value)))
            continue
        values = _string_values(value)
        if values:
            bullet_lists.append((_field_label(name), values))

    for name in spec.group_names:
        values = _string_values(resolved.group.get(name))
        if values:
            linked = ", ".join(f"[`{v}`](#{slug_for('Enums')})" for v in values)
            rows.append((_field_label(name), linked))

    if rows:
        b.line("| Field | Value |")
        b.line("|---|---|")
        for label, value in rows:
            b.line(f"| {label} | {value} |")
        b.line()

    for label, values in bullet_lists:
        b.line(f"**{label}:**")
        b.line()
        for v in values:
            b.line(f"- {cell(v)}")
        b.line()


def _render_rule_table(b: DocBuilder, rows: list[tuple[str, str]]) -> None:
    """The `| Rule | Reason |` table shared by a resolved (path/folder)
    entry's attachments and a `paths.cross` set's - each just gets there
    from a different rules-table shape, normalized to (rule_id, reason)
    rows before it does."""
    if not rows:
        return
    b.line("**Attached rules:**")
    b.line()
    b.line("| Rule | Reason |")
    b.line("|---|---|")
    for rule_id, reason in rows:
        rule_slug = slug_for(f"`{rule_id}`")
        b.line(f"| {link(f'`{rule_id}`', rule_slug)} | {cell(reason)} |")
    b.line()


def _render_rule_attachments(b: DocBuilder, resolved: ResolvedEntry) -> None:
    rows = [
        (rule_id, a.instance.get("reason", ""))
        for rule_id, attachments in sorted(resolved.rules.items())
        for a in attachments
    ]
    _render_rule_table(b, rows)


def _add_path_toc_tree(b: DocBuilder, keys: list[str]) -> None:
    """Nest the ToC under Paths by directory depth instead of listing
    every key flat - a reader scanning the ToC sees the same tree shape
    as the filesystem. Only the final path segment is shown as the link
    text; the ancestry is already conveyed by the indentation, so
    repeating the full path on every line would just be noise."""
    for key in sorted(keys):
        trimmed = key.rstrip("/")
        depth = trimmed.count("/")
        leaf = trimmed.rsplit("/", 1)[-1] if "/" in trimmed else trimmed
        label = f"`{leaf}/`" if key.endswith("/") else f"`{leaf}`"
        b.toc_entry(3 + depth, label, slug_for(f"`{key}`"))


def render_paths(b: DocBuilder, resolved_paths: dict[str, ResolvedEntry], spec: FieldSpec) -> None:
    if not resolved_paths:
        return
    b.heading(2, "Paths", slug_for("Paths"))
    for key in sorted(resolved_paths.keys()):
        resolved = resolved_paths[key]
        b.heading(3, f"`{key}`", slug_for(f"`{key}`"), in_toc=False)
        _render_attribute_table(b, resolved, spec)
        _render_rule_attachments(b, resolved)
    _add_path_toc_tree(b, list(resolved_paths.keys()))


def render_cross(b: DocBuilder, data: dict[str, Any]) -> None:
    paths = data.get("paths", {})
    cross_sets = paths.get("cross", [])
    if not isinstance(cross_sets, list) or not cross_sets:
        return
    b.heading(2, "Cross-Path Sets", slug_for("Cross-Path Sets"))
    for i, cross in enumerate(cross_sets):
        if not isinstance(cross, dict):
            continue
        b.heading(3, f"Set {i + 1}", slug_for(f"Set {i + 1}"))
        members = cross.get("paths", [])
        if members:
            member_links = ", ".join(link(f"`{m}`", slug_for(f"`{m}`")) for m in members)
            b.line(f"**Members**: {member_links}")
            b.line()

        rows = [
            (rule_id, inst.get("reason", ""))
            for rule_id, instances in sorted(iter_rule_instances(cross.get("rules")))
            for inst in instances
            if isinstance(inst, dict)
        ]
        if rows:
            _render_rule_table(b, rows)


def render_folders(b: DocBuilder, data: dict[str, Any], resolved_folders: dict[str, ResolvedEntry], spec: FieldSpec) -> None:
    if not resolved_folders:
        return
    b.heading(2, "Reserved Folders", slug_for("Reserved Folders"))
    reserved = data.get("folders", {}).get("reserved", {})
    prefix = reserved.get("prefix", DEFAULT_RESERVED_PREFIX) if isinstance(reserved, dict) else DEFAULT_RESERVED_PREFIX
    b.line(f"Reserved-name prefix: `{prefix}`")
    b.line()
    for name in sorted(resolved_folders.keys()):
        resolved = resolved_folders[name]
        b.heading(3, f"`{name}`", slug_for(f"`{name}`"))
        _render_attribute_table(b, resolved, spec)
        _render_rule_attachments(b, resolved)


def render_rules(b: DocBuilder, sites_by_rule: dict[str, list[RuleAttachmentSite]]) -> None:
    attached_ids = sorted(sites_by_rule.keys())
    if not attached_ids:
        return
    b.heading(2, "Rules", slug_for("Rules"))

    for rule_id in attached_ids:
        b.heading(3, f"`{rule_id}`", slug_for(f"`{rule_id}`"))
        sites = sites_by_rule[rule_id]
        b.line(f"**Attached at {len(sites)} location(s):**")
        b.line()
        for site in sorted(sites, key=lambda s: s.location_label):
            b.line(f"- {link(f'`{site.location_label}`', site.location_slug)} - {cell(site.reason)}")
        b.line()


def render_enums(b: DocBuilder, data: dict[str, Any]) -> None:
    """One table per vocabulary, under the kind of field it belongs to -
    a standard names its own fields, so neither the set of tables nor
    their names is known ahead of time. The heading is the dotted key
    itself, so a reader of the docs can find it in the TOML."""
    enums = data.get("enums", {})
    if not isinstance(enums, dict):
        return

    vocabularies: list[tuple[str, str, dict[str, Any]]] = []
    for kind in (GROUP, ATTRIBUTES):
        kind_enums = enums.get(kind, {})
        if not isinstance(kind_enums, dict):
            continue
        for name, values in kind_enums.items():
            if isinstance(values, dict) and values:
                vocabularies.append((kind, name, values))

    if not vocabularies:
        return

    b.heading(2, "Enums", slug_for("Enums"))

    for kind, name, values in vocabularies:
        b.line(f"**`enums.{kind}.{name}`:**")
        b.line()
        b.line("| Value | Meaning |")
        b.line("|---|---|")
        for val, desc in values.items():
            b.line(f"| `{val}` | {cell(desc)} |")
        b.line()


def render_abbreviations(b: DocBuilder, data: dict[str, Any]) -> None:
    abbreviations = data.get("abbreviations", {})
    if not isinstance(abbreviations, dict) or not abbreviations:
        return
    b.heading(2, "Abbreviations", slug_for("Abbreviations"))
    b.line("| Abbreviation | Meaning |")
    b.line("|---|---|")
    for k in sorted(abbreviations.keys(), key=str.lower):
        b.line(f"| `{k}` | {cell(abbreviations[k])} |")
    b.line()


def render_tags(b: DocBuilder, data: dict[str, Any]) -> None:
    """One table per tag namespace, rendered like the enums section it
    resembles - both are closed vocabularies. The difference is where a
    value ends up: an enum value is written in this standard, a tag value
    is carried by something on disk, so this documents what may be used
    and never what currently is."""
    tags = data.get("tags", {})
    if not isinstance(tags, dict) or not tags:
        return

    namespaces = [
        (name, declaration) for name, declaration in tags.items()
        if isinstance(declaration, dict)
    ]
    if not namespaces:
        return

    b.heading(2, "Tags", slug_for("Tags"))

    for name, declaration in namespaces:
        b.line(f"**`tags.{name}`:**")
        b.line()
        description = declaration.get("description")
        if isinstance(description, str) and description:
            b.line(description)
            b.line()
        b.line(
            "Multiple values may apply at once."
            if declaration.get("multi")
            else "Exactly one value applies at a time."
        )
        b.line()

        values = declaration.get("values")
        if not isinstance(values, dict) or not values:
            b.line("*No values declared.*")
            b.line()
            continue

        b.line("| Value | Meaning |")
        b.line("|---|---|")
        for value, meaning in values.items():
            b.line(f"| `{value}` | {cell(meaning)} |")
        b.line()


# ---------------------------------------------------------------------
# Assembly
# ---------------------------------------------------------------------

def generate(data: dict[str, Any], validator: Validator, title: str | None) -> str:
    b = DocBuilder()

    meta = data.get("meta", {})
    doc_title = title or f"{Path(data.get('root', 'Standard')).name or 'Standard'} - fs-org-std"

    sites_by_rule = collect_rule_sites(data, validator.resolved_paths, validator.resolved_folders)

    # rendered in this fixed order so cross-references are always to a
    # section that's either already rendered above, or will exist below
    render_overview(b, data, validator.resolved_paths, validator.resolved_folders)
    render_paths(b, validator.resolved_paths, validator.path_fields)
    render_cross(b, data)
    render_folders(b, data, validator.resolved_folders, validator.folder_fields)
    render_rules(b, sites_by_rule)
    render_enums(b, data)
    render_abbreviations(b, data)
    render_tags(b, data)

    body = "\n".join(b.lines)
    toc = "\n".join(b.render_toc())

    parts = [f"# {doc_title}", ""]
    if toc:
        parts.append(toc)
    parts.append(body)
    parts.append("---")
    parts.append(
        f"*Generated from `fs-org-std.toml` - standard v{meta.get('standard_version', '?')}, "
        f"schema v{meta.get('schema_version', '?')}*"
    )
    return "\n".join(parts) + "\n"


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("path", type=Path, help="path to a populated fs-org-std.toml")
    parser.add_argument("--output", type=Path, default=None, help="write to a file instead of stdout")
    add_discovery_args(parser)
    parser.add_argument("--title", default=None, help="override the document title")
    args = parser.parse_args(argv)
    use_utf8_output()

    try:
        data, validator, warnings = load_and_validate(
            args.path, include_external=args.include_external,
            bundled_rules_dir=args.rules_dir, before="generating docs",
        )
    except StandardLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if warnings:
        print(f"note: {len(warnings)} validation warning(s) - docs generated anyway (see the validator for details)", file=sys.stderr)

    markdown = generate(data, validator, args.title)

    if args.output:
        args.output.write_text(markdown, encoding="utf-8")
        print(f"wrote {args.output}", file=sys.stderr)
    else:
        sys.stdout.write(markdown)

    return 0


if __name__ == "__main__":
    sys.exit(main())
