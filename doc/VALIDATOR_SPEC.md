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

### Path and folder entries

- a `[paths."..."]` or `[folders.reserved."..."]` entry must be a
  table
- a field on an entry not declared in the namespace's
  `attributes.names` is flagged
- `purpose` and `lifecycle` must be non-empty, even after inheritance
  and standard-wide defaults are applied
- `lifecycle` must be one of `enums.paths.lifecycle`
- `origin` must be a non-empty list of strings, each one of
  `enums.paths.origin`
- `use_for` / `not_for`, when present, must be lists
- `allow_missing`, when present, must be a boolean
- `outside_root`, when present, must be a boolean
- a path key that resolves outside `root` - absolute (`/etc/nginx/`),
  home-relative (`~/.config/`), or walking up (`../sibling/`) - is an
  error unless that entry declares `outside_root = true`. Joining an
  absolute key onto `root` silently discards `root`, so this is opt-in
  rather than implicit (see doc/DESIGN.md)
- `outside_root = true` on a key that resolves *inside* root is also an
  error: a flag claiming something untrue misleads the next reader as
  much as a missing one
- `outside_root` reaching an entry through `inherit` or
  `paths.attributes.defaults` is an error. Like `reason`, it must be
  written on the entry it applies to - a flag whose job is to make one
  thing deliberate is worth nothing if it can arrive from elsewhere
- `[[paths.cross]]` carries the same flag, covering every path it lists,
  with the same both-ways checks
- a rule attached under `paths."<key>".rules` where `[paths."<key>"]`
  itself was never declared (no own content, no `inherit`) is an
  error - an orphaned attachment, not an under-filled-out entry
- `paths.cross[i].paths` must be a non-empty list of strings

### `inherit`

- `inherit`, when present, must be a table
- `inherit.attributes` / `inherit.rules`, when set, must reference a
  key that actually exists in the same namespace (a path can only
  inherit from a path, a reserved folder entry only from another
  reserved folder entry)
- an inheritance chain (`C` inherits `B` inherits `A`) must not cycle
- `inherit.exclude_rules` requires `inherit.rules` to be set - there's
  nothing to exclude from otherwise
- a key inside `inherit` other than `attributes` / `rules` /
  `exclude_rules` is flagged

### Rule discovery integrity

- a discovered rule manifest with a name/version mismatch, missing
  checker script, invalid TOML, or an out-of-enum `severity`/`scope`
  is an error for that rule (it doesn't enter the catalog at all)
- an external-tier rule falsely claiming `overrides_bundled = true` is
  flagged (see DESIGN.md - this is a correctness/integrity concern
  about *which rule actually runs*, not a formatting one, so it's
  validate-level even though it's a warning rather than an error)

---

## Lint

- `root` should end with a trailing slash
- a path key should end with a trailing slash (`some/path/`, not
  `some/path`). A key that resolves *outside* root is no longer a lint
  matter at all - see `outside_root` under Validate.
- `schema_version` / `standard_version` should look like
  `major.minor` (e.g. `"1.0"`) - malformed values don't break
  anything (the major-compatibility check just silently skips), so
  this is a format nitpick, not a validate-level failure
- reserved folder names should start with the standard's reserved
  prefix (`_` by default - see `[folders.reserved]`'s `prefix` field)
- `use_for` / `not_for` shouldn't contain leftover empty placeholder
  entries (`""`) - the list itself is structurally fine, this just
  means some entries were never filled in
- there should be at least one cataloged path (an empty `[paths]` with
  no entries isn't wrong, just probably not useful yet)
- `paths.attributes.names` shouldn't be empty (without it, unknown-field
  checking can't run for any path entry - worth knowing about, but the
  file still functions)
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
