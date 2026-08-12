"""
fs_org_kit.fields - what a namespace declares its entries may carry.

An entry is its documentation fields, plus two sub-tables:

    [paths."a/"]                 free-form documentation fields, written
    whatever = "bla"             directly on the entry. A string, or a
                                 list of strings. Nothing reads the
                                 values; the doc generator renders
                                 whatever is there.

    [paths."a/".group]           enum-backed values, checked against
    fruit = "apple"              `enums.group.<field>` and used to sort
                                 entries into buckets in the generated
                                 docs - a closed vocabulary is what makes
                                 that possible.

    [[paths."a/".rules.rule-a-v1]]   rule attachments.

The namespace declares the first two in one place:

    [paths.attributes]
    names = ["whatever"]         valid documentation field names
    required = ["whatever"]      the ones that may not be left empty

    [paths.attributes.group]
    names = ["fruit"]
    multi = []                   fields holding a LIST of values
    required = ["fruit"]

Every name is the user's: nothing in this package knows what `purpose`
or `lifecycle` mean, and a standard is free to call its fields anything
that isn't one of the structural keys below. The two namespaces (`paths`,
`folders`) declare independently, so they can carry different fields; the
vocabularies under `enums` are shared, since a value set describes the
field rather than who carries it.

Parsed once per namespace by the validator, which hands the result to the
doc generator - the same resolve-once-and-reuse path `rule_catalog` and
`resolved_paths` already take.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOC = "doc"
GROUP = "group"
RULES = "rules"

# Keys on an entry that are structure rather than a documentation field.
# A declared field name may not collide with one.
STRUCTURAL_KEYS = (GROUP, RULES, "inherit")

# The table a namespace declares its fields in, beside its entries.
DECLARATION_TABLE = "attributes"

MISSING_GROUPING_ENUM = "missing-grouping-enum"


@dataclass(frozen=True)
class FieldIssue:
    level: str      # "error" | "warning"
    location: str   # dotted path into the TOML
    message: str
    code: str = ""  # warnings only


@dataclass(frozen=True)
class FieldSpec:
    """What one namespace ("paths" / "folders") declares its entries may
    carry. Names keep their declared order - the doc generator renders in
    the order the standard was written in, not alphabetically."""

    namespace: str
    doc_names: tuple[str, ...] = ()
    doc_required: frozenset[str] = frozenset()
    doc_values: dict[str, frozenset[str]] = field(default_factory=dict)
    group_names: tuple[str, ...] = ()
    group_multi: frozenset[str] = frozenset()
    group_required: frozenset[str] = frozenset()
    group_values: dict[str, frozenset[str]] = field(default_factory=dict)

    def names(self, kind: str) -> tuple[str, ...]:
        return self.doc_names if kind == DOC else self.group_names

    def required(self, kind: str) -> frozenset[str]:
        return self.doc_required if kind == DOC else self.group_required

    def is_multi(self, name: str) -> bool:
        return name in self.group_multi

    @staticmethod
    def enum_location(kind: str, name: str) -> str:
        return f"enums.{kind}.{name}"

    def declaration_location(self, kind: str) -> str:
        base = f"{self.namespace}.{DECLARATION_TABLE}"
        return f"{base}.names" if kind == DOC else f"{base}.{GROUP}.names"

    def is_declared(self) -> bool:
        """False when a namespace declares no fields at all - the point
        where unknown-field checking has nothing to compare against."""
        return bool(self.doc_names or self.group_names)


def _string_list(value: Any, location: str, issues: list[FieldIssue]) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        issues.append(FieldIssue("error", location, "must be a list of field names (strings)"))
        return ()
    seen: list[str] = []
    for name in value:
        if name in seen:
            issues.append(FieldIssue("error", location, f"'{name}' is listed twice"))
            continue
        seen.append(name)
    return tuple(seen)


def _subset(
    value: Any, location: str, names: tuple[str, ...], names_location: str, issues: list[FieldIssue]
) -> frozenset[str]:
    listed = _string_list(value, location, issues)
    for name in listed:
        if name not in names:
            issues.append(FieldIssue("error", location, f"'{name}' isn't declared in {names_location}"))
    return frozenset(n for n in listed if n in names)


def _table(data: dict[str, Any], *keys: str) -> dict[str, Any]:
    current: Any = data
    for key in keys:
        if not isinstance(current, dict):
            return {}
        current = current.get(key, {})
    return current if isinstance(current, dict) else {}


def _vocabulary(enums: dict[str, Any], kind: str, name: str) -> frozenset[str] | None:
    """The declared value set for one field, or None when there isn't
    one. Vocabularies live under `enums.<kind>.<field>` and are shared by
    both namespaces."""
    table = _table(enums, kind).get(name)
    if not isinstance(table, dict) or not table:
        return None
    return frozenset(table.keys())


def parse_field_spec(data: dict[str, Any], namespace: str) -> tuple[FieldSpec, list[FieldIssue]]:
    """Read one namespace's field declarations. Reports what's wrong with
    the DECLARATION itself; checking entry values against it is the
    validator's job."""
    issues: list[FieldIssue] = []
    enums = _table(data, "enums")

    declaration = f"{namespace}.{DECLARATION_TABLE}"
    attributes = _table(data, namespace, DECLARATION_TABLE)
    doc_names = _string_list(attributes.get("names"), f"{declaration}.names", issues)
    doc_required = _subset(
        attributes.get("required"), f"{declaration}.required",
        doc_names, f"{declaration}.names", issues,
    )

    group_table = _table(attributes, GROUP)
    group_names = _string_list(group_table.get("names"), f"{declaration}.group.names", issues)
    group_multi = _subset(
        group_table.get("multi"), f"{declaration}.group.multi",
        group_names, f"{declaration}.group.names", issues,
    )
    group_required = _subset(
        group_table.get("required"), f"{declaration}.group.required",
        group_names, f"{declaration}.group.names", issues,
    )

    for name in doc_names:
        if name in STRUCTURAL_KEYS:
            issues.append(FieldIssue(
                "error", f"{declaration}.names",
                f"'{name}' is one of an entry's structural keys ({', '.join(STRUCTURAL_KEYS)}) - "
                f"a documentation field can't share the name",
            ))
    for name in group_names:
        if name in doc_names:
            issues.append(FieldIssue(
                "error", f"{declaration}.group.names",
                f"'{name}' is also declared in {declaration}.names - a field is either free-form "
                f"documentation or an enum-backed grouping field, not both",
            ))

    doc_values: dict[str, frozenset[str]] = {}
    for name in doc_names:
        # optional here: a documentation field is prose unless the
        # standard chose to close its value set
        vocabulary = _vocabulary(enums, DOC, name)
        if vocabulary is not None:
            doc_values[name] = vocabulary

    group_values: dict[str, frozenset[str]] = {}
    for name in group_names:
        vocabulary = _vocabulary(enums, GROUP, name)
        if vocabulary is None:
            issues.append(FieldIssue(
                "warning", f"enums.group.{name}",
                f"grouping field '{name}' has no value vocabulary - its values won't be checked "
                f"(declare them under [enums.group.{name}])",
                MISSING_GROUPING_ENUM,
            ))
            group_values[name] = frozenset()
        else:
            group_values[name] = vocabulary

    spec = FieldSpec(
        namespace=namespace,
        doc_names=doc_names,
        doc_required=doc_required,
        doc_values=doc_values,
        group_names=group_names,
        group_multi=group_multi,
        group_required=group_required,
        group_values=group_values,
    )
    return spec, issues
