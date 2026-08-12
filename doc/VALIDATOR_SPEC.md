# Validator Specification

What `fs_org_kit.validator` checks, split into two categories, and why
each check is in the category it's in.

## The split

**Validate** - is the file structurally sound and complete enough to be
*acted on*. Failing a validate-level check means the standard can't be
trusted to mean what it says: a broken cross-reference, a required
field left empty, a value of the wrong type or outside its enum. These
are always **errors** - they block the runner from running at all (see
`fs_org_kit/runner.py`, which validates first and aborts on any error).

**Lint** - is the file well-formed by *convention*, given that it's
already structurally sound. A lint issue never blocks anything from
running; it's a nudge toward consistency and scannability - value
formatting (`root` should end in `/`), naming convention (reserved
folder names should start with `_`), leftover template placeholders,
declaration order. These are always **warnings**.

The test that decides which bucket a check belongs in: **if this were
wrong, would acting on the file do the wrong thing, or would it just
look inconsistent?** Wrong thing → validate. Looks inconsistent → lint.

Both run by default. `--validate-only` / `--lint-only` narrow to one;
`--only <category>` narrows further to specific parts of the file (see
`fs_org_kit.validator --help`).

---

## Validate

### Top-level structure

- `root`, `meta`, `paths`, `folders`, `enums` tables must all be
  present
- `root` must be a string

### `meta`

- `schema_version`, `standard_version`, `schema_date`, `standard_date`
  must all be present
- `schema_version` / `standard_version` must be strings
- `schema_version`'s major must match `standard_version`'s major
- `schema_version`'s major must be one this validator supports (a
  mismatch here **stops all further checks** - running v1-shaped checks
  against an incompatible grammar would just produce misleading noise)

### Rule references and attachments

- every `rules.<id>` reference (per-path, blanket, cross, or via
  `inherit.rules`) must resolve to a rule that actually exists in some
  discovered tier (bundled / `rules.own/` / `rules.external/`)
- a rule's declared `scope` must be compatible with where it's attached
  (a `single`-only rule can't go under `paths.cross`, a `cross`-only
  rule can't attach to one path)
- every rule attachment must have a non-empty `reason`
- every param the rule declares with no default in its own manifest
  must be supplied at the attachment site
- a param supplied that isn't declared in the rule's manifest is
  flagged (an unknown key in a schema-defined table - a structural
  concern, not a formatting one)

### Field declarations

Each namespace (`paths`, `folders`) declares what its entries may carry
in its own `attributes` table, and the two are read independently - see
doc/DESIGN.md.

- `attributes.names`, `attributes.required`, `attributes.group.names`,
  `attributes.group.multi`, `attributes.group.required` must each be a
  list of strings, with no name listed twice
- a name in `attributes.required` must appear in `attributes.names`; a
  name in `attributes.group.multi` / `.required` must appear in
  `attributes.group.names`
- the same name can't be both a documentation and a grouping field
- an attribute can't be named after one of an entry's
  structural keys (`group`, `rules`, `inherit`)
- a grouping field with no `enums.group.<field>` table is a warning: it
  still groups, but its values go unchecked

### Path and folder entries

- a `[paths."..."]` or `[folders.reserved."..."]` entry carries its
  attributes directly, and its `group`, `rules` and `inherit`
  keys must each be a table
- a field on an entry, or in its `group` table, that its namespace never
  declared is flagged
- every field in `attributes.required` / `attributes.group.required`
  must be non-empty, even after inheritance
- an attribute must be a string or a list of strings, and its
  values must come from `enums.attributes.<field>` if that table exists
- a grouping field's value must be one of `enums.group.<field>`, or a
  list of them when the field is declared in `attributes.group.multi`
  (a list where one value is expected, or a bare value where a list is,
  is an error either way)
- a rule attached under `paths."<key>".rules` where `[paths."<key>"]`
  itself was never declared (no own content, no `inherit`) is an
  error - an orphaned attachment, not an under-filled-out entry
- `paths.cross[i].paths` must be a non-empty list of strings

### `inherit`

- `inherit`, when present, must be a table, with one key per part of
  the entry it fills (`attributes` / `group` / `rules`), plus `exclude_rules`
- `inherit.attributes` / `inherit.group` / `inherit.rules`, when set, must
  reference a key that actually exists in the same namespace (a path can only
  inherit from a path, a reserved folder entry only from another
  reserved folder entry)
- an inheritance chain (`C` inherits `B` inherits `A`) must not cycle
- `inherit.exclude_rules` requires `inherit.rules` to be set - there's
  nothing to exclude from otherwise
- a key inside `inherit` other than `attributes` / `group` / `rules` /
  `exclude_rules` is flagged

### Rule discovery integrity

- a discovered rule manifest with a name/version mismatch, missing
  checker script, invalid TOML, or an out-of-enum `severity`/`scope`
  is an error for that rule (it doesn't enter the catalog at all)
- an external-tier rule falsely claiming `overrides_bundled = true` is
  flagged - validate-level even though it's a warning, since it's about
  which rule actually runs (see doc/DESIGN.md for why external never
  overrides)

---

## Lint

- `root` should end with a trailing slash
- a path key should end with a trailing slash (`some/path/`, not
  `some/path`)
- `schema_version` / `standard_version` should look like
  `major.minor` (e.g. `"1.0"`) - malformed values don't break
  anything (the major-compatibility check just silently skips), so
  this is a format nitpick, not a validate-level failure
- reserved folder names should start with the standard's reserved
  prefix (`_` by default - see `[folders.reserved]`'s `prefix` field)
- a list-valued attribute shouldn't contain leftover empty
  placeholder entries (`""`) - the list itself is structurally fine,
  this just means some entries were never filled in
- there should be at least one cataloged path (an empty `[paths]` with
  no entries isn't wrong, just probably not useful yet)
- a namespace with entries should declare some fields (without
  `<ns>.attributes.names` or `<ns>.attributes.group.names`, unknown-field
  checking can't run for its entries and the doc generator has nothing
  to render - worth knowing about, but the file still functions)
- **path keys, reserved folder names, and abbreviations should be
  declared in alphabetical order** - makes scanning and diffing the
  file predictable. Checked against each table's *declaration order in
  the source file*, not case-sensitively exact byte order - see
  implementation notes below.

---

## Implementation notes

- Every issue carries a `kind` (`"validation"` or `"lint"`) alongside
  its `level` (`"error"` or `"warning"`). In the current implementation
  every validate-level issue is also `level="error"` and every
  lint-level issue is `level="warning"` - the two axes happen to align
  today, but they're tracked separately (`Issue.kind` vs `Issue.level`)
  because that alignment isn't a hard rule the code enforces, just how
  every check has been written so far.
- Alphabetical order is checked by comparing a table's key iteration
  order (which `tomllib` preserves as source declaration order) against
  `sorted()` of the same keys, case-insensitively. A single
  out-of-order key produces one warning naming both the key and what it
  should sort after, rather than one warning per key that's out of
  place - re-sorting the whole table clears it in one pass either way.
