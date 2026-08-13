"""
fs_org_kit.inherit - resolves inheritance for [paths."..."] and
[folders.reserved."..."] entries.

This is a pure data transformation, run once before validation: given the
raw TOML data for one namespace (paths, or folders.reserved), it produces
a fully resolved view where every entry is already flattened -
inheritance chains walked, exclusions applied. Everything downstream (the
validator, the runner, the doc generator) operates on this resolved view
and never needs to know inheritance exists.

An entry has three parts (see fs_org_kit.fields) and each inherits from
its own source, named for the part it fills:

    [paths."archive/project-x/".inherit]
    attributes = "active/project-x/"   # the entry's own fields; this
                                       # entry's own still override
    group = "active/project-x/"        # same, per field
    rules = "active/project-x/"        # inherited attachments MERGE with
                                       # this entry's own - use
                                       # exclude_rules to drop specific
                                       # inherited ones
    exclude_rules = ["rule-a-v2"]

Resolution order per field, most to least specific:
    1. the entry's own explicitly-set value
    2. inherited value, via that part's source entry (recursive)
    3. unset

A field counts as "explicitly set" if it's a non-empty string/list, or if
it's a boolean at all (booleans have no meaningful "empty" state).

Rule attachments MERGE rather than override:
    {attachments inherited via .inherit.rules, minus .inherit.exclude_rules}
    UNION
    {this entry's own directly-declared attachments}
If the same rule id appears in both, both sets of instances apply -
nothing in the child silently replaces an inherited instance of the same
rule. To change an inherited rule's params, exclude it and redeclare it
fresh.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fs_org_kit.fields import ATTRIBUTES, GROUP, RULES, STRUCTURAL_KEYS, iter_rule_instances

# `inherit` keys naming a source entry, and the part each one fills
SOURCE_KEYS = (ATTRIBUTES, GROUP, RULES)


@dataclass(frozen=True)
class RuleAttachment:
    instance: dict[str, Any]
    origin_key: str | None  # None = declared directly on this entry; else the
                             # entry it was inherited from (traced to the
                             # original declaring entry, not just one hop up)

    @property
    def origin_note(self) -> str:
        """How an inherited attachment is named in validator/runner output."""
        return f' (inherited from "{self.origin_key}")' if self.origin_key else ""


@dataclass(frozen=True)
class ResolvedEntry:
    key: str
    attributes: dict[str, Any]
    group: dict[str, Any]
    rules: dict[str, list[RuleAttachment]]


@dataclass(frozen=True)
class InheritIssue:
    level: str  # "error" | "warning"
    key: str
    message: str


class _CycleDetected(Exception):
    def __init__(self, chain: list[str]):
        self.chain = chain


def _is_explicitly_set(table: dict[str, Any], field_name: str) -> bool:
    if field_name not in table:
        return False
    value = table[field_name]
    if isinstance(value, bool):
        return True  # no "empty" boolean - presence alone is the signal
    return bool(value)  # "" / [] / None don't count as explicitly set


def _get_inherit_table(entry: dict[str, Any]) -> dict[str, Any]:
    inherit = entry.get("inherit")
    return inherit if isinstance(inherit, dict) else {}


def own_fields(entry: dict[str, Any], kind: str) -> dict[str, Any]:
    """The fields an entry declares itself for one part. Attributes are
    written directly on the entry, so they're everything that isn't one
    of its structural keys; `group` is its own table."""
    if kind == ATTRIBUTES:
        return {k: v for k, v in entry.items() if k not in STRUCTURAL_KEYS}
    table = entry.get(kind)
    return table if isinstance(table, dict) else {}


def _resolve_fields(
    key: str,
    raw_entries: dict[str, dict[str, Any]],
    memo: dict[str, dict[str, Any]],
    chain: tuple[str, ...],
    kind: str,
) -> dict[str, Any]:
    if key in memo:
        return memo[key]
    if key in chain:
        raise _CycleDetected(list(chain) + [key])

    entry = raw_entries.get(key, {})
    parent_key = _get_inherit_table(entry).get(kind)

    result: dict[str, Any] = {}
    if isinstance(parent_key, str) and parent_key:
        result = dict(_resolve_fields(parent_key, raw_entries, memo, chain + (key,), kind))

    own = own_fields(entry, kind)
    for field_name in own:
        if _is_explicitly_set(own, field_name):
            result[field_name] = own[field_name]

    memo[key] = result
    return result


def _own_attachments(entry: dict[str, Any]) -> dict[str, list[RuleAttachment]]:
    """This entry's own `rules` attachments, ignoring inheritance."""
    return {
        rule_id: [RuleAttachment(inst, None) for inst in instances if isinstance(inst, dict)]
        for rule_id, instances in iter_rule_instances(own_fields(entry, RULES))
    }


def _resolve_rules(
    key: str,
    raw_entries: dict[str, dict[str, Any]],
    memo: dict[str, dict[str, list[RuleAttachment]]],
    chain: tuple[str, ...],
) -> dict[str, list[RuleAttachment]]:
    if key in memo:
        return memo[key]
    if key in chain:
        raise _CycleDetected(list(chain) + [key])

    entry = raw_entries.get(key, {})
    inherit = _get_inherit_table(entry)
    parent_key = inherit.get(RULES)
    exclude = set(inherit.get("exclude_rules", [])) if isinstance(inherit.get("exclude_rules"), list) else set()

    result: dict[str, list[RuleAttachment]] = {}

    if isinstance(parent_key, str) and parent_key:
        parent_rules = _resolve_rules(parent_key, raw_entries, memo, chain + (key,))
        for rule_id, attachments in parent_rules.items():
            if rule_id in exclude:
                continue
            result[rule_id] = [
                RuleAttachment(a.instance, a.origin_key or parent_key)
                for a in attachments
            ]

    for rule_id, own_attachments in _own_attachments(entry).items():
        result[rule_id] = result.get(rule_id, []) + own_attachments

    memo[key] = result
    return result


def resolve_entries(
    raw_entries: dict[str, dict[str, Any]],
    namespace_label: str,
) -> tuple[dict[str, ResolvedEntry], list[InheritIssue]]:
    """Resolve every entry in one namespace (paths, or folders.reserved).

    `namespace_label` is used only for issue messages (e.g. "paths" or
    "folders.reserved") - it doesn't affect resolution logic, which is
    identical for both namespaces.
    """
    issues: list[InheritIssue] = []

    # structural pre-check: every referenced source must exist, and must
    # be a string - resolved before any recursive walk so a bad reference
    # can't crash resolution partway through
    for key, entry in raw_entries.items():
        if not isinstance(entry, dict):
            continue
        inherit = entry.get("inherit")
        if inherit is None:
            continue
        if not isinstance(inherit, dict):
            issues.append(InheritIssue("error", key, "`inherit` must be a table"))
            continue

        for source_key in SOURCE_KEYS:
            source = inherit.get(source_key)
            if source is None:
                continue
            if not isinstance(source, str):
                issues.append(InheritIssue("error", key, f"inherit.{source_key} must be a path/folder key (string)"))
            elif source not in raw_entries:
                issues.append(InheritIssue(
                    "error", key,
                    f"inherit.{source_key} references unknown {namespace_label} key '{source}'",
                ))

        exclude_rules = inherit.get("exclude_rules")
        if exclude_rules is not None:
            if not isinstance(exclude_rules, list) or not all(isinstance(r, str) for r in exclude_rules):
                issues.append(InheritIssue("error", key, "inherit.exclude_rules must be a list of rule ids"))
            elif inherit.get(RULES) is None:
                issues.append(InheritIssue("error", key, "inherit.exclude_rules is set but inherit.rules isn't - nothing to exclude from"))

    # drop entries whose own inherit table is structurally broken, so a bad
    # reference doesn't crash resolution for everyone else - they resolve
    # as if `inherit` weren't there at all, isolated to just that entry
    broken_keys = {issue.key for issue in issues}
    safe_entries = {
        key: ({**entry, "inherit": {}} if key in broken_keys else entry)
        for key, entry in raw_entries.items()
        if isinstance(entry, dict)
    }

    memos: dict[str, dict[str, dict[str, Any]]] = {ATTRIBUTES: {}, GROUP: {}}
    rules_memo: dict[str, dict[str, list[RuleAttachment]]] = {}
    resolved: dict[str, ResolvedEntry] = {}

    def resolve_part(key: str, kind: str) -> dict[str, Any]:
        try:
            return _resolve_fields(key, safe_entries, memos[kind], (), kind)
        except _CycleDetected as e:
            issues.append(InheritIssue("error", key, f"inherit.{kind} cycle: {' -> '.join(e.chain)}"))
            return dict(own_fields(safe_entries[key], kind))

    for key in safe_entries:
        attributes = resolve_part(key, ATTRIBUTES)
        group = resolve_part(key, GROUP)

        try:
            rules = _resolve_rules(key, safe_entries, rules_memo, ())
        except _CycleDetected as e:
            issues.append(InheritIssue("error", key, f"inherit.rules cycle: {' -> '.join(e.chain)}"))
            rules = _own_attachments(safe_entries[key])

        resolved[key] = ResolvedEntry(key=key, attributes=attributes, group=group, rules=rules)

    # exclude_rules entries that don't correspond to anything actually
    # inherited are very likely a typo or a stale exclusion - worth a
    # warning, not an error (excluding something that isn't there changes
    # nothing, it just doesn't do what the author probably intended)
    for key, entry in raw_entries.items():
        if not isinstance(entry, dict):
            continue
        inherit = entry.get("inherit")
        if not isinstance(inherit, dict):
            continue
        rules_src = inherit.get(RULES)
        exclude = inherit.get("exclude_rules")
        if not isinstance(rules_src, str) or rules_src not in resolved or not isinstance(exclude, list):
            continue
        # what the parent *would* offer before this entry's own exclusion -
        # resolve the parent alone, not this entry, to get the raw candidate set
        try:
            candidate_ids = set(_resolve_rules(rules_src, safe_entries, rules_memo, ()).keys())
        except _CycleDetected:
            candidate_ids = set(resolved[rules_src].rules.keys())
        for rule_id in exclude:
            if isinstance(rule_id, str) and rule_id not in candidate_ids:
                issues.append(InheritIssue(
                    "warning", key,
                    f"inherit.exclude_rules lists '{rule_id}', but it isn't among the rules inherited from '{rules_src}' - no effect",
                ))

    return resolved, issues
