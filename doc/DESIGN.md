# Design Decisions and Architecture

This document captures the important structural and architectural decisions in fs-org-kit, and the reasoning behind them.

## Core Architecture

### Rules live on disk, not in the standard

Originally, rule *definitions* lived inside `fs-org-std.toml` as a `[rules]` catalog table. They were split out because:

1. Rule definitions change at a completely different rate than a personal standard's content
2. Sharing rules with others, or letting them contribute new ones, meant no one could modify someone else's standard file to add a rule
3. Rules are versioned independently (`file-extensions-v1`, `file-extensions-v2`, etc.), and that versioning model is easier to manage with files on disk than embedded table entries

Rules now live in three trust tiers:
- **Bundled** (`rules/` in the fs-org-kit repo) - project-maintained, always available
- **Own** (`rules.own/` in the user's standard directory) - user's hand-written rules, merged automatically
- **External** (`rules.external/` in the user's standard directory) - third-party, never included by default, requires `--include-external` opt-in

This three-tier model is enforced structurally (not as a convention or config option) - the runner, validator, and discovery module all understand these exact paths.

### Discovery is centralized

`fs_org_kit/discovery.py` is the single source of truth for "what rules exist right now." It's imported directly by the validator (to resolve rule references in a standard); the runner and doc generator both reuse `validator.rule_catalog` afterward rather than calling `discover_rules()` again themselves - one discovery pass per invocation, not two or three.

This prevents the tools from having subtly different views of what rules exist, which would be a silent correctness bug.

### Validator and runner share the rule catalog

Once validation passes, the runner doesn't call `discover_rules()` again - it reuses `validator.rule_catalog` directly. This ensures:

1. The runner never acts on a rule that validation rejected
2. The same collision/precedence logic (own overrides bundled, external never overrides) applies consistently
3. If validation sees `include_external=True`, the runner sees it too

The validator's `Validator.__init__` now takes `include_external` and `bundled_rules_dir` parameters, threading the runner's CLI flags through to the discovery step.

### Fixability is structural, not declared

Originally, rule manifests had a `fix` field saying whether a rule could be fixed. This was changed to infer fixability from what files exist on disk:

- A rule is fixable if its `-fix.py` file exists
- The runner discovers this at runtime, not from the manifest

This has two benefits:
1. One less field that can fall out of sync with reality
2. Clearer intent - either the fixer exists on disk or it doesn't, with no possibility of a manifest claiming something that isn't true

### The core owns where rules cache, not the rules

A rule that keeps state between runs (currently only `duplicate-files-v1`, which caches file hashes) declares `uses_cache = true` in its manifest. The runner then creates a rule-private directory and passes it as `--cache-dir`. The rule stores whatever it wants inside; it never resolves a location itself.

The first implementation had it the other way round - the rule computed its own per-platform cache path. That works, and it's wrong, because it leaves the core with **no inventory**: nothing knows which rules cache, where, or how much space they're using, so nothing can report on it or clear it. The location also has to be reimplemented in every caching rule, free to drift between them.

Inverting it gives:

- **One layout, one owner** - `<cache-root>/rules/<rule-id>/`, resolved in `fs_org_kit/cache.py` and nowhere else
- **Real management** - `fs-org-cache --list` / `--clear [rule-id]`. The per-rule subdirectory means the core can clear one rule's cache without knowing anything about what's inside it, the same boundary the runner↔script protocol draws everywhere else
- **One cleanup command that stays correct** as more caching rules appear - which matters because nothing deletes this automatically, including `pip uninstall` (pip removes only what it installed and has no post-uninstall hook)

Two constraints fall out of it:

- **A rule that doesn't declare `uses_cache` never receives the flag.** Passing `--cache-dir` to every rule would break the argument parsing of every existing rule, bundled or third-party, and force a protocol version bump. Gating it on the declaration made this a strictly additive change.
- **A rule declaring it must still work without it.** The flag is absent when the script is run standalone, and when the directory can't be created (read-only or full filesystem). Both mean "run uncached" - the cache is an optimization, so losing it must cost speed, never correctness, and never trigger a fallback location of the rule's own choosing.

This is deliberately *not* the same shape as [fixability is structural](#fixability-is-structural-not-declared). Fixability has a structural signal - the `-fix.py` file either exists or it doesn't - so a manifest field would be a second source of truth. "This rule keeps state" has no such signal; a declaration is the only way to express it, and the core needs it *before* invoking the script in order to prepare the directory.

A per-rule `--clear-cache` flag was considered and rejected: after an uninstall the script implementing it is gone, which is exactly when a user wants to reclaim the space.

### Rules define their own semantics for params

The runner doesn't interpret rule params - it just passes them as JSON. This is essential for:

- **Folder rules** - `[[folders.rules]]` attachments apply to root, and the rule's own `params` control recursion, exclusion patterns, etc. The runner just invokes once; the rule walks.
- **Per-path rules** - if a rule wants to control behavior via `exclude`, `recursive`, `mode`, or anything else, those are its own params to interpret.

This keeps the runner simple (just a dispatcher) and gives rules full control over their behavior.

### Param values can reference elsewhere in the standard, generically - never a per-rule special case

Two bundled rules need a list that's already declared elsewhere in the
standard: `uncataloged-reserved-v1`'s `cataloged` wants
`[folders.reserved]`'s entry names, `spelling-abbreviations-v1`'s
`abbreviations` wants `[abbreviations]`'s keys. Because a rule script
never sees the parsed standard (only its own resolved `params` - see
above), the original-and-only option was retyping that list by hand at
every attachment site, kept in sync manually - a real, acknowledged
limitation, not a bug.

The fix is **not** runner code that knows about these two rules by
name - that would violate "rules define their own semantics for
params" directly above, and worse, would need extending every time
some other rule hit the same wall. Instead, `fs_org_kit/param_refs.py`
lets *any* param value, on *any* rule, be `{ref = "dotted.path"}`
instead of a literal - resolved to the table's keys (or the list) found
at that path elsewhere in the standard. The runner still has zero
rule-specific knowledge: it expands `{ref: ...}` the same way
regardless of which rule or param it's attached to, exactly like it
already doesn't care what `exclude` or `recursive` mean semantically.
This is wire-format sugar applied uniformly to values, not an
exception to "the runner doesn't interpret params" - the rule script
still only ever receives a plain resolved JSON value, same as always.

Resolution happens once (validator confirms every reference resolves
before the runner ever touches the filesystem; the runner then expands
the same way to build the actual JSON payload) - the same "resolve
once, reuse" pattern used for rule discovery and inheritance elsewhere
in this document.

### Scope is structural validation, not runtime

Rule scope (`single`, `cross`, `both`) is validated at the time a standard is checked:

- A `single`-scope rule attached under `paths.cross` is an error (caught at validation, exit 2)
- A `cross`-scope rule attached to a plain path is an error (caught at validation, exit 2)

This prevents the runner from ever having to deal with impossible attachment combinations - validation is the gatekeeper.

## Naming and File Organization

### Package structure

The project is a proper Python package (`fs_org_kit/`) with `pyproject.toml`. Modules:

- `fs_org_kit/discovery.py` - rule discovery across the three tiers
- `fs_org_kit/validator.py` - validates standards and their rule attachments
- `fs_org_kit/runner.py` - executes rules against the real filesystem
- `fs_org_kit/doc.py` - generates Markdown documentation

Console entry points are declared in `pyproject.toml` (`fs-org-validate`, `fs-org-run`, `fs-org-doc`, `fs-org-cache`); each module keeps a `main()` so `python -m fs_org_kit.validator` works identically without installing.

### File naming

- **Templates use kebab-case with `.template.` suffix** - `fs-org-std.template.toml`, `rule.template.toml` - so they visibly match the real file names and sort together
- **Python modules use underscores** - `fs_org_kit`, `validator.py`, `discovery.py` - because they need to be importable
- **Rule directories and manifests use the rule ID** - `file-extensions-v1/file-extensions-v1.toml`, `file-extensions-v1-check.py`, `file-extensions-v1-fix.py` - self-identifying outside their directory context

### Project name

**fs-org-kit** is deliberately literal over evocative. Someone encountering the name has no chance of guessing wrong about what it does.

## Schema and Data Modeling

### Schema versioning is separate from standard versioning

`fs-org-std.template.toml` tracks `schema_version` (the grammar it uses, e.g., 1.0) separately from `standard_version` (the content version, e.g., 3.2). This allows:

- The grammar to evolve independently of a user's personal standard
- Multiple standards to coexist at different schema versions
- Clear error messages when a standard is incompatible with a validator

### Attributes are self-describing

The validator reads its field lists and defaults from the file being checked:

- `paths.attributes.names` declares what fields are valid on a path
- `paths.attributes.defaults` provides default values
- `enums.paths.*` define the valid values for enum fields

This means the validator doesn't need code edits when the schema evolves - it adapts automatically.

### Paths use flat TOML keys

Paths are written as flat quoted keys (`[paths."media/img/"]`), not nested tables. This choice prioritizes:

1. **Grep-ability** - `grep "media/img" standard.toml` finds the entry without needing to know TOML nesting syntax
2. **Verbatim visibility** - the key is literally the path, with no escaping or indentation tricks
3. **Scannability** - all path entries line up at the same indentation level

The alternative (nested structure like `[paths.media.img]`) would be less scannable and harder to grep.

### `reason` is required at every attachment site, not inherited from the rule

When a rule is attached (`[[paths."x/".rules.file-extensions-v1]]`), the attachment must include a `reason` field explaining *why* this rule applies *here*. This reason is not inherited from the rule manifest, and can't be defaulted:

- It forces the standard author to think about each attachment individually
- It makes the standard more readable - scanning a file shows *every* reason a rule is applied
- It prevents silent defaulting that might hide misunderstandings

## Protocol and Invocation

### Rule-to-runner protocol is versioned independently

Rule manifests include `protocol_version`, separate from the rule's own `version`. This allows:

- The runner's command-line interface to evolve
- Old rules (v1 protocol) to coexist with new rules (v2 protocol) without rewriting
- Clear error messages when a rule uses an unsupported protocol version

### Fixer-specific protocol: self-contained, not check-then-fix

When a fixer is invoked, it doesn't check first and then fix - the `-fix.py` script is responsible for detecting the problem AND fixing it in one pass. It returns one of four statuses:

- `ok` - nothing needed fixing
- `violation` - found problems, couldn't fix them (e.g., permission denied)
- `fixed` - found problems and fixed them
- `unfixable` - found problems that are logically unfixable by the rule

This design:

1. Avoids redundant passes (check, then fix, then recheck)
2. Makes it clear that a fixer owns the full problem-solving, not the runner
3. Simplifies the runner's logic - just invoke once, read status

### Scripts run inside an audit-hook harness

Rule scripts run under `sys.addaudithook` (`fs_org_kit/sandbox.py`), which blocks network access, starting other processes, native/ctypes calls, and writes outside what the invocation is entitled to touch. `--no-sandbox` turns it off.

It is a guard against bugs and accidents, **not** a security boundary, and describing it as one would be wrong: the hook lives inside the interpreter it polices, so `ctypes` reaches straight past it, and nothing here constrains a rule that was malicious rather than careless. What it does catch is the class of mistake an author makes without meaning to - a checker that writes, a fixer that reaches outside the tree it was pointed at, a rule that quietly phones home - none of which was detectable before, because the convention was documented and entirely unenforced.

Two decisions shaped it:

**The policy is built in the parent, never derived in the child.** Anything the child worked out after installing the hook would have to be exempted from the hook, which is a hole. So the runner computes the writable set from the manifest's declarations plus the invocation's own targets, and passes it in.

**Capabilities are declared in the manifest, not special-cased in the runner.** `basename-sync-v1`'s fixer shells out to a user-provided script, so it declares `[sandbox] subprocess = true`; a fixer whose destination is a user-configured path the core can't know in advance declares `unrestricted_writes`. This is the same shape as `uses_cache`: the rule states a need, the core grants it uniformly, and the runner keeps no per-rule knowledge. It also puts the grant somewhere a reviewer reads before trusting a rule.

The writable set is `{cache, temp}` for a checker, and additionally `{root} ∪ {targets}` for a fixer. Targets are listed separately from root because a path may be outside root - that's what `outside_root` declares, and this is one of the things it declares it *for*.

A violation raises an exception deriving from `BaseException` rather than `Exception`, since rule scripts routinely wrap their work in `except Exception` and a swallowed violation would be reported as an ordinary failure or as success. Violations are also recorded, so even `except BaseException` can't turn one into a clean result.

## Validation vs. Execution

### Validator is read-only

The validator **never** modifies anything on disk. It reads a `.toml` file, parses it, validates it against the schema, and reports issues. That's all.

### Runner validates first, always

The runner's first step is to reuse the validator. If validation fails, the runner exits with code 2 and never touches the filesystem. This ensures:

- The standard is structurally sound before any rule runs
- Validation errors are reported consistently, whether running the validator or the runner

### Exit codes are meaningful

- **0** - Everything ran and produced no violations (or there was nothing to run)
- **1** - At least one rule returned `violation`, `unfixable`, or `broken`
- **2** - The standard itself is invalid (unreadable TOML, validation errors, etc.)

## Path/Folder Inheritance

### The problem it solves

PARA-style organization (and similar schemes) uses a folder's *location* as state - a project moves from `active/x/` to `archive/x/` when archived, and back if reactivated. Without inheritance, every archive/restore cycle means editing `fs-org-std.toml`: deleting one catalog entry, recreating another, re-declaring every attribute and rule attachment from scratch.

### The mechanism

An entry can inherit from another entry of the same kind (a path only from another path; a reserved folder entry only from another reserved folder entry) via an `inherit` sub-table:

```toml
[paths."archive/project-x/".inherit]
attributes = "active/project-x/"
rules = "active/project-x/"
exclude_rules = ["staleness-check-v1"]
```

- **`attributes`** - full inheritance, per-field override. Any field this entry sets itself wins; anything unset falls through to the source, then to a standard-wide default if one exists, then stays unset.
- **`rules`** - a **separate** opt-in from `attributes`, deliberately. Inheriting a path's descriptive text says nothing about whether you also want its rules blindly applied - keeping them independent avoids the surprise of a folder suddenly running rules nobody explicitly attached to it.
- **`exclude_rules`** - drops specific rule IDs from what `rules` would otherwise bring in. Requires `rules` to be set (validation error otherwise - nothing to exclude from).
- Chains are allowed (`C` inherits from `B` inherits from `A`); cycles are a validation error.
- If the same rule ID is both inherited (and not excluded) and separately declared on the entry itself, **both instances apply** - nothing silently overrides. To change an inherited rule's params, exclude it and redeclare it fresh. This was a deliberate choice to avoid "invisible" behavior: a config that looks like two declarations should behave like two declarations.

### `allow_missing`

A path attribute, independent of `inherit` (a path can be `allow_missing` without inheriting anything, and vice versa). Marks a cataloged path as one that may not currently exist on disk. Resolved at runtime by the runner (not the validator, which never touches the filesystem) - a missing path without this flag is reported as a problem and fails the run; with it, the runner silently skips invoking any rules for that path.

**Both sides of a state-varying pair need `allow_missing = true`, not just the "unusual" one.** Since only one of two alternate locations exists at any given time, whichever one *isn't* currently real needs to not be flagged as a problem - and that could be either side depending on current state. Marking only the archive location, say, works fine until the folder is *in* the archive location and the active one goes missing instead.

### Why `allow_missing` gets a defaults table entry, and other path attributes normally don't

Most path attributes (`purpose`, `notes`, `lifecycle`, ...) have no sensible standard-wide default - there's no universal answer to "what is this folder for." `allow_missing` is the exception: `false` (must exist) is a reasonable default for anything not marked otherwise. Rather than special-case this in code, `paths.attributes.defaults` is a real, generic mechanism - any attribute can have a standard-wide default declared there, resolved with the same precedence as everything else (explicit > inherited > standard-wide default > unset). It's just that in practice, `allow_missing` is currently the only field where declaring one makes sense.

### Why this is a separate module (`fs_org_kit/inherit.py`), not inline in the validator

Same reasoning as `discovery.py` for rules: resolution is needed by both the validator (to validate the *resolved* view, not the raw one - so a path that inherits `purpose` doesn't get flagged "missing purpose" just because it didn't type it itself) and the runner (to know which rules actually apply to which real, currently-existing path). One module, one place to get the precedence rules right, imported by both.

### Architecture: resolve once, flatten, then everything downstream is unaware inheritance exists

`resolve_entries()` runs as a pure data-transformation step before validation. It produces a `ResolvedEntry` per catalog key with final, flattened attributes and rules - the validator's field checks and the runner's invocation-building both just read `resolved.attributes`/`resolved.rules` and never need their own inheritance-walking logic. This mirrors the same "resolve once, flatten, reuse" pattern already used for rule discovery and the validator/runner relationship generally.

## Out-of-Root Path Keys

### The problem it solves

`root` is the tree the standard governs, and a catalog key is relative to it. But a personal filesystem doesn't stop at one tree: `~/.config/`, `/etc/`, an external drive's mount point are all worth cataloging and attaching rules to, and none of them sit under a `root` of, say, `~/usr/`.

### Why it's an opt-in flag rather than just accepting an absolute key

It was already "working", wrongly. `Path("/home/me/usr") / "/etc/nginx"` is `/etc/nginx` - Python's path join **discards** the left side when the right is absolute. So an absolute key typo'd into a standard would already have sent rules walking somewhere far outside root, with nothing anywhere saying so. `outside_root = true` turns a silent escape into a deliberate one, which is the same stance `overrides_bundled` takes for rule identity: the surprising thing is rejected by default, and one explicit field on the record opts out.

Three routes escape and all three need the flag - absolute (`/etc/`), home-relative (`~/.config/`), and walking up (`../sibling/`). The `..` case matters most: it escapes just as completely and is the easiest to write by accident.

### Why it is never inherited or defaulted

Hardcoded, like `reason`. A flag whose only job is to make one thing deliberate is worth nothing if it can arrive from somewhere else - a one-word edit to an unrelated entry must not be able to widen the set of directories the tool will walk into and, under `--fix`, write to. Arriving via `inherit` or `paths.attributes.defaults` is an error rather than a quiet acceptance.

### What it feeds

`fs_org_kit/path_keys.py` owns `resolve_key`, the single place a key becomes a real path, so all three escape routes are handled identically everywhere rather than being re-derived per consumer. The sandbox reads the flag's consequence: an out-of-root target is a place a fixer may write, and the policy can only know that because the standard said so.

Overlap detection compares keys in a normalized form, so `/srv/*/` and `srv/*/` are correctly *not* a collision while `~/x/` and `/home/me/x/` still are.

## Path Pattern Keys

### The problem it solves

A `[paths."..."]` entry is normally one exact location. A personal filesystem often has many structurally-identical folders under one prefix - one per client, one per numbered project - that all deserve the same `purpose`/`lifecycle`/rule attachments without hand-maintaining an otherwise-identical catalog entry per folder, kept in sync by hand as folders come and go. This sat in a real gap in the existing location vocabulary: exact path (`[paths."x/"]`), reserved *name* pattern anywhere (`[folders.reserved."_name"]`), or every folder anywhere (`[[folders.rules]]`) - nothing for "these N folders under this prefix are the same kind of thing."

### The mechanism

A `[paths."..."]` key may be a glob pattern (`fs_org_kit/path_patterns.py`) instead of a literal path - the same vocabulary already used everywhere for `exclude` params (`fnmatch`/`pathlib.Path.glob`: `*`, `**`, `?`, `[abc]`). No wrapper syntax needed to tell a pattern key from a literal one - a literal path can't legitimately contain a glob metacharacter anyway (see `naming-pattern-v1`'s portable-charset doc comment), so a key is a pattern iff it contains one.

Brace-expansion (`folder{1..3}/`) was considered and rejected - it has no stdlib support (a bash-ism, not part of POSIX `glob()` or Python's `glob`/`fnmatch`), and `folder[1-3]/` already covers the common numeric-range case with zero extra code or dependencies.

One pattern entry's attributes and rule attachments apply identically to every real folder it matches - invoked once per match, exactly like `[[folders.rules]]` already invokes once per real folder on disk. This required zero changes to `inherit.py`: it already resolves purely by key string, so inheriting from a pattern key (or a pattern key inheriting from something else) works unmodified.

### Why zero matches isn't automatically "missing"

A literal path defaults to "must exist" (`allow_missing = false`). A pattern matching nothing right now is completely normal glob behavior, not evidence of a broken standard - so a pattern key uses the exact same `allow_missing` attribute a literal key already has, with the exact same semantics, rather than inventing a second "pattern matched nothing" concept. `allow_missing = true` on a pattern key means "it's fine if this currently matches nothing"; the default (`false`) still reports zero real matches as a problem.

### Overlap between two catalog keys: validator work, not runner work

Two catalog keys that could both match the same real folder is a structural problem - whose `purpose`/`lifecycle`/rules would actually apply is ambiguous. Unlike "does this pattern match anything on disk right now" (real filesystem state, runner-only, same as `allow_missing`), "could these two catalog KEY STRINGS ever describe the same location" is a property of the two strings alone, computable with zero filesystem access - so it's checked by the validator (`Validator._check_pattern_overlaps` / `path_patterns.patterns_may_overlap`), not deferred to the runner.

The check is deliberately conservative (segment-by-segment comparison; `[abc]` vs `[xyz]` at the same position are treated as "may overlap" even though they could never actually share a character; `**`'s variable-length matching is approximated via each side's fixed prefix before its first `**`, not proven exactly). A false positive here costs a human a rename; a false negative would be a silently-broken standard where two entries fight over the same real folder and nothing ever says so.

Two overlapping *patterns* are always an error - there's no inherent precedence between two wildcards. A pattern overlapping a *literal* is also an error, **unless** that literal explicitly declares `inherit.attributes` or `inherit.rules` pointing at that exact pattern key - the deliberate, on-the-record way to override one instance of a pattern's shared attributes/rules for one specific real folder. This mirrors `overrides_bundled` elsewhere in this project: a collision is rejected by default, and only an explicit reference opts out of that, rather than silent precedence rules a reader would have to infer.

When the runner actually expands a pattern against real disk, any real match that's *also* its own explicit literal catalog entry is excluded from that pattern's own expansion - since the validator already guarantees any such overlap was sanctioned, the literal entry's own resolved attributes/rules (already including whatever it inherited from the pattern) are authoritative for that one folder, not a second, separate invocation via the pattern. A pattern whose real matches are *all* claimed this way still isn't "missing" - the folders exist, they're just individually cataloged elsewhere.

## Deferred Decisions

### OS-level sandboxing

The audit-hook harness above is a soft guard, and can't be made into anything more from inside the interpreter. Real isolation (bubblewrap, Landlock, Seatbelt) is a separate project-level decision, deferred - it changes how rules are distributed and trusted, not just how they're invoked.

### Recursive rule invocation on folders

`[[folders.rules]]` attachments pass root to the rule once, and the rule's own params control recursion and exclusion. No attempt is made to enumerate child directories or handle recursion in the runner itself - that's the rule's job.

## Packaging and CLI Commands

Entry points are now wired up in `pyproject.toml`:

```toml
[project.scripts]
fs-org-validate = "fs_org_kit.validator:main"
fs-org-run = "fs_org_kit.runner:main"
```

This means you can call the tools as short commands:

```bash
fs-org-validate my-standard.toml
fs-org-run my-standard.toml --fix
```

After `pip install -e .`, these commands are available directly in your PATH. If you installed from PyPI (`pip install fs-org-kit`), they'd be installed the same way.
