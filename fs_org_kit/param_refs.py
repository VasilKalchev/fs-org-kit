"""
fs_org_kit.param_refs - resolves rule-param values that reference
another location in the standard, instead of a hand-typed literal.

The problem this solves: a rule script never sees the parsed standard
directly (deliberately - see doc/RULES.md) - only a location and its
own `params`. Several rules need something that's already declared
elsewhere in the standard (uncataloged-reserved-v1's `cataloged` wants
[folders.reserved]; spelling-abbreviations-v1's `abbreviations` wants
[abbreviations]; a tag-checking rule wants a [tags."..."] namespace).
Without this module, the only option was retyping that data by hand at
every attachment site, kept in sync manually - a real, documented
limitation. Special-casing the runner per rule was rejected as a fix
(see doc/DESIGN.md) - this module is the generic alternative: ANY
param, on ANY rule, can reference ANY value elsewhere in the standard,
with zero rule-specific code in the runner or validator.

Syntax: a param value that's a one-key TOML inline table, {ref = "..."},
is a reference rather than a literal - e.g.:

    [paths."archive/".rules.uncataloged-reserved-v1.params]
    cataloged = { ref = "folders.reserved" }

`dotted.path` walks plain, unquoted top-level keys - it can reach
`folders.reserved` or `tags.state`, but not a `[paths."some/path/"]`
entry, whose key contains characters a dotted path can't express (if
you need that, the runner-generated blanket mechanisms - paths.rules,
folders.rules - are almost certainly what you actually want instead).

A ref expands to **whatever is at that path, verbatim** - a table, a
list, a string, a number, a boolean. It is substitution, not
interpretation: this module never projects a table down to its keys or
strips anything out of it, because deciding which parts of
[folders.reserved] are entries and which are schema-level config is
knowledge about that table, and the core doesn't own it. The rule
receiving the value does, and takes what it needs. The only failure is
a path that doesn't resolve at all.

Resolution happens once and flows into both consumers that need it -
the validator (to catch a broken reference before the runner ever
touches the filesystem) and the runner (to build the actual JSON
payload a rule script receives) - the same "resolve once, reuse"
pattern already used for rule discovery and inheritance.
"""

from __future__ import annotations

from typing import Any

REF_KEY = "ref"

_MISSING = object()


def is_ref(value: Any) -> bool:
    return isinstance(value, dict) and set(value) == {REF_KEY} and isinstance(value.get(REF_KEY), str)


def _walk(data: dict[str, Any], dotted_path: str) -> Any:
    current: Any = data
    for part in dotted_path.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def expand_param_value(value: Any, data: dict[str, Any]) -> tuple[Any, str | None]:
    """Returns (expanded_value, error_or_None). A non-ref value passes
    through unchanged, with no error."""
    if not is_ref(value):
        return value, None

    dotted_path = value[REF_KEY]
    target = _walk(data, dotted_path)

    if target is _MISSING:
        return value, f'ref "{dotted_path}" does not resolve to anything in the standard'
    return target, None


def expand_params(params: dict[str, Any], data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Expands every {ref: "..."} value in `params` (one level - a
    resolved value is never itself re-searched for nested refs).
    Returns (expanded_params, error_messages); each error names the
    param it's about."""
    expanded: dict[str, Any] = {}
    errors: list[str] = []
    for key, value in params.items():
        new_value, err = expand_param_value(value, data)
        expanded[key] = new_value
        if err:
            errors.append(f"`{key}`: {err}")
    return expanded, errors
