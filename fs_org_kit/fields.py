"""
fs_org_kit.fields - the three tables an entry is made of, and the
per-namespace declaration that says what may go in two of them.

A `[paths."..."]` or `[folders.reserved."..."]` entry mixes fields that
mean very different things, and the difference is not visible from the
value. They live in three sub-tables named for who reads them:

  <entry>.doc    documentation. Free-form: a string, or a list of
                 strings. Nothing reads the values; the doc generator
                 renders whatever is there. Declared in `<ns>.doc.names`.

  <entry>.group  grouping. Enum-backed, checked against
                 `enums.group.<field>`, and used to sort entries into
                 buckets in the generated docs - a closed vocabulary is
                 what makes that possible. Declared in
                 `<ns>.group.names`.

  <entry>.rules  everything the rule machinery reads: the rule
                 attachments themselves, plus the CONTROL fields
                 `allow_missing` and `outside_root`, which decide
                 whether a target is expected on disk and where a fixer
                 may write. A fixed set owned by this package, never
                 declared in a standard.

Which names appear in `doc` and `group` is entirely the user's choice,
including the ones this project's own template happens to use - nothing
in the code knows what `purpose` or `lifecycle` mean. The two namespaces
declare independently, so `folders` can carry a different set of fields
from `paths`; the vocabularies under `enums` are shared between them,
since a value set is about the field, not about who carries it.

Parsed once per namespace by the validator, which hands the result to
the doc generator - the same resolve-once-and-reuse path `rule_catalog`
and `resolved_paths` already take.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DOC = "doc"
GROUP = "group"
RULES = "rules"

# The sub-tables an entry is made of, plus `inherit` - everything at the
# top level of an entry, so anything else there is a mistake.
ENTRY_TABLES = (DOC, GROUP, RULES)
STRUCTURAL_KEYS = (*ENTRY_TABLES, "inherit")

# Fields inside an entry's `rules` table that are the tool's own, not
# rule attachments. `folders` has none: a reserved name isn't one
# location, so neither "may be missing on disk" nor "points outside
# root" has anything to apply to.
CONTROL_FIELDS: dict[str, tuple[str, ...]] = {
    "paths": ("allow_missing", "outside_root"),
    "folders": (),
}
ALL_CONTROL_FIELDS = tuple(sorted({name for names in CONTROL_FIELDS.values() for name in names}))

# Keys inside a `<ns>.doc` / `<ns>.group` declaration table that describe
# the declaration rather than name a field.
DECLARATION_KEYS = ("names", "required", "multi", "defaults")

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
    defaults: dict[str, dict[str, Any]] = field(default_factory=dict)

    @property
    def control_names(self) -> tuple[str, ...]:
        return CONTROL_FIELDS.get(self.namespace, ())

    def names(self, kind: str) -> tuple[str, ...]:
        return self.doc_names if kind == DOC else self.group_names

    def required(self, kind: str) -> frozenset[str]:
        return self.doc_required if kind == DOC else self.group_required

    def values(self, kind: str) -> dict[str, frozenset[str]]:
        return self.doc_values if kind == DOC else self.group_values

    def is_multi(self, name: str) -> bool:
        return name in self.group_multi

    @staticmethod
    def enum_location(kind: str, name: str) -> str:
        return f"enums.{kind}.{name}"

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
    both namespaces - a value set describes the field, not who carries
    it."""
    table = _table(enums, kind).get(name)
    if not isinstance(table, dict) or not table:
        return None
    return frozenset(table.keys())


def parse_field_spec(data: dict[str, Any], namespace: str) -> tuple[FieldSpec, list[FieldIssue]]:
    """Read one namespace's field declarations. Reports what's wrong with
    the DECLARATION itself; checking entry values against it is the
    validator's job."""
    issues: list[FieldIssue] = []
    control = CONTROL_FIELDS.get(namespace, ())
    enums = data.get("enums", {})
    if not isinstance(enums, dict):
        enums = {}

    doc_table = _table(data, namespace, DOC)
    doc_names = _string_list(doc_table.get("names"), f"{namespace}.doc.names", issues)
    doc_required = _subset(
        doc_table.get("required"), f"{namespace}.doc.required",
        doc_names, f"{namespace}.doc.names", issues,
    )

    group_table = _table(data, namespace, GROUP)
    group_names = _string_list(group_table.get("names"), f"{namespace}.group.names", issues)
    group_multi = _subset(
        group_table.get("multi"), f"{namespace}.group.multi",
        group_names, f"{namespace}.group.names", issues,
    )
    group_required = _subset(
        group_table.get("required"), f"{namespace}.group.required",
        group_names, f"{namespace}.group.names", issues,
    )

    for kind, names in ((DOC, doc_names), (GROUP, group_names)):
        for name in names:
            if name in ALL_CONTROL_FIELDS:
                issues.append(FieldIssue(
                    "error", f"{namespace}.{kind}.names",
                    f"'{name}' is a control field this tool reads itself - it belongs in an entry's "
                    f"`rules` table and can't be redeclared here",
                ))
        if kind == GROUP:
            for name in names:
                if name in doc_names:
                    issues.append(FieldIssue(
                        "error", f"{namespace}.group.names",
                        f"'{name}' is also declared in {namespace}.doc.names - a field is either "
                        f"free-form documentation or an enum-backed grouping field, not both",
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

    defaults: dict[str, dict[str, Any]] = {
        DOC: _table(doc_table, "defaults"),
        GROUP: _table(group_table, "defaults"),
        # an entry's control fields sit in its `rules` table, so the
        # namespace-wide default for one sits in the namespace's
        # `rules` table, beside the blanket attachments
        RULES: {
            name: value
            for name, value in _table(data, namespace, RULES).items()
            if name in control
        },
    }

    spec = FieldSpec(
        namespace=namespace,
        doc_names=doc_names,
        doc_required=doc_required,
        doc_values=doc_values,
        group_names=group_names,
        group_multi=group_multi,
        group_required=group_required,
        group_values=group_values,
        defaults=defaults,
    )
    return spec, issues
