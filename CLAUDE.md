# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

fs-org-kit is a tool for making a personal filesystem organization standard
machine-enforceable. Users write a `fs-org-std.toml` describing how a
directory tree should be organized (paths, their purpose/lifecycle, and
which rules apply to them); a validator, runner, and doc generator then
check/fix/document that standard against the real filesystem. Status: 0.1
complete, with unreleased work on top (see doc/CHANGELOG.md).

Read doc/DESIGN.md before making architectural changes — it records *why*
things are structured the way they are (rules-on-disk vs. embedded,
single discovery pass shared across tools, structural fixability, etc.),
and repeating a decision already reverted there wastes a cycle.

Design docs, the changelog, the rule-authoring guide, and the validator
spec all live under `doc/` (`CHANGELOG.md`, `DESIGN.md`, `RULES.md`,
`TESTING.md`, `VALIDATOR_SPEC.md`); only `README.md` and this file stay
at the repo root.

Keep documentation concise: state the decision and its constraint, then
stop. Rationale belongs in `doc/DESIGN.md` once, referenced from
elsewhere rather than restated.

## Commands

```bash
pip install -e ".[dev]"             # install package + pytest

pytest                               # run everything: core package + bundled rules
pytest tests/                        # core package only
pytest rules/                        # bundled rules only
pytest tests/test_inherit.py -v      # single module
pytest tests/test_runner.py::TestMainIntegration::test_inheritance_follows_a_real_filesystem_move -v
pytest -k "scope_mismatch"           # single test by name (any file)

python -m fs_org_kit.validator <standard.toml> [flags]   # or: fs-org-validate
python -m fs_org_kit.runner    <standard.toml> [--fix]   # or: fs-org-run
python -m fs_org_kit.doc       <standard.toml> [flags]   # or: fs-org-doc
```

There is no build/lint step beyond pytest — no separate linter/formatter is configured in this repo.

### Testing a rule standalone (no standard/validator/runner needed)

```bash
python rules/<rule-name>-v<N>/<rule-name>-v<N>-check.py \
    --path /tmp/some/dir --params '{"allowed": ["jpg", "png"]}'
```

### Rule test placement — not in `tests/`

Core package tests live in `tests/`, one file per module. Each bundled
rule's tests live **inside that rule's own directory**
(`rules/<rule>/test_<rule_with_underscores>.py`), not in `tests/` — this is
deliberate (see doc/TESTING.md/doc/RULES.md) so a rule's tests travel with it when
copied into someone's `rules.own/` or `rules.external/`. `pytest.ini`'s
`testpaths = tests rules` picks up both from the repo root.

When adding rule tests, invoke the script via `subprocess` exactly as the
runner does — never import the script's internals — since that's the real
documented protocol contract. Filter validator test assertions on
`Issue.location` (dotted path), not `Issue.message` (describes what's
wrong, not which field).

`tests/test_docs_current.py` is the exception to "one file per module" —
it tests the docs, failing when a test count in `doc/TESTING.md`, the
rule count in `README.md`, or a `doc/*.md` reference anywhere drifts from
what's on disk. Update the docs alongside the change and it stays green;
it also fails when a new bundled rule arrives without tests.

### Adding a rule

Use the `new-rule` skill (`.claude/skills/new-rule/`) — it copies
`rules/_template-<scope>-v1/`, a complete tested rule, with the naming
and protocol invariants already correct, and ends at the doc updates
`test_docs_current.py` checks. A rule directory whose name starts with
`_` is skipped by discovery in every tier, silently — that's what keeps
the templates out of the catalog.

## Architecture

### Two file types, two rates of change

- **The standard** (`fs-org-std.toml`, user-owned, grammar in
  `fs-org-std.template.toml`) — paths, their fields, and which rules
  attach where. Changes constantly.
- **Rules** — small versioned units living on disk in three trust tiers,
  each a directory with a manifest + scripts:
  - `rules/` in this repo — bundled, project-maintained
  - `rules.own/` (sibling of the user's standard) — user's own, merged automatically
  - `rules.external/` (sibling of the user's standard) — third-party, requires `--include-external` opt-in

  Rule identity is the directory name (`<rule-name>-v<major>`), global
  across tiers. `rules.own/` can override a same-named bundled rule only
  with `overrides_bundled = true` in its manifest; `rules.external/` can
  never override anything, even if it claims to.

### Module responsibilities (`fs_org_kit/`)

- `discovery.py` — the single source of truth for what rules exist right
  now, across all three tiers, with the precedence rules above. Imported
  directly by the validator; runner and doc generator reuse
  `validator.rule_catalog` afterward rather than re-discovering — one
  discovery pass per invocation. It also owns the manifest schema
  (`SEVERITY`, `SCOPE`, `MANIFEST_KEYS`): that's the tool's half of the
  rule contract, not something a file on disk configures — see
  doc/DESIGN.md, "The rule manifest schema lives in code".
- `cache.py` — owns *where* rules keep state between runs, and the only
  thing that manages it (`fs-org-cache --list` / `--clear [rule-id]`).
  A rule declares `uses_cache = true` in its manifest; the runner then
  creates `<cache-root>/rules/<rule-id>/` and passes it as
  `--cache-dir`. A rule never resolves a location itself — that would
  leave the core with no inventory to report on or clear, and copy the
  per-platform path logic into every caching rule. A rule that doesn't
  declare it never receives the flag (which is what kept this additive
  — every existing rule's argparse would reject an unknown flag), and a
  rule that does must still work without it (standalone runs, unusable
  location) by not caching at all.
- `path_keys.py` — the single place a catalog key becomes a real path
  (`resolve_key`). A key may be relative, absolute, `~`-relative or walk
  up out of `root`, and resolves to exactly where it names. Note the
  accident it exists for: `root / "/etc/x"` is `/etc/x`, and a join
  never expands `~`, so a bare join silently lands elsewhere. Never use
  one.
- `sandbox.py` — the audit-hook harness every rule script runs inside
  (both halves in one module so the policy the runner *builds* and the
  policy the child *enforces* can't drift). Blocks network,
  subprocess, native calls, and writes outside cache+temp for a
  checker, plus root and its own targets for a fixer. Capabilities are
  declared in a manifest's `[sandbox]` table — the runner reads a
  declaration and never special-cases a rule by name. It is a guard
  against accidents, **not** a security boundary; don't describe it as
  one. `--no-sandbox` disables it.
- `fields.py` — what a namespace declares its entries may carry:
  attributes (written on the entry itself) and grouping
  fields (in its `group` table), declared under
  `<ns>.attributes`. **No field name is hardcoded anywhere in the
  package** — a standard names its own fields, and app behavior must
  never key on one. Parsed once by the validator (`path_fields` /
  `folder_fields`) and reused by the doc generator.
- `inherit.py` — resolves `[paths."...".inherit]` (per-part
  inheritance for the PARA-style "state via folder location" pattern)
  once, before validation. One `inherit` key per part of an entry
  (`attributes` / `group` / `rules`, plus `exclude_rules`), each free to name a
  different source. `resolve_entries()` produces a flattened
  `ResolvedEntry` per catalog key (`.attributes` / `.group` / `.rules`) so
  nothing downstream needs its own inheritance-walking logic.
- `validator.py` — read-only. Validates TOML structure, resolved rule
  attachments/scope compatibility, resolved inheritance, and lint checks.
  Issues are tagged `kind` (`validation`/`lint`) and `level`
  (`error`/`warning`) — see doc/VALIDATOR_SPEC.md for the full validate/lint
  split and rationale.
- `runner.py` — calls the validator first and aborts (exit 2) on any
  validation error before touching the filesystem; reuses
  `validator.rule_catalog` rather than re-discovering. Resolves rule
  attachments (per-path, `paths.rules` blanket, `paths.cross`,
  `folders.rules` blanket) into subprocess invocations. `--fix` invokes a
  rule's `-fix.py` directly when present; rules without a fixer still run
  their checker even under `--fix`. Exit codes: 0 clean, 1
  violation/unfixable/broken, 2 invalid standard.
- `doc.py` — validates first (same abort-on-error stance), then generates
  Markdown from the *resolved* standard (inherited fields show their
  actual value, not blank) — ToC plus a section per namespace. It reads
  the validator's resolved view only, never re-deriving grammar of its
  own.

### The rule protocol (runner ↔ script)

Rule scripts run as **plain subprocesses**, never imported — crash
isolation, dependency isolation, and directly debuggable on the CLI. See
doc/RULES.md for the full authoring guide; the essentials:

- Invocation: `--path <p>` (scope=single) or `--paths <p> [--paths <p> ...]`
  (scope=cross, 2+), always `--params '<json>'`; fixers additionally get `--fix`.
- Script never receives `purpose`/`notes`/`lifecycle`/etc. from the
  standard — only location(s) and `params`. If behavior needs to vary per
  attachment, that variation must be a declared param.
- Checker stdout is exactly one JSON line: `{"status": "ok"}` or
  `{"status": "violation", "message": "..."}`.
- Fixer is **self-contained** — detects *and* resolves in one pass, not
  check-then-fix. Stdout is one JSON line with one of four statuses:
  `ok` / `violation` (found, couldn't act) / `fixed` / `unfixable`.
- Exit code 0 = script ran, read stdout for the verdict. Nonzero = the
  script itself is broken (bad params, bad path) — reason goes to
  stderr, surfaced by the runner as `broken`, distinct from finding a violation.
- `-v<major>` in the directory name is part of rule identity, not a
  revision marker — `name-v1/` and `name-v2/` coexist independently.
  Manifest `version`'s major must match the directory suffix (checked,
  not convention). Breaking behavior/param changes get a new
  `-v<major>` directory; non-breaking refinements bump `version`'s minor
  in place.
- Rules are Python-only (see doc/RULES.md's "Language policy" — readability
  for review, no bash, cross-platform).

### Design principles worth knowing before changing shared code

- **Resolve once, flatten, reuse** — this pattern recurs for rule
  discovery (validator discovers, the runner reuses `rule_catalog`) and
  for inheritance (`resolve_entries()` runs once; validator, runner and
  doc all just read `resolved.attributes`/`.group`/`.rules`). Don't
  reintroduce a second discovery/resolution pass when adding a new
  consumer — thread the existing resolved data through instead.
- **Fixability is structural** — a rule is fixable iff its `-fix.py`
  exists on disk; this is not a manifest field. Don't add one back.
- **`reason` at every rule attachment site is required and never
  inherited/defaulted** — hardcoded in the validator, deliberately, to
  force per-attachment justification.
- **A cataloged path that isn't on disk is skipped silently** by the
  runner, and never reported. "This path should exist" is a rule's
  question, not the runner's — there is no `allow_missing` any more.
- **Checkers really can't write now** — `sandbox.py` enforces it. A rule
  that needs a blocked capability declares it in `[sandbox]`; never add
  a runner-side exception for a specific rule. Rule scripts run
  standalone are *not* sandboxed, so a rule can pass its own tests and
  still fail under the runner — check both when touching a fixer.
- A rule may keep helper modules beside its scripts (`_shared.py`), and
  several do. The sandbox puts the script's directory on `sys.path` to
  make that work, since `runpy.run_path` doesn't.
