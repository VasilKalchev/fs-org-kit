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

### Discovery is centralized, and shared rather than repeated

`fs_org_kit/discovery.py` is the single source of truth for "what rules exist right now." It's imported directly by the validator, to resolve rule references in a standard; the runner and doc generator then reuse `validator.rule_catalog` rather than calling `discover_rules()` again themselves - one discovery pass per invocation, not two or three.

This is more than an optimization: two passes could disagree - a rule installed or removed between them, or `Validator.__init__`'s `include_external`/`bundled_rules_dir` args passed differently - and the runner would then act on a rule validation never saw, or vice versa. Reusing the same catalog object makes that class of bug structurally impossible rather than something to keep in sync by convention.

### Fixability is structural, not declared

Originally, rule manifests had a `fix` field saying whether a rule could be fixed. That was dropped in favor of inferring fixability from what's actually on disk: a rule is fixable iff its `-fix.py` file exists, discovered by the runner at invocation time rather than read from the manifest. One less field to fall out of sync with reality, and no possibility of a manifest claiming a fixer that isn't there.

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
instead of a literal - substituted with whatever is at that path
elsewhere in the standard. The runner still has zero rule-specific
knowledge: it expands `{ref: ...}` the same way regardless of which
rule or param it's attached to, exactly like it already doesn't care
what `exclude` or `recursive` mean semantically. This is wire-format
sugar applied uniformly to values, not an exception to "the runner
doesn't interpret params" - the rule script still only ever receives a
plain resolved JSON value, same as always.

**A ref substitutes; it does not project.** The first version resolved
a table to its *keys*, since that's the shape both rules wanted, and
kept a `_META_KEYS_BY_PATH` map so `[folders.reserved]`'s `prefix`
wouldn't be handed over as if it were a reserved-folder name. Both were
mistakes of the same kind: deciding which parts of a table are entries
and which are schema-level config is knowledge *about that table*, and
projecting a table down to a list is interpretation - the exact thing
the paragraph above says the core doesn't do. A tag namespace made it
visible, since its value is the whole object (vocabulary, cardinality,
meanings), not a list of names.

So a ref now yields the value verbatim - table, list, string, number,
boolean - and the two rules take what they want from it: one reads the
keys of `[abbreviations]`, the other keeps the table-valued keys of
`[folders.reserved]`, which drops `prefix` without either the core or
the rule naming it. The alternative considered was an opt-in projection
(`{ref = "...", as = "value"}`), rejected because it leaves the core
with a mode to choose between and a rule's expectations still encoded
at the attachment site. Deleting a branch beat adding one.

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

- **The standard's template uses kebab-case with a `.template.` suffix** - `fs-org-std.template.toml` - so it visibly matches the real file name and sorts beside it
- **A template rule is a real rule directory, prefixed `_`** - `rules/_template-single-v1/` - see [The rule manifest schema lives in code](#the-rule-manifest-schema-lives-in-code)
- **Python modules use underscores** - `fs_org_kit`, `validator.py`, `discovery.py` - because they need to be importable
- **Rule directories and manifests use the rule ID** - `file-extensions-v1/file-extensions-v1.toml`, `file-extensions-v1-check.py`, `file-extensions-v1-fix.py` - self-identifying outside their directory context

### Project name

**fs-org-kit** is deliberately literal over evocative. Someone encountering the name has no chance of guessing wrong about what it does.

## Schema and Data Modeling

### Schema versioning is separate from standard versioning

`fs-org-std.template.toml` tracks `schema_version` (the grammar it uses, e.g., 1.0) separately from `standard_version` (the content version, e.g., 3.2), so the grammar can evolve independently of any one person's standard: different standards can sit at different schema versions, and a validator that doesn't recognize one gives a clear error rather than a flood of misleading ones.

### Attributes are self-describing

The validator reads its field lists and defaults from the file being checked:

- `<ns>.attributes.names` / `.required` declare the free-form attributes an entry may carry, and which of them may not be left empty
- `<ns>.attributes.group.names` / `.multi` / `.required` declare the enum-backed grouping fields
- `enums.group.<field>` (and optionally `enums.attributes.<field>`) defines the valid values for one field

This means the validator doesn't need code edits when the schema evolves - it adapts automatically.

### An entry is its fields, a `group` table, and a `rules` table

`purpose` and `allow_missing` used to sit side by side in a flat entry and read as the same kind of thing, though only one of them did anything. That's resolved from both ends now: the fields the tool acted on are gone (below), and what remains is split by who reads it.

| Where | Holds | Declared by |
|---|---|---|
| the entry itself | free-form prose: a string, or a list of strings | `<ns>.attributes.names` / `.required` |
| `<entry>.group` | enum-backed values, checked against `enums.group.<field>` | `<ns>.attributes.group.names` / `.multi` / `.required` |
| `<entry>.rules` | rule attachments | nothing - they're references to rules on disk |

Grouping is separate from documentation because a closed vocabulary is what makes bucketing entries possible at all: the doc generator emits a "by `<field>`" index per grouping field, which free-form prose could never support.

Nothing in the code knows what `purpose` or `lifecycle` mean - including the ones this project's own template ships with. A standard that wants `sensitivity` and `owner` instead gets the same validation and the same rendering; `group`, `rules` and `inherit` are the only names an entry can't use for a field. Requiredness moved into the standard along with the names: a validator that no longer knows `purpose` exists can't insist on it either.

Field lists are per namespace, so `folders` can carry a different set from `paths`. Vocabularies are not: `enums.group.lifecycle` is one table both namespaces read, because a value set describes the field, not who carries it.

### Tags declare a vocabulary, never a value

`[tags."<ns>"]` and `enums.group.<field>` are both closed value sets, and the difference between them is who carries the value. A grouping field's value is written in the standard and describes the cataloged entry. A tag's value is carried by each item *under* one - every archived project has its own state; `prj/_arch/` doesn't have one at all. So a tag namespace can't be another field: the standard would have to record what's on disk, and it would be wrong the moment anything moved.

The standard therefore declares which vocabulary exists and where it applies, and nothing more. What each item currently carries is a question for the filesystem, answered by a rule at run time - the same division as [a cataloged path that isn't on disk](#a-cataloged-path-that-isnt-on-disk-is-skipped-not-reported).

**Tags have no attachment syntax of their own.** A namespace is declared once and reaches a checking rule as one param, via `{ref = "tags.state"}`; which rule runs where stays an ordinary rule attachment, with its `reason`. The alternative - `[<entry>.tags.<ns>]` attachments, a fourth `inherit` part, a `uses_tags` manifest flag feeding the rule a `--tags` payload the way `uses_cache` feeds `--cache-dir` - buys one thing the ref approach can't: a doc generator that renders which tags apply to which path. It was rejected as the wrong fix for that, because the general version is better - *every* applied rule is documentation, so the doc generator should render rule attachments' params (see Deferred Decisions), which covers tags along with everything else.

How a tag is stored is never the standard's business either. xattr, a sidecar file, TMSU, a name suffix - each is a different rule, and the `state/complete` spelling is one rule's separator param, not a declaration here.

### Nothing keyed on a field's name, including in the doc generator

The corollary of the above, and the one place it was violated: the generated docs used to draw a Mermaid diagram of the `lifecycle` vocabulary, recognized by its name and its four expected values. That's app behavior keyed on a name the user chose, so it's gone - the enums section renders every vocabulary the same way, under its dotted key. A standard naming the same concept `stage` was already getting nothing from it.

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

### The rule manifest schema lives in code

`rule.template.toml` used to be two things at once: the manifest grammar, and the file discovery read `enums.severity`/`enums.scope` out of at every invocation. The intent was transparency - the valid values visible in a file rather than buried in application logic. What it produced was a configuration surface with nothing behind it: a fifth `severity` added to that file would be accepted by every rule and implemented by none. Its `[attributes]` table compounded the confusion by mimicking `paths.attributes` in a standard - where the names genuinely are the user's to choose - to declare a field set that is not negotiable, and that nothing enforced anyway.

The schema now lives in `fs_org_kit/discovery.py` (`SEVERITY`, `SCOPE`, `MANIFEST_KEYS`), beside the code that acts on it, and the field list became enforced rather than decorative: an unknown manifest field is a warning, not a silently ignored typo.

What that file was genuinely good at - handing an author a correct starting point - moved to `rules/_template-single-v1/`, `_template-cross-v1/` and `_template-both-v1/`: real rule directories, one per scope, each with a manifest, a checker, a fixer and tests that run in this repo's suite, so a template that drifts from the protocol fails here rather than in whatever someone copied it into. Discovery skips any rule directory whose name begins with `_`, in every tier, silently - that prefix is the entire disabling mechanism, and it doubles as somewhere a user can park a half-written rule.

### Rule-to-runner protocol is versioned independently

Rule manifests include `protocol_version`, separate from the rule's own `version`, so the runner's command-line interface can evolve without forcing every existing rule to be rewritten in step - an old-protocol rule and a new-protocol one coexist, and a rule declaring an unsupported version gets a clear error instead of a mysterious argparse failure.

### Fixer-specific protocol: self-contained, not check-then-fix

When a fixer is invoked, it doesn't check first and then fix - the `-fix.py` script is responsible for detecting the problem AND fixing it in one pass. It returns one of four statuses:

- `ok` - nothing needed fixing
- `violation` - found problems, couldn't fix them (e.g., permission denied)
- `fixed` - found problems and fixed them
- `unfixable` - found problems that are logically unfixable by the rule

This avoids a redundant check-then-fix-then-recheck cycle, keeps the runner's logic to "invoke once, read status," and makes the fixer own the full problem end to end rather than sharing it with the runner.

### `skipped` - the runner's own status, for a plan a fixer outran

Targets are expanded once, up front, from a single snapshot (one discovery/resolution pass, the pattern used everywhere here). So a fixer can move or delete a folder that a later invocation in the same pass was already planned against - `staleness-v1` archiving a project the per-project checks were queued for is the ordinary case, not an edge one.

Handing the vanished path to the script anyway makes it exit nonzero, which the protocol reads as *the script itself is broken*. That is the one signal meaning "this rule is misconfigured, go look at it", and spending it on a fixer doing its job trains people to ignore it - and holds the run at exit 1.

So the runner checks a target still exists immediately before invoking, and reports `skipped` instead. It is deliberately **not** a fifth script status: no rule can return it, and the checker/fixer contract is unchanged. It doesn't affect the exit code.

Absence alone isn't enough to justify skipping, though - "a fixer moved this" and "this was never here" look identical at that moment, and the second is a misconfigured attachment that must still be reported. So `collect_invocations` stamps each invocation with the targets that really existed when the plan was built, and only those can go on to be skipped. This matters for `paths.cross`, which resolves its references directly rather than through the exists-on-disk filter every path-derived target passes: it's the one attachment shape that can name somewhere that never existed.

The alternative was re-expanding glob keys after each `fixed` result. That fixes more - the moved folder would also get checked at its new location in the same pass - but makes the invocation list mutate mid-run, and raises ordering questions (does a re-expansion that produces new targets re-run rules already run?) that a plain existence check doesn't. The moved folder is simply checked on the next run.

### Scripts run inside an audit-hook harness

Rule scripts run under `sys.addaudithook` (`fs_org_kit/sandbox.py`), which blocks network access, starting other processes, native/ctypes calls, and writes outside what the invocation is entitled to touch. `--no-sandbox` turns it off.

It is a guard against bugs and accidents, **not** a security boundary, and describing it as one would be wrong: the hook lives inside the interpreter it polices, so `ctypes` reaches straight past it, and nothing here constrains a rule that was malicious rather than careless. What it does catch is the class of mistake an author makes without meaning to - a checker that writes, a fixer that reaches outside the tree it was pointed at, a rule that quietly phones home - none of which was detectable before, because the convention was documented and entirely unenforced.

Two decisions shaped it:

**The policy is built in the parent, never derived in the child.** Anything the child worked out after installing the hook would have to be exempted from the hook, which is a hole. So the runner computes the writable set from the manifest's declarations plus the invocation's own targets, and passes it in.

**Capabilities are declared in the manifest, not special-cased in the runner.** `basename-sync-v1`'s fixer shells out to a user-provided script, so it declares `[sandbox] subprocess = true`; a fixer whose destination is a user-configured path the core can't know in advance declares `unrestricted_writes`. This is the same shape as `uses_cache`: the rule states a need, the core grants it uniformly, and the runner keeps no per-rule knowledge. It also puts the grant somewhere a reviewer reads before trusting a rule.

The writable set is `{cache, temp}` for a checker, and additionally `{root} ∪ {targets}` for a fixer. Targets are listed separately from root because a catalog key may name a location outside it.

A violation raises an exception deriving from `BaseException` rather than `Exception`, since rule scripts routinely wrap their work in `except Exception` and a swallowed violation would be reported as an ordinary failure or as success. Violations are also recorded, so even `except BaseException` can't turn one into a clean result.

## Validation vs. Execution

### Validator is read-only

The validator **never** modifies anything on disk. It reads a `.toml` file, parses it, validates it against the schema, and reports issues. That's all.

### Runner validates first, always

The runner's first step is to reuse the validator. If validation fails, the runner exits with code 2 and never touches the filesystem - a rule only ever runs against a standard already confirmed structurally sound, and a validation error reads the same whether it came from `fs-org-validate` or `fs-org-run`.

### Exit codes are meaningful

- **0** - Everything ran and produced no violations (or there was nothing to run); `skipped` invocations don't change this
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

### A cataloged path that isn't on disk is skipped, not reported

The runner invokes rules against the paths that exist right now, and passes over the ones that don't. There was an `allow_missing` flag for this, defaulting to "must exist", so an absent path failed the run unless marked - which made state-via-location schemes (a project moving between `active/x/` and `archive/x/`) depend on remembering to mark *both* sides, since either could be the absent one at any moment.

The catalog describes where things go, not which locations exist at this instant. "This path should exist" is a real thing to want checked, but it's a question about the filesystem, which is what rules are for - so it belongs in a rule, attached where it applies, not in a flag on every entry. Until such a rule exists, absence is simply not reported.

### Why this is a separate module (`fs_org_kit/inherit.py`), not inline in the validator

Same reasoning as `discovery.py` for rules: resolution is needed by both the validator (to validate the *resolved* view, not the raw one - so a path that inherits `purpose` doesn't get flagged "missing purpose" just because it didn't type it itself) and the runner (to know which rules actually apply to which real, currently-existing path). One module, one place to get the precedence rules right, imported by both.

### Architecture: resolve once, flatten, then everything downstream is unaware inheritance exists

`resolve_entries()` runs as a pure data-transformation step before validation. It produces a `ResolvedEntry` per catalog key with final, flattened attributes and rules - the validator's field checks and the runner's invocation-building both just read `resolved.attributes`/`resolved.rules` and never need their own inheritance-walking logic. This mirrors the same "resolve once, flatten, reuse" pattern already used for rule discovery and the validator/runner relationship generally.

## Out-of-Root Path Keys

### The problem it solves

`root` is the tree the standard governs, and a catalog key is relative to it. But a personal filesystem doesn't stop at one tree: `~/.config/`, `/etc/`, an external drive's mount point are all worth cataloging and attaching rules to, and none of them sit under a `root` of, say, `~/usr/`.

### Why there's no flag for it

There was one - `outside_root = true`, required on any key that escaped root - and it existed because the escape was silent and easy to write by accident: `Path("/home/me/usr") / "/etc/nginx"` is `/etc/nginx`, since Python's path join **discards** the left side when the right is absolute.

That's a sharp edge in path handling, and the fix for it is `fs_org_kit/path_keys.resolve_key` being the only place a key becomes a real path - not a field every escaping entry has to carry. The flag asked the standard to restate what the key already says, and made a second thing to get wrong (it was un-inheritable, un-defaultable, and separately mirrored on `[[paths.cross]]`). A key names a location; the tool goes there.

### What it feeds

`resolve_key` handles relative, absolute, `~`-relative and `..`-walking keys identically for every consumer, so no caller re-derives it and no bare join appears anywhere else. The sandbox confines a fixer's writes to root plus its own targets, and a target outside root is simply one of those targets.

Overlap detection compares keys in a normalized form, so `/srv/*/` and `srv/*/` are correctly *not* a collision while `~/x/` and `/home/me/x/` still are.

## Path Pattern Keys

### The problem it solves

A `[paths."..."]` entry is normally one exact location. A personal filesystem often has many structurally-identical folders under one prefix - one per client, one per numbered project - that all deserve the same `purpose`/`lifecycle`/rule attachments without hand-maintaining an otherwise-identical catalog entry per folder, kept in sync by hand as folders come and go. This sat in a real gap in the existing location vocabulary: exact path (`[paths."x/"]`), reserved *name* pattern anywhere (`[folders.reserved."_name"]`), or every folder anywhere (`[[folders.rules]]`) - nothing for "these N folders under this prefix are the same kind of thing."

### The mechanism

A `[paths."..."]` key may be a glob pattern (`fs_org_kit/path_patterns.py`) instead of a literal path - the same vocabulary already used everywhere for `exclude` params (`fnmatch`/`pathlib.Path.glob`: `*`, `**`, `?`, `[abc]`). No wrapper syntax needed to tell a pattern key from a literal one - a literal path can't legitimately contain a glob metacharacter anyway (see `naming-pattern-v1`'s portable-charset doc comment), so a key is a pattern iff it contains one.

Brace-expansion (`folder{1..3}/`) was considered and rejected - it has no stdlib support (a bash-ism, not part of POSIX `glob()` or Python's `glob`/`fnmatch`), and `folder[1-3]/` already covers the common numeric-range case with zero extra code or dependencies.

One pattern entry's attributes and rule attachments apply identically to every real folder it matches - invoked once per match, the same shape a `[folders.reserved."_name"]` entry uses. (`[[folders.rules]]` is the other shape: one invocation, on root, with the rule's own `recursive`/`exclude` params doing the walking.) This required zero changes to `inherit.py`: it already resolves purely by key string, so inheriting from a pattern key (or a pattern key inheriting from something else) works unmodified.

### Why zero matches isn't automatically "missing"

A pattern matching nothing right now is completely normal glob behavior, not evidence of a broken standard - and it needs no separate concept, because a literal path that isn't on disk is skipped the same way. Zero matches contributes zero invocations, and nothing is reported.

### Overlap between two catalog keys: validator work, not runner work

Two catalog keys that could both match the same real folder is a structural problem - whose `purpose`/`lifecycle`/rules would actually apply is ambiguous. Unlike "does this pattern match anything on disk right now" (real filesystem state, runner-only), "could these two catalog KEY STRINGS ever describe the same location" is a property of the two strings alone, computable with zero filesystem access - so it's checked by the validator (`Validator._check_pattern_overlaps` / `path_patterns.patterns_may_overlap`), not deferred to the runner.

The check is deliberately conservative (segment-by-segment comparison; `[abc]` vs `[xyz]` at the same position are treated as "may overlap" even though they could never actually share a character; `**`'s variable-length matching is approximated via each side's fixed prefix before its first `**`, not proven exactly). A false positive here costs a human a rename; a false negative would be a silently-broken standard where two entries fight over the same real folder and nothing ever says so.

Two overlapping *patterns* are always an error - there's no inherent precedence between two wildcards. A pattern overlapping a *literal* is also an error, **unless** that literal explicitly declares `inherit.attributes`, `inherit.group` or `inherit.rules` pointing at that exact pattern key - the deliberate, on-the-record way to override one instance of a pattern's shared fields/rules for one specific real folder. This mirrors `overrides_bundled` elsewhere in this project: a collision is rejected by default, and only an explicit reference opts out of that, rather than silent precedence rules a reader would have to infer.

When the runner actually expands a pattern against real disk, any real match that's *also* its own explicit literal catalog entry is excluded from that pattern's own expansion - since the validator already guarantees any such overlap was sanctioned, the literal entry's own resolved attributes/rules (already including whatever it inherited from the pattern) are authoritative for that one folder, not a second, separate invocation via the pattern. A pattern whose real matches are *all* claimed this way still isn't "missing" - the folders exist, they're just individually cataloged elsewhere.

## Reserved-Name Rule Attachments

### Why the targets come from a disk walk

A `[folders.reserved."_x"]` entry describes what a *name* means wherever it occurs. That is the one location vocabulary with no key to resolve: a path key names a place, a pattern key names a set of places, but a reserved name names none - so its targets can only come from looking. One `os.walk` per run collects every folder whose own name matches, symlinks not followed (a link back up the tree would walk forever) and a match inside another match not pruned (a `_x` nested in a `_x` is still that name occurring in the tree).

The entries arrive via `validator.resolved_folders` rather than a second resolution pass, so `inherit` between reserved entries carries rule attachments with it exactly as it does for paths - the same resolve-once-and-reuse path `resolved_paths` takes.

### Why a folder can collect rules from two places at once

`prj/_arch/` can be both its own `[paths."..."]` entry and an occurrence of the reserved name `_arch`. Both sets of rules run against it. They answer different questions - "what `_arch` means anywhere" and "what this one location is" - and suppressing one would mean picking which question the standard is allowed to ask. This is the same coexistence a per-path attachment already has with `[[folders.rules]]`, and the opposite of the pattern-vs-literal rule, where the ambiguity is over a single set of attributes rather than two independent statements.

### Why a name matching nothing is not a problem

Nothing ever said a reserved name had to occur anywhere. A name matching zero folders contributes zero invocations and is reported nowhere - the same treatment a cataloged path that isn't on disk gets, for the same reason.

## Deferred Decisions

### OS-level sandboxing

The audit-hook harness above is a soft guard, and can't be made into anything more from inside the interpreter. Real isolation (bubblewrap, Landlock, Seatbelt) is a separate project-level decision, deferred - it changes how rules are distributed and trusted, not just how they're invoked.

### Recursive rule invocation on folders

`[[folders.rules]]` attachments pass root to the rule once, and the rule's own params control recursion and exclusion. No attempt is made to enumerate child directories or handle recursion in the runner itself - that's the rule's job.

### Rendering rule attachments in the generated docs

Every applied rule is documentation: its `reason` says why it's there, and its params say what it will accept. The doc generator currently renders neither, so anything expressed as a rule param - which tags apply under a path, which extensions are allowed, how stale is too stale - is invisible in the generated Markdown even though it's the enforceable half of the standard. Rendering attachments generally is deferred, and is the reason [tags](#tags-declare-a-vocabulary-never-a-value) got no attachment syntax of their own: a tags-shaped fix would have solved one case of it.

## Packaging and CLI Commands

`pyproject.toml`'s `[project.scripts]` wires each tool's `main()` to a short command (`fs-org-validate`, `fs-org-run`, ...), available in `PATH` after `pip install -e .` the same way a PyPI install would provide them.
