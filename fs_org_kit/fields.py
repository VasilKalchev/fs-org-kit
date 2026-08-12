"""
fs_org_kit.fields - the three kinds of field an entry can carry, and the
per-namespace declaration that says which name is which kind.

A `[paths."..."]` or `[folders.reserved."..."]` entry mixes fields that
mean very different things, and the difference is not visible from the
value:

  control      `allow_missing`, `outside_root` - read by the tool itself.
               Fixed set, owned by this package, never user-declared:
               they change what the runner and the sandbox actually do,
               so a standard can't rename or invent one.

  grouping     enum-backed, declared in `[<namespace>.grouping]`, checked
               against `enums.<namespace>.<field>`. Their job is to sort
               entries into buckets (`lifecycle`, `origin` are the
               examples the bundled template ships) - a closed vocabulary
               is what makes that possible.

  documentation  everything else, declared in
               `[<namespace>.attributes].names`. Free-form prose: a
               string, or a list of strings. Nothing reads their values;
               the doc generator renders whatever is there.

Which names fall in the last two groups is entirely the user's choice,
including the ones this project's own template happens to use - nothing
in the code knows what `purpose` or `lifecycle` mean. The two namespaces
declare independently: `folders` can carry a different set of fields
from `paths`, with its own vocabularies under `enums.folders.*`.

Parsed once per namespace by the validator, which hands the result to
the doc generator - the same resolve-once-and-reuse path `rule_catalog`
and `resolved_paths` already take.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Fields the tool reads itself, per namespace. `folders` has none: a
# reserved name isn't one location, so neither "may be missing on disk"
# nor "points outside root" has anything to apply to.
CONTROL_FIELDS: dict[str, tuple[str, ...]] = {
    "paths": ("allow_missing", "outside_root"),
    "folders": (),
}

# Keys on an entry that are structure, not content - so neither kind of
# declaration lists them, and the unknown-field check skips them.
STRUCTURAL_KEYS = ("rules", "inherit")

MISSING_GROUPING_ENUM = "missing-grouping-enum"
FIELD_DECLARATION_CODE = "field-declaration"


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
    grouping_names: tuple[str, ...] = ()
    grouping_multi: frozenset[str] = frozenset()
    grouping_required: frozenset[str] = frozenset()
    grouping_values: dict[str, frozenset[str]] = field(default_factory=dict)

    @property
    def control_names(self) -> tuple[str, ...]:
        return CONTROL_FIELDS.get(self.namespace, ())

    @property
    def required_names(self) -> tuple[str, ...]:
        """Declared order, documentation fields first - so a fully empty
        entry reports its missing fields in the order they'd be written."""
        return tuple(
            [n for n in self.doc_names if n in self.doc_required]
            + [n for n in self.grouping_names if n in self.grouping_required]
        )

    def known_names(self) -> set[str]:
        return {*self.doc_names, *self.grouping_names, *self.control_names}

    def is_multi(self, name: str) -> bool:
        return name in self.grouping_multi

    def enum_location(self, name: str) -> str:
        return f"enums.{self.namespace}.{name}"

    def is_declared(self) -> bool:
        """False when a namespace declares no fields at all - the point
        where unknown-field checking has nothing to compare against."""
        return bool(self.doc_names or self.grouping_names)


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


def parse_field_spec(data: dict[str, Any], namespace: str) -> tuple[FieldSpec, list[FieldIssue]]:
    """Read one namespace's field declarations. Reports what's wrong with
    the DECLARATION itself; checking entry values against it is the
    validator's job."""
    issues: list[FieldIssue] = []
    control = CONTROL_FIELDS.get(namespace, ())

    attributes = _table(data, namespace, "attributes")
    doc_names = _string_list(attributes.get("names"), f"{namespace}.attributes.names", issues)
    doc_required = _subset(
        attributes.get("required"), f"{namespace}.attributes.required",
        doc_names, f"{namespace}.attributes.names", issues,
    )

    grouping = _table(data, namespace, "grouping")
    grouping_names = _string_list(grouping.get("names"), f"{namespace}.grouping.names", issues)
    grouping_multi = _subset(
        grouping.get("multi"), f"{namespace}.grouping.multi",
        grouping_names, f"{namespace}.grouping.names", issues,
    )
    grouping_required = _subset(
        grouping.get("required"), f"{namespace}.grouping.required",
        grouping_names, f"{namespace}.grouping.names", issues,
    )

    for name in doc_names:
        if name in control:
            issues.append(FieldIssue(
                "error", f"{namespace}.attributes.names",
                f"'{name}' is a control field this tool reads itself - it's always allowed on an entry "
                f"and can't be redeclared as a documentation field; drop it from the list",
            ))
    for name in grouping_names:
        if name in control:
            issues.append(FieldIssue(
                "error", f"{namespace}.grouping.names",
                f"'{name}' is a control field this tool reads itself - it can't be used as a grouping field",
            ))
        if name in doc_names:
            issues.append(FieldIssue(
                "error", f"{namespace}.grouping.names",
                f"'{name}' is also declared in {namespace}.attributes.names - a field is either "
                f"free-form documentation or an enum-backed grouping field, not both",
            ))

    enums = _table(data, "enums", namespace)
    grouping_values: dict[str, frozenset[str]] = {}
    for name in grouping_names:
        table = enums.get(name)
        if not isinstance(table, dict) or not table:
            issues.append(FieldIssue(
                "warning", f"enums.{namespace}.{name}",
                f"grouping field '{name}' has no value vocabulary - its values won't be checked "
                f"(declare them under [enums.{namespace}.{name}])",
                MISSING_GROUPING_ENUM,
            ))
            grouping_values[name] = frozenset()
        else:
            grouping_values[name] = frozenset(table.keys())

    spec = FieldSpec(
        namespace=namespace,
        doc_names=doc_names,
        doc_required=doc_required,
        grouping_names=grouping_names,
        grouping_multi=grouping_multi,
        grouping_required=grouping_required,
        grouping_values=grouping_values,
    )
    return spec, issues
