# Changelog

Newest first. This records *what* changed; the reasoning behind design
decisions lives in [DESIGN.md](DESIGN.md).

Four commands: `fs-org-validate`, `fs-org-run`, `fs-org-doc`,
`fs-org-cache`. The current rule count lives in
[README.md](../README.md), not here, so there's one place to update it.

---

## Unreleased

### Doc generator: ToC links, footer, path nesting, and a strip-down to a minimal baseline

Generated docs' ToC links now resolve in Obsidian, the renderer these
docs are actually read in - an explicit `<a id="...">` before each
heading, linked to by a prefixed slug scheme, turned out not to be
honored there. `slug_for()` now computes the anchor Obsidian itself
derives from a heading's visible text: lowercased, backticks (code-span
syntax) stripped, whitespace percent-encoded as `%20` rather than
hyphenated. Heading-anchor generation isn't part of CommonMark, so this
is inherently renderer-specific - GitHub and most static-site
generators hyphenate spaces instead, and there's no anchor string that
satisfies both. Obsidian is the default target for now; a configurable
target is planned. The `> Generated from ...` line moved from a
blockquote right under the title to an italic footer at the end of the
document, so it doesn't compete with the actual content for attention.
The Paths section of the ToC now nests entries by directory depth
instead of listing every cataloged path flat, and shows only the final
path segment per line - the indentation already conveys the ancestry.

Beyond that, the doc generator was stripped down to a minimal,
unconfigurable baseline in preparation for making it configurable:
gone are Mermaid diagrams (`tree`/`rules`/`cross`, the 40-node guard,
`--diagrams`/`--no-diagrams`), `--sections`/`--exclude-sections`
filtering (every present section always renders now), the grouping
index (`**By `<field>`:**` bucket lists), per-field inherited/default
markers in attribute tables, and the Rules section's rule-catalog
detail table (purpose/tier/version/severity/scope/fixable/params) -
it now just lists each rule's attachment sites and their reasons. An
inherited field still renders at its resolved value; it's just no
longer annotated as inherited. `--no-toc` is also gone - the ToC is
unconditional now, alongside everything else.

### The `alphabetical-order` lint is gone

The validator no longer requires `[paths]`, `[folders.reserved]`,
`[abbreviations]`, or `[tags]` entries to be declared in alphabetical
order. `_check_abbreviations` had nothing left to do once its only
check was removed, so it's gone too.

### `transfer-v1` — cross-scope move/copy/sync

Twentieth bundled rule. Moves, copies, or syncs non-excluded entries
from one declared cross-path to another - `operation` (move/copy/sync)
and `direction` (which declared path is the source), both required with
no default. A dated destination (`~/inbox/%Y-%m-%d-dump/`) is expressed
in the target's own path string, expanded with strftime at run time,
rather than as a separate param.

This picks back up the question `collect-v1` (see below) was shelved
over - whether a fixer's destination has to be an opaque param - and
answers it: no, not when the destination is a second declared
cross-path instead of a free-standing string. That's also why this rule
still needs `[sandbox] unrestricted_writes`: the runner grants a fixer
write access to a target exactly as declared, before this rule expands
`%Y-%m-%d`/`{name}` in it, so the expanded destination's text doesn't
match what was granted whenever either placeholder is used.

### `link-integrity-v1` drops `.webloc`/Finder alias support — **behavior change**

Scope narrowed to filesystem links: `symlink`, `desktop`, `shortcut`.
`.webloc` and macOS Finder aliases are gone rather than left unverified,
since neither names a local file this rule can actually check.
`foreign_links` ("skip"/"report") is now `report_foreign` (bool, default
`false`) - same behavior, plainer shape for a switch with only two
states. Version 1.1.

### `folder-icon-inherit-v1` and `folder-icon-auto-v1` renamed to `xdg-inherit-folder-icon-color-v1` and `xdg-auto-folder-icon-v1`

Both manifests overstated platform support (KDE/Dolphin specifics,
claims about how GNOME/macOS/Windows store folder icons); corrected to
state only what's verified: `.directory` is a freedesktop.org standard,
unsupported on Windows and macOS. No behavior change.

### A param `{ref}` now substitutes the whole value — **behavior change**

**If you wrote a rule that takes a `{ref = "..."}` pointing at a table,
it now receives that table instead of a list of its keys.** Previously
the core projected a table down to its keys and stripped out keys it
knew were schema-level config (`[folders.reserved]`'s `prefix`). That
was the core interpreting a param value on a rule's behalf, and it
carried knowledge about tables it doesn't own. Both are gone:
`param_refs` substitutes whatever is at the path, verbatim - table,
list, string, number or boolean - and its only remaining failure is a
path that doesn't resolve.

Standards need no edits: the syntax is unchanged, and the two bundled
rules that consumed the projection were updated in lockstep. Both still
accept a literal list, so a hand-narrowed list keeps working.

- `spelling-abbreviations-v1` 1.1 - reads the abbreviations off the
  table's keys and ignores the meanings beside them.
- `uncataloged-reserved-v1` 1.1 - takes the table-valued keys as entry
  names, which skips `prefix` without knowing that name.
- `META_KEYS_UNDER_PATHS` / `_RESERVED` moved from `param_refs` to
  `validator`, its only remaining consumer; `META_KEYS_UNDER_FOLDERS`
  was dead and is deleted.

### `[tags]` declares vocabularies for metadata carried on disk

Schema 2.1. The table was previously a flat `tag = "meaning"` glossary
that nothing but the doc generator read. It now holds one table per
namespace:

```toml
[tags.state]
description = "Where a unit of work stands once it leaves the active tree."
multi = false

[tags.state.values]
abandoned = "stopped deliberately, will not resume"
complete  = "finished, nothing further planned"
```

A namespace reaches a checking rule as **one param**, via
`{ref = "tags.state"}` - there is no tag-attachment syntax, and which
rule applies where stays visible as an ordinary rule attachment. How a
tag is stored (xattr, sidecar, name suffix) and how `state` and
`complete` are spelled together are that rule's business.

The standard declares which vocabulary exists and never which value
something currently has - a tag value lives on disk, which is what keeps
the standard a specification rather than a record of filesystem state.

The validator checks a namespace's shape (`values` a table of
string → string, `multi` a boolean, unknown keys warned, alphabetical
order linted) and reports the old flat form by name. The doc generator
renders one table per namespace instead of one flat list.

`examples/parext` declares `[tags.state]` with the four states
`prj/_arch/` already described in prose; no bundled rule consumes it
yet.

### `rule.template.toml` is gone; templates are real rules under `rules/_*`

That file was a template and a live configuration file at once:
discovery read `enums.severity` and `enums.scope` out of it at every
invocation, so editing it changed what every rule's manifest meant, while
its `[attributes]`/`[attributes.defaults]` tables declared a field set
and a set of defaults that nothing read at all.

- The manifest schema moved into `fs_org_kit/discovery.py` - `SEVERITY`,
  `SCOPE`, and `MANIFEST_KEYS`, the latter now **enforced**: an unknown
  manifest field is a warning instead of a silently ignored typo.
  `discover_rules()` lost its `rule_template_path` parameter.
- Three template rules replace the file: `rules/_template-single-v1/`,
  `_template-cross-v1/`, `_template-both-v1/` - each a complete manifest,
  checker, fixer and test file, one per scope, all passing this repo's
  suite.
- **Discovery skips any rule directory whose name starts with `_`**, in
  every tier, silently and without parsing it. That's what disables the
  templates, and it also gives a user somewhere to park a half-written
  rule.
- `.claude/skills/new-rule/scaffold_rule.py` now copies a template and
  renames it rather than generating a second skeleton of its own; its
  `--severity`, `--params` and `--cache` flags are gone (one-line edits
  in the manifest the copy leaves behind).

Nothing in a standard changes. A rule manifest only changes if it
carried a field the tool never read, which now says so.

### An entry declares its own fields - schema 2.0

`purpose` and `allow_missing` used to sit side by side in a flat entry
and in one `paths.attributes.names` list, reading as the same kind of
thing. Only one of them was: the tool acted on `allow_missing` and
`outside_root`, while the rest were documentation nothing reads - except
that `purpose`, `lifecycle` and `origin` were *also* hardcoded by name in
the validator, so a standard couldn't actually name its own fields.

An entry is now its attributes plus two tables, and each
namespace declares what may go in the first two:

```toml
[paths.attributes]                     # free-form: string or list of strings
names = ["purpose", "notes", "use_for", "not_for", "see_also"]
required = ["purpose"]

[paths.attributes.group]               # enum-backed, checked against enums.group.*
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle", "origin"]

[paths."area/inv/"]
purpose = "Inventory tracking"

[paths."area/inv/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."area/inv/".rules.file-extensions-v1]]
reason = "..."
```

**No field name is hardcoded anywhere in the package.** Requiredness
moved into the standard along with the names, and the doc generator's
Mermaid diagram of the `lifecycle` vocabulary is gone - it recognized a
user-chosen name and its four expected values, which is exactly the
coupling this removes. `group`, `rules` and `inherit` are the only names
an entry can't use for a field of its own. `inherit` names one source
per part (`attributes` / `group` / `rules`, plus `exclude_rules`).

Vocabularies moved from `enums.paths.<field>` to `enums.<kind>.<field>`
and are shared by both namespaces: one `[enums.group.lifecycle]` serves
paths and reserved folders alike, since a value set describes the field
rather than who carries it. `[enums.attributes.<field>]` is optional and
normally absent - an attribute is prose unless a standard chooses to
close its value set.

### `allow_missing` and `outside_root` are gone

Both were flags asking a standard to restate something, and both are
removed rather than relocated - see DESIGN.md's
[cataloged-path-not-on-disk](DESIGN.md#a-cataloged-path-that-isnt-on-disk-is-skipped-not-reported)
and [out-of-root](DESIGN.md#out-of-root-path-keys) sections for why.

A cataloged path that isn't on disk is now simply skipped, silently. No
rule for "this path should exist" ships yet. `path_keys.resolve_key` is
now the only place a key becomes a path, so `path_keys` loses its
escape-detection half entirely, and the runner loses its missing-path
reporting and the exit-1 that went with it.

Together these also retire standard-wide field defaults
(`attributes.defaults`): `allow_missing = false` was the only value
anyone had reason to declare there.

Breaking, so `SUPPORTED_SCHEMA_MAJOR` is 2 and both bundled examples
move to `schema_version = "2.0"`. A 1.x standard stops with one clear
version error instead of a pile of unknown-field warnings. Migrating an
entry: leave its prose fields where they are, move its enum-backed ones
into `[<key>.group]`, and delete `allow_missing` / `outside_root`.

### `skipped` - an invocation a fixer outran

A fixer moving a folder left later invocations pointed at where it used
to be; those exited nonzero and were reported `broken` - the signal for
"this rule is misconfigured" - holding the run at exit 1 for a fixer
doing its job correctly. The runner now checks a target still exists
immediately before invoking and reports `skipped` instead, which doesn't
affect the exit code. See [DESIGN.md](DESIGN.md#skipped---the-runners-own-status-for-a-plan-a-fixer-outran)
for why it isn't a fifth script status and how a genuinely-missing target
still reports `broken`.

Surfaced by `examples/para`, where `staleness-v1` archives a project that
`projects/*/` was queued against.

### `collect-v1` moved out of the bundled tier

The sweep rule is off main and parked on the `collect-rule` branch,
which holds it exactly as it stood. Nothing in the core changed: it was
a rule directory, and removing one is removing a directory.

The open question it was shelved over is whether a fixer's destination
has to be an opaque param. `unrestricted_writes` stays a documented
capability either way - the destination-from-config shape isn't unique
to this rule.

### Rules attached to a reserved folder name actually run

`[folders.reserved."_x".rules.<name>]` validated and documented, but
`runner.py` had no branch for it - `collect_invocations` covered
per-path, `paths.rules`, `paths.cross`, and `folders.rules`, so those
attachments silently did nothing. They now target every folder *named*
`_x` anywhere under root, found in one `os.walk` that doesn't follow
symlinks and doesn't prune a match nested inside another. This closes
the gap between the four location vocabularies
[DESIGN.md](DESIGN.md#path-pattern-keys) already claimed existed and the
three the runner implemented.

Reserved entries reach the runner through `validator.resolved_folders`,
the same resolve-once-and-reuse path `resolved_paths` already takes, so
`inherit` between reserved entries carries their rules with it. A folder
that is both a reserved name and its own `[paths."..."]` entry gets both
sets of rules - two questions, two answers, the way a per-path
attachment and `[[folders.rules]]` already coexist on one folder.

### `staleness-v1` 1.1 - dated destinations

`destination` now expands strftime placeholders against the time of the
run, so `"_arch/%Y"` files each archived item under the year it was
archived. Without it, a fixer pointed at an archive that is "separated
by year" spends every run undermining that arrangement. A destination
with no placeholder renders to itself, so every existing attachment
resolves exactly where it did.

New `create_destination` (default `false`) keeps the never-creates
stance - a typo'd destination still reports `unfixable` rather than
building a tree beside the real one - while letting a dated destination
opt in, since the folder for a given year cannot exist before that year
is first archived into. The default differs from the sweep rule's
equivalent for that reason: a dated dump folder is that rule's whole
purpose, whereas an archive is somewhere that should already exist.

`~`-relative destinations are now expanded, which is what the manifest
already claimed for pointing the fixer at an OS trash folder.

### `see_also` renders as Markdown

A list-valued `see_also` reached the generated attribute table as its
Python repr (`['prj/', 'task/']`); it's now joined like every other list
field, with a bare string still passing through.

### `examples/`

`examples/para/` - a toy PARA tree, a standard governing it, and a
tutorial. Three violations are seeded into the tree so the first run
reports something, and the standard stays small enough to read in one
sitting: glob path keys, `inherit`, and one fixer, not a tour of the
grammar.

Each example's `root` is relative, which makes it cwd-dependent - the
tutorial says to run from the example's own directory. An absolute root
can't be committed, and resolving a relative root against the standard's
own location is a change to `runner.py`, not to an example.
`tests/test_docs_current.py` now scans `examples/` for dangling doc
links.

### Every bundled rule has tests

The six that predated the coverage check - `mime-type-v1`,
`naming-pattern-v1`, `spelling-abbreviations-v1`, `staleness-v1`,
`timestamp-consistency-v1`, `uncataloged-reserved-v1` - are covered, and
the exemption list in `tests/test_docs_current.py` is gone rather than
empty, so a new rule without tests fails outright.

`spelling-abbreviations-v1` is the one rule with a third-party
dependency, so its suite shadows `pyspellchecker` with an importable stub
to verify the missing-dependency message on a machine that has the
package, and skips the rest when it's genuinely absent.

### `mime-type-v1` 1.1 - `exclude` is now read

The manifest declared it and the checker never looked at it, so an
attachment that set `exclude` passed validation and was silently ignored.
Found while writing that rule's tests.

---

## 0.3

### Eight rules

`empty-v1` (zero-byte files, and two readings of "empty folder" -
literally entry-less, or a hollow tree of folders holding no file
anywhere). `link-integrity-v1` (broken symlinks, `.desktop`
`Type=Link`/`Type=Application`, `.url`, `.webloc`, and `.lnk` parsed
from its LinkInfo structure; a remote URL is counted but never judged -
the rule could declare the sandbox's `network` capability and fetch it,
and deliberately doesn't, since reachability is a fact about someone
else's server rather than about your filesystem - and a macOS Finder
alias is counted as unverifiable rather than guessed at).
`link-policy-v1` (files/folders/links each required, allowed or
forbidden - classification is link-first, or "no real files, links are
fine" would be unsayable). `collect-v1` (sweeps a path into a
strftime-templated target; the only bundled rule whose fixer moves user
data, and it never overwrites under any conflict setting).
`required-content-v1` (required/suggested/forbidden globs - three flat
lists rather than tables with a severity each, since severity is a
property of the rule, not the attachment). `changed-since-v1` (cached
snapshot diff, optionally drawn as a tree with unchanged branches
collapsed). `xdg-inherit-folder-icon-color-v1` and `xdg-auto-folder-icon-v1` (freedesktop
`.directory` icons: one propagates a parent's color while keeping each
child's variant, the other assigns variants from name or content
conditions while preserving color, so the two compose in either order).

Folders in `changed-since-v1` are tracked by presence, never by their
own timestamps: a folder's mtime moves whenever anything inside it
appears, which would report one edit twice when recursive and leak deep
edits when not - exactly what `recursive = false` says not to look at.

### `fs_org_kit/sandbox.py` - rule scripts run policed

`sys.addaudithook` blocking network, subprocess, native calls, and
writes outside what an invocation may touch: cache and temp for a
checker, plus root and its own targets for a fixer. So "checkers never
write" is enforced rather than merely documented - see
[DESIGN.md](DESIGN.md#scripts-run-inside-an-audit-hook-harness) for the
capability-declaration shape and why it's a guard against accidents, not
a security boundary.

`basename-sync-v1` declares `subprocess` (its fixer delegates to a user
script); `collect-v1` declares `unrestricted_writes` (its destination
comes from the standard). Building it surfaced that `runpy.run_path`
doesn't put the script's directory on `sys.path` the way direct
execution does, which broke `staleness-v1`'s import of its `_shared`
module.

### `fs_org_kit/path_keys.py` - out-of-root path keys

A catalog key may resolve outside `root` - `/etc/nginx/`, `~/.config/`,
`../sibling/` - on an entry declaring `outside_root = true`. See
[DESIGN.md](DESIGN.md#out-of-root-path-keys) for why the flag exists and
why it's never inherited or defaulted. `resolve_key` is now the single
place a key becomes a real path; the previous `path-leading-slash` lint
is gone, replaced by a validation error.

---

## 0.2

Everything below 0.1 still holds; this adds param references, glob path
keys, rule-owned caching, two rules, and self-checking docs.

### `file-size-v1`

Per-file `max_size` / `min_size` thresholds — the twelfth bundled rule,
and the first written with the `new-rule` skill.

Deliberately not a param on `folder-structure-v1`, whose `max_size` is
the total for a whole tree: one 5 GiB file and 5,000 × 1 MiB files are
identical to that rule, and a per-file threshold would have been its only
one not describing a folder's shape. Separate rules also attach
independently, with separate reasons.

The cost is duplicated size parsing — a rule is a standalone script and
can't import from a sibling, so both carry their own
`parse_size`/`format_size`. The unit vocabulary is deliberately identical,
so `"500MiB"` means the same thing in both.

Symlinks are skipped (their size is the stored path, and following one
measures a file outside the tree). A threshold-less attachment is
rejected rather than reported `ok`, since it can only ever pass. No
fixer: delete, move, recompress, or accept are all plausible and disagree.

### Docs made self-checking; `new-rule` skill

`doc/ROADMAP.md` became `doc/CHANGELOG.md` — it had stopped describing
future work and turned into a record of what shipped, at roughly twice
the length it needed.

`tests/test_docs_current.py` now asserts the facts the docs state about
the repository: every test count in `doc/TESTING.md`, `README.md`'s rule
count, whether every module and every bundled rule has tests, and whether
every `doc/*.md` reference — in a Markdown link *or* in a docstring —
points at a file that exists. Written after finding that TESTING.md
claimed 109 bundled-rule tests against an actual 98, and omitted
`tests/test_doc.py` (28 tests) entirely. Six bundled rules have no tests
at all; they're named in an explicit list in that file, so the debt is
visible and a *new* untested rule fails instead of joining them quietly.

`.claude/skills/new-rule/` scaffolds a rule directory with the naming and
protocol invariants already correct, and ends at the doc updates the test
above checks.

### `fs_org_kit/cache.py` - the core owns where rules cache

`fs-org-cache --list | --clear [RULE_ID] | --path`. A rule declares
`uses_cache = true` in its manifest; the runner creates
`<cache-root>/rules/<rule-id>/` and passes it as `--cache-dir`. A rule
never resolves a location itself - see
[DESIGN.md](DESIGN.md#the-core-owns-where-rules-cache-not-the-rules) for
why.

This inverted the first implementation, where `duplicate-files-v1`
computed its own per-platform path.

### `duplicate-files-v1`

First bundled rule with `scope = "both"`, and the first to keep state
between runs.

- Per-path, any group of 2+ identical files is reported. Under
  `paths.cross`, only groups spanning 2+ of the given roots are — copies
  living inside one root are not.
- Grouped by size first; a unique-size file is never read. Survivors are
  hashed (`blake2b` by default: stdlib, faster than sha256).
- A cached digest is reused only when size *and* `mtime_ns` both match —
  `cp -p`, `rsync -t`, restores and archive extraction all reproduce an
  old mtime. Rows carry `seen_at`, are swept after `cache_ttl_days`, and
  the sweep is followed by `VACUUM` when it actually removed rows (a bare
  `DELETE` frees pages inside the file but never shrinks it).
- Symlinks and hardlinks to an already-seen inode are deliberately not
  reported — neither is a redundant copy.
- No fixer: finding duplicates is objective, deciding which copy is
  canonical is policy.

### `fs_org_kit/path_patterns.py` - glob keys in `[paths."..."]`

A path key may be a glob (`*`, `**`, `?`, `[abc]`) instead of one exact
location — one entry, every real match sharing its attributes and rule
attachments, invoked once per match. Fills the gap between exact path,
reserved-name pattern, and every-folder blanket. `inherit.py` needed no
changes; it already resolves by key string alone.

Split the same way `allow_missing` is: whether two keys *could* match the
same folder is a validator string comparison (conservative — never a
false negative), while whether a pattern matching nothing is a problem is
runner work governed by `allow_missing`. A pattern overlapping a literal
is an error unless the literal opts in via `inherit`, which surfaced
during end-to-end testing: an unconditional overlap check made the
override mechanism impossible to use, since the override *is* an overlap.

### `fs_org_kit/param_refs.py` - `{ref = "dotted.path"}` param values

Any param on any rule can reference a table or list elsewhere in the
standard, expanded to that table's keys (schema meta keys like
`folders.reserved`'s `prefix` excluded) or that list. Resolved once — the
validator confirms every reference resolves, then the runner expands the
same way.

Motivated by `uncataloged-reserved-v1`'s `cataloged` and
`spelling-abbreviations-v1`'s `abbreviations`, both of which previously
had to be retyped at every attachment site, since a rule script never
sees the parsed standard. Deliberately generic rather than a runner
special case for those two rules.

---

## 0.1

The first working end to end: write a standard, attach rules to it, and
run one command that validates the TOML, executes every attached rule
against the real filesystem, reports violations, and optionally fixes
what's fixable. Listed newest first, like everything above.

### Doc generator (`fs_org_kit/doc.py`)

`fs-org-doc <standard.toml> [flags]`. Validates first and aborts on error
(exit 2) — documenting a standard that doesn't validate produces
confidently-wrong output. Reuses the validator's `resolved_paths` /
`resolved_folders` / `rule_catalog` — a third consumer of the same
machinery, not a reimplementation — and documents the *resolved*
standard, so an inherited `purpose` shows its value marked "(inherited
from ...)" rather than a blank.

- ToC with explicit `<a id="...">` anchors, so links work in any renderer
- One section per part of the standard, each skipped entirely when empty
- Rules section is a reverse index over rules actually *attached*, not the
  whole discovered catalog
- Mermaid diagrams (`tree`, `lifecycle`, `rules`, `cross`), individually
  toggleable; `tree` and `rules` skip above 40 nodes with a note rather
  than emitting something unreadable

### Validator spec + eight more bundled rules

`VALIDATOR_SPEC.md` documents every check, split into **validate**
(structural, always errors, blocks the runner) and **lint** (convention,
always warnings, blocks nothing). Auditing against that split found one
misclassification (`version-format` was an error; a malformed version
breaks nothing) and one gap (alphabetical declaration order wasn't
checked at all).

`[folders.reserved].prefix` became a real configurable field (was
hardcoded `"_"`). Adding it surfaced a bug: the validator treated every
key under `folders.reserved` as a folder entry, so `prefix` itself would
have been flagged.

New rules: `timestamp-consistency-v1` (a name's embedded timestamp must
not contradict its ancestors'), `uncataloged-reserved-v1`,
`naming-pattern-v1` (regex allow/disallow list), `spelling-abbreviations-v1`
(first rule with a third-party dependency, `pyspellchecker`),
`mime-type-v1` (content-sniffed via a built-in magic-byte table, avoiding
a `libmagic` system dependency), `folder-structure-v1` (counts, depth,
size — each independently optional via sentinel defaults),
`staleness-v1` (too old, or unexpectedly recent for an archive; has a
fixer that moves items), and later `timestamp-format-v1`.

`timestamp-format-v1` decouples detection from acceptance: a small
built-in set of raw shapes decides "is this an attempted timestamp at
all," separately from the standard's accepted `formats`. So
`20251231235959name` is flagged and `report.txt` is skipped. Both passes
render each format against a reference datetime to measure its length,
slice that many characters, and validate with `strptime` — real calendar
validation for free, no hand-rolled date regex.

**Removed** `illegal-names-v1` — a single `naming-pattern-v1` attachment
already covered it.

### `basename-sync-v1` - first cross-scope rule with a fixer

Checks whether 2+ paths agree on which file stems exist:
`mode = "shared"` (every stem in all paths) or `"exclusive"` (never in
more than one). `recursive` matching is folder-structure-aware — the same
filename in a *different* subfolder does not satisfy a match.

Its fixer never touches a file itself; it delegates to a user-provided
`fixer_script`, invoked per violating stem with `--present`/`--missing`
as JSON.

Building it surfaced that the runner's fixed 30s subprocess timeout was
far too short for a fixer shelling out to something slow, so `--timeout`
was added to the runner — not specific to this rule.

### Path/folder inheritance (`fs_org_kit/inherit.py`)

Solves state-via-location (PARA-style archiving: a folder moves between
`active/x/` and `archive/x/`). See
[DESIGN.md](DESIGN.md#pathfolder-inheritance) for the mechanism, the
`attributes`/`rules`/`exclude_rules` split, and why `resolve_entries()`
runs once before validation.

```toml
[paths."archive/project-x/".inherit]
attributes = "active/project-x/"
rules = "active/project-x/"        # separate opt-in, merges
exclude_rules = ["staleness-v1"]
```

`allow_missing` is resolved by the runner only, never the validator.
`paths.attributes.defaults` / `folders.attributes.defaults` are generic
standard-wide defaults; precedence is explicit > inherited > default.

### The runner (`fs_org_kit/runner.py`)

Validates first (exit 2 on any error) and reuses `validator.rule_catalog`
rather than discovering a second time. Resolves per-path attachments,
`paths.rules` blanket (every cataloged path), `paths.cross`, and
`folders.rules` blanket (every folder under root) into invocations.

`--fix` invokes a rule's `-fix.py` directly when one exists — not
check-then-fix; the fixer is self-contained. Rules without a fixer still
run their checker in `--fix` mode.

Exit codes: 0 clean, 1 violation/unfixable/broken, 2 standard invalid.

### Validator update

Dropped the old embedded `[rules]` table: removed `_check_rules_catalog`,
`enums.rules.*` loading, and `"rules"` from the required top-level keys.
Added `_load_rule_catalog`, bridging `DiscoveryIssue` to `Issue` (errors
stay errors; warnings get code `rule-discovery-warning`).
`_check_rule_instances` now reads typed `RuleEntry` fields instead of raw
dict lookups.

### Rule discovery (`fs_org_kit/discovery.py`)

One implementation shared by validator, runner, and doc generator, so
tier/precedence logic can't drift between them. Per rule directory
`<name>-v<major>/`: the manifest filename must equal the directory name,
`-check.py` must exist, `-fix.py` is optional and its presence alone sets
`has_fixer`. Directory suffix and manifest `version` major must match;
`severity`/`scope` are checked against the enums in `rule.template.toml`,
read live rather than hardcoded.

| situation | result |
|---|---|
| own vs bundled, same name, `overrides_bundled = true` | own wins |
| own vs bundled, same name, no flag | warning; bundled wins |
| external vs anything, same name | external never wins; the claim is flagged |
| external tier, `include_external = False` | not even scanned |

Returns `(catalog, issues)` as data — discovery never prints.

---

## Not built yet

- **OS-level sandboxing.** The audit-hook harness added in 0.3 is a soft
  guard and can't be made into more from inside the interpreter. Real
  isolation (bubblewrap, Landlock, Seatbelt) changes how rules are
  distributed and trusted, not just how they're invoked. See DESIGN.md.
- **Near-duplicate (similarity) detection.** Needs a separate detector per
  media type sharing only a report format, most of them with third-party
  or non-pip dependencies, and nearest-neighbour search rather than a dict
  lookup. The verdict also becomes a tunable threshold rather than a fact,
  so it can't honestly be `severity = "error"`. Scoped as one rule per
  media type; plain text first, being the only one that needs nothing
  outside the standard library.
