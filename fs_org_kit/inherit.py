"""
fs_org_kit.inherit - resolves inheritance and standard-wide defaults for
[paths."..."] and [folders.reserved."..."] entries.

This is a pure data transformation, run once before validation: given the
raw TOML data for one namespace (paths, or folders.reserved), it produces
a fully resolved view where every entry's attributes and rules are already
flattened - inheritance chains walked, exclusions applied, standard-wide
defaults filled in. Everything downstream (the validator, the runner)
operates on this resolved view and never needs to know inheritance exists.

Resolution order per attribute field, most to least specific:
    1. the entry's own explicitly-set value
    2. inherited value, via .inherit.attributes' source entry (recursive)
    3. standard-wide default (paths.attributes.defaults, or the folders
       equivalent)
    4. unset

A field counts as "explicitly set" if it's a non-empty string/list, or
if it's a boolean at all (booleans have no meaningful "empty" state -
`allow_missing = false` is a deliberate override, not an absence, even
though it's falsy).

Rules resolve independently via .inherit.rules / .inherit.exclude_rules -
same chain-walking and cycle detection as attributes, but the two chains
can point at different sources, and the result is a MERGE, not a
per-field override: the resolved rule set is
    {rules inherited via .inherit.rules, minus .inherit.exclude_rules}
    UNION
    {this entry's own directly-declared rule attachments}
If the same rule id appears in both, both sets of instances apply - nothing
in the child silently replaces an inherited instance of the same rule.
To change an inherited rule's params, exclude it and redeclare it fresh.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class RuleAttachment:
    rule_id: str
    instance: dict[str, Any]
    origin_key: str | None  # None = declared directly on this entry; else the
                             # entry it was inherited from (traced to the
                             # original declaring entry, not just one hop up)


@dataclass(frozen=True)
class ResolvedEntry:
    key: str
    attributes: dict[str, Any]
    rules: dict[str, list[RuleAttachment]]
    raw: dict[str, Any]


@dataclass(frozen=True)
class InheritIssue:
    level: str  # "error" | "warning"
    key: str
    message: str


class _CycleDetected(Exception):
    def __init__(self, chain: list[str]):
        self.chain = chain


def _is_explicitly_set(entry: dict[str, Any], field_name: str) -> bool:
    if field_name not in entry:
        return False
    value = entry[field_name]
    if isinstance(value, bool):
        return True  # no "empty" boolean - presence alone is the signal
    return bool(value)  # "" / [] / None don't count as explicitly set


def _get_inherit_table(entry: dict[str, Any]) -> dict[str, Any]:
    inherit = entry.get("inherit")
    return inherit if isinstance(inherit, dict) else {}


def _resolve_attributes(
    key: str,
    raw_entries: dict[str, dict[str, Any]],
    defaults: dict[str, Any],
    memo: dict[str, dict[str, Any]],
    chain: tuple[str, ...],
) -> dict[str, Any]:
    if key in memo:
        return memo[key]
    if key in chain:
        raise _CycleDetected(list(chain) + [key])

    entry = raw_entries.get(key, {})
    parent_key = _get_inherit_table(entry).get("attributes")

    base: dict[str, Any] = {}
    if isinstance(parent_key, str) and parent_key:
        base = dict(_resolve_attributes(parent_key, raw_entries, defaults, memo, chain + (key,)))

    result = dict(base)
    for field_name, value in entry.items():
        if field_name in ("inherit", "rules"):
            continue
        if _is_explicitly_set(entry, field_name):
            result[field_name] = value

    for field_name, value in defaults.items():
        if field_name not in result or not _is_explicitly_set(result, field_name):
            result[field_name] = value

    memo[key] = result
    return result


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
    parent_key = inherit.get("rules")
    exclude = set(inherit.get("exclude_rules", [])) if isinstance(inherit.get("exclude_rules"), list) else set()

    result: dict[str, list[RuleAttachment]] = {}

    if isinstance(parent_key, str) and parent_key:
        parent_rules = _resolve_rules(parent_key, raw_entries, memo, chain + (key,))
        for rule_id, attachments in parent_rules.items():
            if rule_id in exclude:
                continue
            result[rule_id] = [
                RuleAttachment(a.rule_id, a.instance, a.origin_key or parent_key)
                for a in attachments
            ]

    own_rules = entry.get("rules", {})
    if isinstance(own_rules, dict):
        for rule_id, instances in own_rules.items():
            if not isinstance(instances, list):
                instances = [instances]
            own_attachments = [RuleAttachment(rule_id, inst, None) for inst in instances if isinstance(inst, dict)]
            result[rule_id] = result.get(rule_id, []) + own_attachments

    memo[key] = result
    return result


def resolve_entries(
    raw_entries: dict[str, dict[str, Any]],
    defaults: dict[str, Any],
    namespace_label: str,
) -> tuple[dict[str, ResolvedEntry], list[InheritIssue]]:
    """Resolve every entry in one namespace (paths, or folders.reserved).

    namespace_label is used only for issue messages (e.g. "paths" or
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

        attrs_src = inherit.get("attributes")
        if attrs_src is not None:
            if not isinstance(attrs_src, str):
                issues.append(InheritIssue("error", key, "inherit.attributes must be a path/folder key (string)"))
            elif attrs_src not in raw_entries:
                issues.append(InheritIssue("error", key, f"inherit.attributes references unknown {namespace_label} key '{attrs_src}'"))

        rules_src = inherit.get("rules")
        if rules_src is not None:
            if not isinstance(rules_src, str):
                issues.append(InheritIssue("error", key, "inherit.rules must be a path/folder key (string)"))
            elif rules_src not in raw_entries:
                issues.append(InheritIssue("error", key, f"inherit.rules references unknown {namespace_label} key '{rules_src}'"))

        exclude_rules = inherit.get("exclude_rules")
        if exclude_rules is not None:
            if not isinstance(exclude_rules, list) or not all(isinstance(r, str) for r in exclude_rules):
                issues.append(InheritIssue("error", key, "inherit.exclude_rules must be a list of rule ids"))
            elif rules_src is None:
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

    attr_memo: dict[str, dict[str, Any]] = {}
    rules_memo: dict[str, dict[str, list[RuleAttachment]]] = {}
    resolved: dict[str, ResolvedEntry] = {}

    for key in safe_entries:
        try:
            attrs = _resolve_attributes(key, safe_entries, defaults, attr_memo, ())
        except _CycleDetected as e:
            issues.append(InheritIssue("error", key, f"inherit.attributes cycle: {' -> '.join(e.chain)}"))
            attrs = {k: v for k, v in safe_entries[key].items() if k not in ("inherit", "rules")}

        try:
            rules = _resolve_rules(key, safe_entries, rules_memo, ())
        except _CycleDetected as e:
            issues.append(InheritIssue("error", key, f"inherit.rules cycle: {' -> '.join(e.chain)}"))
            own = safe_entries[key].get("rules", {})
            rules = {}
            if isinstance(own, dict):
                for rule_id, instances in own.items():
                    if not isinstance(instances, list):
                        instances = [instances]
                    rules[rule_id] = [RuleAttachment(rule_id, inst, None) for inst in instances if isinstance(inst, dict)]

        resolved[key] = ResolvedEntry(key=key, attributes=attrs, rules=rules, raw=raw_entries[key])

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
        rules_src = inherit.get("rules")
        exclude = inherit.get("exclude_rules")
        if not isinstance(rules_src, str) or rules_src not in resolved or not isinstance(exclude, list):
            continue
        parent_rule_ids = set(resolved[rules_src].rules.keys()) if rules_src in resolved else set()
        # what the parent *would* offer before this entry's own exclusion -
        # resolve the parent alone, not this entry, to get the raw candidate set
        try:
            candidate_ids = set(_resolve_rules(rules_src, safe_entries, rules_memo, ()).keys())
        except _CycleDetected:
            candidate_ids = parent_rule_ids
        for rule_id in exclude:
            if isinstance(rule_id, str) and rule_id not in candidate_ids:
                issues.append(InheritIssue(
                    "warning", key,
                    f"inherit.exclude_rules lists '{rule_id}', but it isn't among the rules inherited from '{rules_src}' - no effect",
                ))

    return resolved, issues
