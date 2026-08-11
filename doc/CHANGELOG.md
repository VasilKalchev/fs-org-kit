# Changelog

Newest first. This records *what* changed; the reasoning behind design
decisions lives in [DESIGN.md](DESIGN.md).

Four commands: `fs-org-validate`, `fs-org-run`, `fs-org-doc`,
`fs-org-cache`. The current rule count lives in
[README.md](../README.md), not here, so there's one place to update it.

---

## 0.2

Everything below 0.1 still holds; this adds param references, glob path
keys, rule-owned caching, two rules, and self-checking docs.

### `examples/`

`examples/para/` — a toy PARA tree, a standard governing it, and a
tutorial. Three violations are seeded into the tree so the first run
reports something, and the standard stays small enough to read in one
sitting: glob path keys, `inherit`, and one fixer, not a tour of the
grammar.

Each example's `root` is relative, which makes it cwd-dependent — the
tutorial says to run from the example's own directory. An absolute root
can't be committed, and resolving a relative root against the standard's
own location is a change to `runner.py`, not to an example.
`tests/test_docs_current.py` now scans `examples/` for dangling doc
links.

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
never resolves a location itself.

This inverted the first implementation, where `duplicate-files-v1`
computed its own per-platform path — that works, and leaves the core
with no inventory to report on or clear, and copies the path logic into
every caching rule. Additive by construction: a rule that doesn't
declare `uses_cache` never receives the flag, so no existing rule's
argument parsing broke. Nothing clears these automatically — `pip
uninstall` included — which is why the management CLI exists.

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
`active/x/` and `archive/x/`). Catalog both locations; whichever isn't
real on disk is skipped, not flagged, so moving it needs zero standard
edits.

```toml
[paths."archive/project-x/".inherit]
attributes = "active/project-x/"
rules = "active/project-x/"        # separate opt-in, merges
exclude_rules = ["staleness-v1"]
```

- `attributes` and `rules` may point at different sources or be omitted
  independently; chains allowed, cycles are a validation error
- A rule both inherited and declared directly applies twice — never a
  silent override
- `allow_missing` is resolved by the runner only, never the validator
- `paths.attributes.defaults` / `folders.attributes.defaults` are generic
  standard-wide defaults; precedence is explicit > inherited > default
- `resolve_entries()` runs once, before validation, producing a flattened
  `ResolvedEntry` per key — nothing downstream walks inheritance itself

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

- **Sandboxing / audit-hook harness.** Rule scripts run with the user's
  full permissions. See DESIGN.md, "OS-level sandboxing".
- **Near-duplicate (similarity) detection.** Needs a separate detector per
  media type sharing only a report format, most of them with third-party
  or non-pip dependencies, and nearest-neighbour search rather than a dict
  lookup. The verdict also becomes a tunable threshold rather than a fact,
  so it can't honestly be `severity = "error"`. Scoped as one rule per
  media type; plain text first, being the only one that needs nothing
  outside the standard library.
