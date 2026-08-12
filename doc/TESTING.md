# Testing fs-org-kit

## Quick start

```bash
pip install -e ".[dev]"    # installs the package + pytest
pytest                      # runs everything: core package + bundled rules
```

More invocations (single module, single test, single rule) are in
[CLAUDE.md](../CLAUDE.md#commands).

## Test organization

**Core package** (`fs_org_kit/`) tests live in `tests/`, one file per module:

- `tests/test_cache.py` - tests for `fs_org_kit.cache`
- `tests/test_discovery.py` - tests for `fs_org_kit.discovery`
- `tests/test_doc.py` - tests for `fs_org_kit.doc`
- `tests/test_fields.py` - tests for `fs_org_kit.fields`
- `tests/test_inherit.py` - tests for `fs_org_kit.inherit`
- `tests/test_param_refs.py` - tests for `fs_org_kit.param_refs`
- `tests/test_path_keys.py` - tests for `fs_org_kit.path_keys`
- `tests/test_path_patterns.py` - tests for `fs_org_kit.path_patterns`
- `tests/test_runner.py` - tests for `fs_org_kit.runner`
- `tests/test_sandbox.py` - tests for `fs_org_kit.sandbox`
- `tests/test_validator.py` - tests for `fs_org_kit.validator`

Plus `tests/test_docs_current.py`, which tests the docs rather than a
module: it fails when this file's counts, `README.md`'s rule count, or
either file's inventories drift from what's actually on disk.

**Rules** are tested differently, and deliberately so: each rule's tests
live *inside that rule's own directory*, not in `tests/`.

```
rules/file-extensions-v1/
  file-extensions-v1.toml
  file-extensions-v1-check.py
  test_file_extensions_v1.py       <- tests live here

rules/basename-sync-v1/
  basename-sync-v1.toml
  basename-sync-v1-check.py
  basename-sync-v1-fix.py
  _shared.py
  test_basename_sync_v1.py         <- tests live here
```

Same convention as `RULES.md`: tests travel with their rule, runnable
standalone (`pytest test_my_rule_v1.py`) with zero dependency on this
repo's structure - which matters once a rule is copied into someone's
`rules.own/` or `rules.external/`. `pytest.ini`'s `testpaths` covers
both `tests` and `rules`, so a bare `pytest` here still runs everything.

## Test coverage

### Docs-currency tests (13 tests, `tests/test_docs_current.py`)

Guards every count and inventory in the sections below, so they can't
quietly go stale.

- **Coverage**: every module has a `tests/test_<module>.py`, and every bundled rule has its own `test_*.py` - with no exemption list, so a new rule without tests fails here
- **Rule inventory**: the bundled tier discovers with no errors and no surprises; every manifest's `version` major matches its directory suffix; `README.md` states the real rule count, in words, in exactly one form
- **Counts**: every `(N tests, path)` claim in this file matches what pytest collects, the bundled total matches the sum, and no collected test file is left undocumented
- **References**: every relative Markdown link resolves, and every `doc/<name>.md` mentioned in prose or in a docstring exists - the case a link check misses
- **Rule templates**: there's a `rules/_template-<scope>-v1/` for every value in `discovery.SCOPE`, and every field in `discovery.MANIFEST_KEYS` appears in every template manifest (commented out counts). Nothing in the package parses those templates - deliberately, since a file the tool reads to learn its own schema is what `rule.template.toml` was - so this is the only thing holding them level with the code

### Cache tests (22 tests, `tests/test_cache.py`)

- **Location**: `$FS_ORG_KIT_CACHE_DIR` wins and gets `~` expanded; the Linux/macOS/Windows fallbacks each resolve to the right per-platform directory (`sys.platform` monkeypatched, so all three are covered on any host); each rule gets its own subdirectory; `rule_cache_dir` is pure - it creates nothing
- **`ensure_rule_cache_dir`**: creates the directory, is idempotent, and returns `None` rather than raising when the location is unusable (a file where the directory should be) - the caller degrades to "run uncached", never to broken
- **List and clear**: an absent root lists empty, sizes are reported per rule and count nested files, clearing one rule leaves the others alone, clearing everything empties the root, and clearing something that was never cached is not an error
- **CLI**: `--path`, `--list` (both the empty and populated forms, including the human-readable size), `--clear <rule-id>`, `--clear`

Every test points `$FS_ORG_KIT_CACHE_DIR` at a `tmp_path`, so the real user cache is never read or written.

### Discovery tests (15 tests, `tests/test_discovery.py`)

- **Baseline**: discovers bundled rules when no own/external rules exist
- **Tier collisions**: own rule vs. bundled (with/without override flag), external rule (can never override)
- **Scan control**: `include_external=False` truly skips the tier, not just filters results
- **Structure validation**: broken TOML, missing checker script, directory name format, version major mismatch, invalid severity/scope values, an unknown manifest field warning without rejecting the rule
- **Disabled rules**: an `_`-prefixed directory is skipped silently (no warning - being skipped is the point), isn't even parsed (broken TOML inside one is not an error), and the bundled `_template-*-v1/` rules never reach the catalog
- **Metadata**: RuleEntry fields are properly populated

### Inherit tests (16 tests, `tests/test_inherit.py`)

- **Basic inheritance**: full inherit with per-field override, each part inheriting only from its own source, an explicit `false` correctly overriding an inherited `true` (the trickiest edge case - booleans have no "empty" state)
- **Rule inheritance**: `exclude_rules` drops specific inherited rule ids while keeping the rest; the same rule id inherited and separately declared both apply (stack, never silently override); `attributes` and `rules` inheriting from different sources
- **Errors and cycles**: undefined references from each of the three keys, 2- and 3-level cycles, a cycle in one part not stopping the others, a broken reference on one entry not blocking resolution of every other entry, `exclude_rules` without `inherit.rules` set, `exclude_rules` referencing something that was never actually inherited

### Field declaration tests (17 tests, `tests/test_fields.py`)

`parse_field_spec` reads what one namespace declares its entries may carry; checking values against that is the validator's job, tested below.

- **Parsing**: the two kinds of field stay apart, declared order is preserved (the doc generator renders in it), `required` and `multi` are read per kind, and a namespace that declares nothing is still usable
- **Vocabularies**: a grouping field reads `enums.group.<field>`, both namespaces read the same table for the same field name, an attribute's vocabulary is optional (`enums.attributes.<field>`), and a grouping field with none warns but still groups
- **Namespaces are independent**: `folders` reads its own field lists
- **Declaration errors**: a non-list `names`; `required`/`multi` naming a field that was never declared; a field named after one of an entry's structural keys (`group`/`rules`/`inherit`); one name declared as both kinds; a name listed twice

### Validator tests (43 tests, `tests/test_validator.py`)

- **Baseline**: a valid standard with rule attachment produces no errors (except expected lint warnings)
- **Rule attachment errors**: unknown rule, scope mismatch, missing reason, unknown param
- **Pattern keys**: a pattern key alone is fine; a pattern overlapping a literal (or another pattern) is an error; a literal overriding a pattern via `inherit.attributes`/`inherit.rules` is sanctioned and produces no error; the same overlap *without* that `inherit` link is still an error; two overlapping patterns are never sanctioned even with an `inherit` link; two ordinary distinct literals are never flagged
- **Inheritance integration**: an inherited field satisfies required-field validation, undefined/cyclic `inherit` references are errors, `exclude_rules` actually removes a rule from validation (not just from the runner), a purely-inherited entry isn't mistaken for an orphaned rule attachment
- **Entry fields**: an attribute may be a string or a list of strings and nothing else; a required field left empty is an error; an undeclared field is flagged; a grouping value outside its vocabulary, a single-valued grouping field given a list, and a multi-valued one given a scalar are each an error; a grouping field with no vocabulary warns once and accepts anything
- **folders**: the namespace declares its own fields (a name declared for `paths` is still unknown here) and groups against the shared `enums.group.*` vocabulary; reserved entries under a namespace that declares nothing at all are flagged, since their fields would be both unchecked and unrendered
- **Param refs**: a `{ref = "..."}` value to `folders.reserved` or `abbreviations` resolves with no errors, a broken ref is an error naming the bad path, a ref satisfies a required-param-with-no-default check the same as a literal would
- **Tags**: a well-formed namespace is clean and the whole `[tags]` table is optional (absent and empty are both fine); the pre-2.1 flat `state = "meaning"` form is an error naming itself rather than a bare type error; a namespace key nothing reads warns, a namespace with no values warns, a non-boolean `multi` and a non-string value meaning are errors; and a namespace reaches a rule's params whole, with its cardinality and meanings intact
- **Discovery options**: `include_external` threaded through to the rule catalog used for validation

### Param refs tests (16 tests, `tests/test_param_refs.py`)

- **`is_ref`**: a `{ref: "..."}` table is recognized, a plain string/list/extra-keyed table/non-string ref value is not
- **`expand_param_value`**: a non-ref value passes through unchanged; a table ref expands to the whole table (keys *and* values), a list ref to the list itself, a nested table keeping its own structure, and a scalar to that scalar; meta keys sitting beside a table's entries are **not** stripped out, since deciding which are entries belongs to the rule reading it; an unresolvable path and a partially-missing path are each an error
- **`expand_params`**: literal and ref values coexist in one params dict, an error names the specific param it's about, an empty params dict is fine

### Path patterns tests (20 tests, `tests/test_path_patterns.py`)

- **`is_pattern`**: a literal path is not a pattern; `*`, `**`, `?`, `[abc]` each make a key a pattern
- **`patterns_may_overlap`, fixed-length**: two distinct literals, and two patterns with mismatched segment counts, never overlap; a wildcard segment against a matching (or non-matching) literal prefix; two mutually-compatible wildcard patterns; `[abc]` vs `[xyz]` at the same position conservatively "may overlap" even though they can't really share a character (the documented approximation); a key overlaps with itself
- **`patterns_may_overlap`, `**`**: a `**` pattern against an incompatible literal root doesn't overlap; against a compatible prefix, or another `**` pattern sharing a prefix, it does; two `**` patterns with different literal prefixes don't
- **`expand_pattern`**: matches only real directories (not files), sorted; no matches returns an empty list; a `[1-3]`-style char class range; `**` matches at any depth

### Path keys tests (22 tests, `tests/test_path_keys.py`)

- **Key shape**: a relative key isn't absolute; a leading slash is; `~` is absolute once expanded
- **`resolve_key`**: relative joins onto root, absolute ignores root, `~` expands, `..` resolves above root - plus the two tests that pin why a bare join isn't equivalent: it silently discards root for an absolute key, and never expands `~` at all
- **`comparison_key`**: relative and absolute lookalikes stay distinct; two spellings of the same out-of-root place normalize together; trailing slashes are irrelevant
- **Validator**: an absolute, `~`-relative or `..`-walking key validates like any other, including inside a `[[paths.cross]]` set - nothing has to be declared for one
- **Overlap across the root boundary**: `/srv/*/` and `srv/*/` don't collide, while `~/shared/*/` and `/home/me/shared/*/` still do
- **Runner**: an out-of-root target is invoked where it actually lives, an absent one contributes no invocation; `expand_pattern` globs an absolute pattern from the filesystem anchor (`Path.glob` refuses one outright) while a relative pattern still globs from root

### Sandbox tests (36 tests, `tests/test_sandbox.py`)

Enforcement only exists in a child process, so these drive a real one: a
throwaway script is written to disk and run exactly the way the runner
runs a rule, and the assertions are on its exit code, its stderr, and
what did or didn't happen on disk.

- **Reading `[sandbox]`**: absent grants nothing; `true` grants; `false` is a denial that's allowed to be spelled out; a typo'd capability and a non-boolean value are both reported rather than silently granting nothing; every documented capability name is accepted
- **Policy construction**: a checker gets neither root nor its targets (the "checkers never write" convention, enforced) but still gets its cache; temp is always writable; a fixer gets root and its targets, including an out-of-root one; round-trips through JSON; `wrap` preserves the rule's argv and passes `-B`
- **Writes**: blocked outside the policy and allowed inside; reads never blocked; `os.open`'s write flags caught without a mode string; mkdir/remove/rename/`shutil.move` blocked, with rename checked on both ends; a symlink out of a writable directory does *not* widen the policy (paths are compared after `realpath`); `unrestricted_writes` lets everything through
- **Capabilities**: network, subprocess and ctypes each blocked by default and each usable once granted
- **Violations can't be swallowed**: `except Exception` doesn't catch one (it derives from `BaseException`), and even `except BaseException` still fails the invocation, because the violation is also recorded
- **Script semantics preserved**: argv reaches the script, exit codes propagate, stdout stays exactly one JSON line, an uncaught error still reports on stderr, and a sibling module beside the script is importable - `runpy.run_path` doesn't put the script's directory on `sys.path` the way direct execution does, and `staleness-v1` broke on precisely that

### Runner tests (39 tests, `tests/test_runner.py`)

- **Active target resolution**: an existing path is active; one that isn't on disk is silently skipped, since whether a location should exist is a rule's question
- **Pattern keys**: a pattern key expands to every real match, sharing the same catalog key; zero matches is skipped exactly like a literal path that isn't there; a real match already claimed by its own explicit literal entry is excluded from the pattern's own expansion (no double invocation), and a pattern whose every match is claimed that way contributes nothing of its own
- **Invocation collection**: per-path attachments, `paths.rules` blanket, `paths.cross`, `folders.rules` blanket (targets root), an absent path contributing nothing, a pattern-key attachment producing one invocation per real match sharing the same rule
- **Reserved-name attachments**: `folders.reserved."_x".rules` produces one invocation per folder *named* `_x` on disk (a reserved entry is a name, not a location); a name matching nothing contributes none; a match nested inside another isn't pruned; an entry with no rules is skipped without walking; a folder that is both a reserved name and its own `[paths."..."]` entry gets both sets of rules against the same target; inherited rule attachments are carried and still marked with their origin
- **Param refs**: a `{ref = "folders.reserved"}` param reaches the invocation as that table itself - meta keys included, not the raw ref table and not a projection of it - a ref to a list elsewhere in the standard is expanded verbatim, and a ref to a tag namespace arrives as one object carrying its vocabulary, its cardinality and its meanings
- **Script invocation**: `ok`/`violation`/`broken` status parsing, a rule with no fixer falls back to its checker even when `--fix` is requested
- **Stale plans are skipped, not broken**: a target that stopped existing between planning and invocation is `skipped` (and one replaced by a file likewise), including a cross-scope invocation where only one of its paths went; a target that was *already* absent when the plan was built is not skipped but still reported `broken` at exit 1 (a `paths.cross` reference to somewhere that never existed - a misconfigured attachment, not a fixer's doing); the guard belongs to `run_invocation`, so `invoke_script` handed a bad path directly still reports `broken`
- **Cache-dir wiring**: a rule declaring `uses_cache` is handed `--cache-dir` and really writes into `<root>/rules/<rule-id>/`; a rule that doesn't declare it never receives the flag (which is what keeps the change additive - every existing rule's argparse would reject an unknown flag) and causes no cache root to be created at all; an unusable cache location still produces the correct verdict
- **Full integration through `main()`**: clean run exits 0, a violation exits 1, a cataloged path that isn't on disk exits 0, an invalid standard exits 2, a fixer that archives a folder leaves the per-folder check already planned against its old location reporting `skipped` rather than `broken` and the run still exiting 0, and the core PARA scenario end-to-end - moving a real folder on disk between two inheritance-linked locations needs zero standard edits and the run stays clean before and after

### Doc generator tests (41 tests, `tests/test_doc.py`)

- **Helpers**: slug generation (`/` becomes `-`, special characters stripped, empty falls back), value formatting for booleans/strings/lists
- **Validate first**: an invalid or missing standard exits 2 and generates nothing; warnings don't block
- **Sections**: all present sections by default, `--sections`/`--exclude-sections` filtering, an unknown section name errors, an empty section is omitted rather than emitted blank
- **Diagrams**: `--no-diagrams`, `--diagrams` filtering, the tree reflects real nesting, the 40-node guard, and Mermaid-breaking characters in a path key are sanitized
- **ToC**: present by default, `--no-toc`, and every link has a matching anchor
- **Rendering**: an inherited field shows its value marked as inherited; the rules section lists every attachment site; a list-valued field becomes bullets rather than reaching the table as a Python repr, a string-valued one becomes a table row, one holding only empty placeholders is omitted, an undeclared field is never rendered at all, and a grouping value links to its vocabulary
- **Grouping index**: one bucket list per grouping field, entries listed under their value, a multi-valued field listing an entry under each of its values, and no index at all when a standard declares no grouping fields
- **Tags**: a namespace renders its description and a row per value, cardinality is stated either way, several namespaces each get their own table, and an empty `[tags]` emits no section
- **Output style**: generated Markdown contains no em dashes

### Bundled rule tests (647 tests, inside `rules/`)

The three rule templates are counted here too, since they live under
`rules/` and run with everything else - but they are not bundled rules:
discovery skips them, and their tests exist so a template that stops
matching the protocol fails in this repo rather than in whatever someone
copied it into.

- **`rules/_template-single-v1/test__template_single_v1.py`** (7 tests): a clean directory is `ok` under the checker and the fixer, `recursive = false` is accepted, and the four broken-script cases (checker rejects `--fix`, either script given a nonexistent path, malformed `--params` JSON)
- **`rules/_template-cross-v1/test__template_cross_v1.py`** (7 tests): two clean directories are `ok` under the checker and the fixer, `recursive = false` is accepted, and the script's own argument errors - rejects `--fix`, rejects a single `--paths` value (the 2-or-more minimum is the script's to enforce, not the runner's), rejects a nonexistent path
- **`rules/_template-both-v1/test__template_both_v1.py`** (9 tests): `--path` and a `--paths` set each `ok`, plus the three ambiguous calls `scope = "both"` makes the script responsible for rejecting (both flags at once, neither, a single-valued `--paths`) - asserted against the fixer as well, which repeats the validation rather than trusting its caller

- **`rules/file-extensions-v1/test_file_extensions_v1.py`** (14 tests): allow list, disallow list, case/dot-agnostic matching, recursive on/off, no-extension files, `exclude` glob filtering (bare name and nested), rejects `--fix` (it has no fixer), rejects an ambiguous "neither list set" call, rejects both-lists-set, rejects a nonexistent path
- **`rules/basename-sync-v1/test_basename_sync_v1.py`** (14 tests): `shared` mode (ok when complete, violation when incomplete), `exclusive` mode (ok when disjoint, violation when overlapping), recursive matching is folder-structure-aware (same filename in a *different* subfolder does not satisfy the match), non-recursive ignores subfolders entirely, `exclude` filtering, `mode` is required with no default, requires 2+ paths, and the fixer: no violations is `ok`, no `fixer_script` configured is `unfixable`, everything resolved is `fixed`, partial success is `violation`, and the exact JSON payload (`--present`/`--missing`) a user's `fixer_script` receives is verified byte-for-byte
- **`rules/folder-structure-v1/test_folder_structure_v1.py`** (13 tests): direct-children counts ok/violation, `recursive` off (a subfolder's own huge child count doesn't count against the root) vs. on (that subfolder is checked against the same threshold using its own direct children, and the violation message names it via a `under '<relpath>'` suffix - absent for the root's own violation), `exclude` removing an item from counts, pruning an excluded folder's subtree from recursion entirely, and excluding a file from the size total, `max_depth`/`max_size` violations, rejects `--fix` (no fixer), no thresholds set is `ok`, rejects a nonexistent path
- **`rules/duplicate-files-v1/test_duplicate_files_v1.py`** (39 tests): single scope (no duplicates, identical content, same-size-different-content is still `ok` so the size prefilter can't be mistaken for the verdict, recursive on/off, three copies collapse into one group); filters (`min_size` defaulting to 1 so empty files aren't one giant group, `min_size` 0 and 1024, `extensions` narrowing and its dot/case-insensitivity, `exclude` by bare name and by relative path, symlinks and hardlinks are never duplicates); cross scope (a group spanning two roots is a violation, a group living entirely inside one root is *not*, the same tree flagged by a single-scope attachment and clean under a cross one, three roots where only two share a file, full paths in the cross message); the cache (created inside the `--cache-dir` it was handed, *nothing* cached anywhere when that flag is absent so the rule can't invent a fallback location, second run agrees with the first, invalidated by a content change, invalidated by a size change *with mtime deliberately restored* so the size half of the check is what has to catch it, `cache = false` writes nothing, switching algorithm mid-cache still works, expired rows are swept, `cache_ttl_days = 0` disables the sweep, a cache hit under one algorithm does *not* refresh the same path's row under another, and a sweep that removed rows actually shrinks the file on disk - a 5000-row fixture must come back under half its bloated size, which only passes because of the `VACUUM`); argument handling (rejects `--fix`, both `--path` and `--paths`, neither, a single-valued `--paths`, a nonexistent path, an unknown algorithm, a negative `min_size`, a non-list `exclude`). Every test passes `--cache-dir` explicitly, pointed at a temp directory - the same flag the runner supplies - so no test ever reads or writes the real user cache
- **`rules/file-size-v1/test_file_size_v1.py`** (32 tests): per-file `max_size` (under, over, exactly at the inclusive threshold) and `min_size` (including an empty file violating any minimum), both set at once reporting independently, and the two cases that distinguish this rule from `folder-structure-v1` - one oversized file is flagged even when the tree total is small, and many small files never aggregate into a violation; the violation message names the file and formats both sizes, and truncates past five with a count; size units (binary units understood, case and spacing flexible, a bare number is bytes); `recursive` on/off, `extensions` narrowing with dot/case-insensitivity, `exclude` by name and pruning a whole subtree; symlinks skipped (target deliberately placed outside the tree, so following it would have reported a violation) and folders having no size of their own; argument handling (rejects `--fix`, no threshold at all, `min_size` above `max_size`, an unparseable size, an unknown unit, a non-list `exclude`/`extensions`, a nonexistent path, malformed `--params` JSON)
- **`rules/empty-v1/test_empty_v1.py`** (26 tests): zero-byte files reported and non-empty ones not (a single whitespace byte is not empty - zero bytes is a fact about the file, "looks blank" isn't), `check_files`/`check_folders` each switchable, recursive on/off; empty folders reported, the scanned path itself reported when empty, and a reported folder not also listing what's inside it; both readings of `folder_empty_means` (`no_entries` flags only the literal leaf, `no_files` flags a hollow tree at its top and respects a single deep file); `exclude` suppressing a report while *not* making a folder count as empty; symlinks never empty, a dangling one left to `link-integrity-v1`, and a symlink counting as content; rejects `--fix`, an unknown meaning, both checks disabled (an attachment that can never report anything), a non-list `exclude`, a nonexistent path, malformed `--params`
- **`rules/link-integrity-v1/test_link_integrity_v1.py`** (39 tests): symlinks (dangling, intact, relative-to-its-own-directory, to a directory, a chain ending in a dangling link, a cycle, kind switchable off, and a symlink named `x.desktop` still classified as a symlink); `.desktop` entries (`Type=Link` to a missing/existing file, percent-decoding, `Type=Application` with a missing program and one resolved via `PATH`, `Type=Directory` having nothing to break, field codes and `;`-lists not breaking the parser, a `Type=Link` with no URL, and an `http` URL counted but never judged); Windows shortcuts, with `.lnk` fixtures assembled byte by byte so the offsets can be varied (missing/existing local target, a `C:\` path skipped by default and reported under `report_foreign = true` and still counted in the message when skipped, a non-shell-link file, a truncated header, a wrong class id, and a network-target link that is *not* called broken); traversal (recursive on/off, exclusions, and a symlinked directory checked as a link rather than descended into, so a link to an ancestor can't loop); argument handling (rejects `--fix`, unknown/empty `kinds` including the now-out-of-scope `webloc`, a non-list `exclude`, a nonexistent path)
- **`rules/link-policy-v1/test_link_policy_v1.py`** (27 tests): each kind independently `forbidden` (files, folders, links) and `required` (present, missing, satisfied anywhere in scope, not satisfied out of scope); the whole arrangement the rule exists for - subfolders plus links and no real files - passing all three policies at once, and one snuck-in file breaking it; classification is link-first (a `.desktop` counts as a link not a file, narrowing `link_kinds` to `["symlink"]` makes it a file again, a symlink to a directory is a link not a folder, `.lnk`/`.url`/`.webloc` all count, and a *broken* link still counts as one since that's `link-integrity-v1`'s question); traversal (not recursive by default, recursion finding buried entries, exclusions, and a link to an ancestor not looping); argument handling (rejects `--fix`, an attachment where all three are `allowed` and so constrains nothing, an unknown policy or link kind, a link policy with no `link_kinds`, a non-list `exclude`, a nonexistent path)
- **`rules/required-content-v1/test_required_content_v1.py`** (23 tests): `required` present/missing, satisfied by a glob, naming a nested path; `suggested` reported as its own tier, both tiers in one message, and `report_suggested = false` silencing only that tier; `forbidden` reported (including a bare-name glob matching at any depth), absent is ok, a forbidden directory, and duplicate hits reported once; the trailing slash meaning "directory" (a file doesn't satisfy `build/`, a directory does, without the slash either kind does, and a symlink to a directory does *not*); argument handling (rejects `--fix`, an attachment where all three tiers are empty and so asserts nothing, a non-list tier, a tier holding non-strings, a nonexistent path, malformed `--params`)
- **`rules/changed-since-v1/test_changed_since_v1.py`** (31 tests): baselines (first run records and reports `ok`, an unchanged second run is `ok`, *without* `--cache-dir` every run is a first run so the rule can't invent a location, separate paths get separate baselines, a corrupt snapshot is treated as no snapshot); detection (added/removed/modified files, added directories, nested changes with `recursive` on/off, exclusions, and a folder never reported as *modified* - its own mtime moves whenever anything inside it appears, which would double-report when recursive and leak deep edits when not); `track` modes (size-only ignoring a pure timestamp change and its blind spot for a byte-for-byte replacement, mtime-only catching that same edit, and a file becoming a directory registering under any mode); `update_baseline` advancing by default vs. keeping a change reported until it's dealt with; the three report formats (summary on one line, `list` one per line, `tree` drawing the hierarchy with `+ - ~` markers and collapsing unchanged branches away) and `max_reported` truncating with a count; argument handling (rejects `--fix`, unknown `track`/`report`, a non-positive `max_reported`, a non-list `exclude`, a nonexistent path)
- **`rules/xdg-inherit-folder-icon-color-v1/test_xdg_inherit_folder_icon_color_v1.py`** (33 tests): a matching child ok, a differently-colored child reported with its before/after name, an unset child reported and `skip_unset` leaving it alone, an explicit `color` overriding the parent's own, a parent with no color reported rather than silently passing, recursion on/off, exclusions, and symlinked folders not followed; the variant surviving a recolor (including a multi-segment one, a child with no variant, and an uncolored icon keeping its variant); `on_different_color` (`change` recolors, `warn` reports without writing, `ignore` reports nothing, and `warn` still setting *unset* children since it's about not overriding a deliberate choice); custom icons reported but never rewritten, both absolute-path and theme-name ones; `.directory` handling (other keys and other groups preserved, the file created when absent, `Icon=` added to an existing group without one, and nothing rewritten when there's nothing to do); argument handling (checker rejects `--fix`, fixer refuses to run without it, a color not in `colors`, an unknown `on_different_color`, empty `colors`, an empty `icon_prefix`, and a custom prefix/color vocabulary working end to end)
- **`rules/xdg-auto-folder-icon-v1/test_xdg_auto_folder_icon_v1.py`** (36 tests): name matching (matching folder gets its icon, non-matching left alone, the fixer writing it, already-correct is `ok`); content matching (`contains` requiring a direct child and *all* of them, and deliberately not recursing; `contains_any` needing only one; `ratio` expressing "mostly images" and not matching when unmet; `empty`; and several conditions in one entry being ANDed); ordering (first match wins, and reordering changing the answer - the rule is ordered rather than scored); color preservation (an existing color kept, an existing variant replaced, `default_color` filling in when there is none, an icon without `{color}` used verbatim, and composing with `xdg-inherit-folder-icon-color-v1` so neither rule can undo the other's decision); traversal and `.directory` handling as above; argument handling (checker rejects `--fix`, fixer refuses without it, missing `match`, a condition-free entry that would match every folder, an entry with no icon, an invalid regex, an unknown condition key, `ratio` without `contains_any`, `ratio` out of range, a `default_color` not in `colors`)
- **`rules/mime-type-v1/test_mime_type_v1.py`** (42 tests): every recognized magic number maps to the type it should, the RIFF subtype is read past the container header (WEBP and WAV share a magic, and a WAV is *not* reported as a WEBP), `ftyp` is found at its non-zero offset, and the text fallback holds only for valid NUL-free UTF-8 - both a NUL byte and invalid UTF-8 defeat it, each asserted through `unknown_is_violation` so "unrecognized" can't pass itself off as "text", and an empty file is unrecognized rather than text; the mismatches the rule exists for (a PNG named `.txt`, an executable named `.jpg`, and the same PNG sniffing identically under either name, since the extension is never consulted); allowed and disallowed lists; unknown handling (skipped by default, counted against an `allowed` list on request, and never against a `disallowed` one - "not on the forbidden list" can't be decided for a type you couldn't identify); traversal, folders never sniffed, `exclude` by name and by nested glob, and an excluded file not sniffed even when unknowns count; message truncation; argument handling (rejects `--fix`, neither or both lists set, a non-list `exclude`, a nonexistent path, malformed `--params`)
- **`rules/naming-pattern-v1/test_naming_pattern_v1.py`** (30 tests): `allow` mode (every name must match) and `disallow` mode (none may), including both reference patterns the manifest documents, tested as written - the portable-charset one and the OS-default-names one; matching semantics (the pattern is a `search`, so it hits anywhere in a name until you anchor it yourself; a file is matched on its full name *including* extension, unlike `spelling-abbreviations-v1`'s stem; only an item's own name is matched, so a matching parent folder doesn't implicate its children); `target` files/folders/both; traversal (recursion on/off, a nested violation named by its path relative to the scanned root, `exclude` by bare name and by nested glob, and the fact that excluding a folder filters that folder without pruning its subtree); truncation; argument handling (`pattern` required and rejected when empty - it would match everything - an invalid regex, `mode` required and rejected when unknown, an unknown `target`, a non-list `exclude`, a nonexistent path, malformed `--params`)
- **`rules/spelling-abbreviations-v1/test_spelling_abbreviations_v1.py`** (45 tests): the missing-dependency path first, and independent of whether the dependency is installed - the real package is shadowed by an importable stub with no `SpellChecker` in it, which raises the same `ImportError` an absent package would, so the "run `pip install pyspellchecker`" message is verified even on a machine that has it; everything after that is skipped when it's genuinely missing. Then: correct spellings pass and a typo doesn't, the item is named whole while only the unrecognized words are parenthesized, names split on `-`/`_`/space, a file is checked on its stem (its extension is `file-extensions-v1`'s question) while a folder's whole name is checked, matching is case-insensitive; `abbreviations` and `ignore` are interchangeable to the checker and an absent `abbreviations` means "no shorthand is sanctioned" rather than "skip the check"; `abbreviations` may also arrive as the whole `[abbreviations]` table from a `{ref}`, in which case the shorthand is its keys and a *meaning* gets no free pass; `languages` (English alone flags a German word, listing both accepts it, and a real typo is unrecognized in either - plus an unknown code, an empty list and a non-list are each broken); `min_word_length` in both directions; a purely numeric name is accepted under *either* `numbers_ok` setting, because the dictionary accepts digit runs anyway and the flag exists so the rule doesn't depend on that, while a word with digits *in* it is not numeric; `target`, recursion, relative-path reporting and `exclude`; truncation; argument handling
- **`rules/staleness-v1/test_staleness_v1.py`** (55 tests): `stale` and `active` as exact opposites on one tree, the threshold boundary being strict, and the effective-timestamp rule that makes the rule usable - a folder is judged by the newest file *anywhere* inside it (so an actively-edited project doesn't read as abandoned just because its own mtime is old), an empty one falls back to its own timestamp, and only direct children are ever judged; `basis = "atime"` read independently of mtime (one file backdated on one axis only); duration units, with a week really seven days and a month really thirty; `exclude` matched against a direct child's own *name*, not a relative path, since this rule never sees anything deeper; the message naming mode and threshold, ages rendered in days and sub-day ones in hours, and truncation. The fixer: nothing to do is `ok`, violations are moved, a relative `destination` resolves against `--path`'s *parent* (the sibling archive, not a subfolder of what's being swept) while an absolute one is used as-is, a folder moves whole, `active` mode moves the recently-touched item *out* of the archive, a missing destination is `unfixable` and is never created - yet is still `ok` when there was nothing to move - and a name collision is never overwritten and doesn't stop the other moves. Dated destinations: `%Y` files under the current year, `create_destination` opens the folder that doesn't exist yet (nested, in one call) while its default `false` keeps the never-creates stance intact, a destination with no placeholder resolves to exactly the same folder it always did, and an already-existing dated folder needs no opt-in at all. Argument handling covers both scripts: the checker rejects `--fix` and points at the fixer, the fixer refuses to run without it, `mode`/`threshold` are required of both, `destination` of the fixer only (a read-only attachment shouldn't name a place it will never move anything to), plus an unknown mode or basis, five malformed thresholds, a non-list `exclude`, a nonexistent path, malformed `--params`
- **`rules/timestamp-consistency-v1/test_timestamp_consistency_v1.py`** (37 tests): consistent chains (year/month/day nesting, separatorless forms equivalent to hyphenated ones, an undated folder skipped rather than breaking the chain, dated siblings not constraining each other, and `--path`'s own name never parsed - the rule can't know whether it's a catalog key or an accident of where the tree lives); conflicts (year, month, and a file's `YYYYMMDD_HHMMSS` contradicting its folder's date, several fields conflicting reported together, an intermediate folder checked on its own account rather than only leaf files, one bad folder reported *once* rather than once per descendant beneath it, and a second conflict under the same parent still found); which forms are recognized (each folder shape establishes a constraint; the datetime prefix carries one into a filename; `2025-01-01.md` carries none, because the date patterns are fully anchored and only the prefix form survives an extension; a bare `2025-01-01` file does; `2026-03-05-holiday` doesn't, that being `timestamp-format-v1`'s question; and a wrong-length digit run is not a date); `require_all_components_timestamped` off and on; recursion, including that `recursive = false` still checks the direct children themselves; truncation; argument handling
- **`rules/uncataloged-reserved-v1/test_uncataloged_reserved_v1.py`** (32 tests): a cataloged reserved folder passes and an uncataloged one doesn't, a folder without the prefix is never checked at all, an empty *or absent* `cataloged` flags every reserved-looking folder rather than refusing to run, a catalog entry with no folder on disk is not a violation (that being `required-content-v1`'s question), files are never checked, and matching is case-sensitive; `cataloged` as a whole `[folders.reserved]` table from a `{ref}` (entry names taken from its table-valued keys, a folder named after a meta key beside them still flagged, an empty table cataloging nothing); `prefix` (the `_` default, a custom one, a multi-character one, named back in the message, and empty or non-string rejected - an empty prefix matches every folder); traversal (recursion on/off, a nested folder reported by its relative path, the catalog matching a *basename* at any depth, a reserved folder nested inside a cataloged reserved folder still checked, `exclude` by bare name and by nested glob, and excluding a folder not pruning its subtree); sorted output and truncation; argument handling
- **`rules/timestamp-format-v1/test_timestamp_format_v1.py`** (18 tests): a plain name and a digit-shaped-but-not-a-real-date name are both `ok`, correctly formatted names (with and without a required trailing separator) are `ok`, a squashed datetime and a date missing its required separator are each a `violation` naming the malformed span, a wrong-shape datetime against a narrower accepted list is a `violation`, a longer digit run isn't misread as a truncated shorter date, `target`/`recursive`/`exclude` behave the same as the other naming rules, rejects `--fix` (no fixer), empty/missing `formats` is broken, rejects a nonexistent path
- **`rules/transfer-v1/test_transfer_v1.py`** (38 tests): selection (loose files and whole folders reported, `exclude`, `min_age`, `recursive` flattening, a dated target expanding strftime, `{name}` expanding to the source's own basename, `direction = "reverse"` swapping which declared path is which, and a target nested inside its own source not collecting itself); the "move" fixer (files and whole folders relocated and gone from the source, rechecking after a move is `ok`, the target created by default and `create_target = false` reporting `unfixable` instead, `on_conflict` `rename`/`skip`/`fail`, and nothing ever overwritten under any setting); the "copy" fixer (source left intact, and rechecking after a copy is `ok` - the source keeping its own copy isn't evidence anything is still outstanding); the "sync" fixer (only entries missing from the target are transferred, an entry already there is not a violation, and a fully synced source reports `ok`); argument handling (checker rejects `--fix`, fixer refuses to run without it, requires exactly 2 `--paths`, `operation`/`direction` required with no default and rejects an unknown value, an unknown `on_conflict`, a non-list `exclude`, a nonexistent source, source and target resolving to the same path, an unparseable `min_age`, malformed `--params`)

## Running specific test classes or methods

```bash
pytest tests/test_inherit.py::TestErrorsAndCycles -v
pytest tests/test_runner.py::TestMainIntegration::test_inheritance_follows_a_real_filesystem_move -v
pytest rules/basename-sync-v1/test_basename_sync_v1.py::TestFixer -v
```

## Test fixtures and temporary directories

Tests use `pytest`'s built-in `tmp_path` fixture (or `tempfile.TemporaryDirectory()` where a plain `Path` object is more convenient) to create isolated test environments. Each test is self-contained and cleans up after itself.

## Adding new tests

**For the core package** (`fs_org_kit/`): add to the matching file in `tests/`, or create a new `tests/test_<module>.py` if you're adding a new module.

**For a rule**: add `test_<rule_id_with_underscores>.py` inside that rule's own directory (see "Test organization" above) - not in `tests/`.

General guidance, either way:

1. Import test classes as `Test*` (pytest recognizes these automatically)
2. Import test methods as `test_*`
3. Use the `tmp_path` fixture (pytest-provided) or `tempfile.TemporaryDirectory()` for file-based tests
4. Populate temporary directories with minimal valid TOML fixtures
5. Avoid `assert` messages - pytest's output is clear enough
6. **Filter on `.location`, not `.message`**, when checking which field a validator issue is about - `Issue.message` describes *what's wrong* ("must be a boolean if present"), it doesn't repeat the field name; `Issue.location` has the dotted path (`paths."x/".purpose`). This bit two tests during development - both looked like validator bugs at first and were actually just the test checking the wrong attribute.
7. **For rule tests specifically**: invoke the script via `subprocess`, exactly as the runner does - not by importing the script's internals. That's the real, documented protocol contract; testing through it catches anything an internals-only test would miss, and it's also what a third-party rule author copying your test file as a template would expect to see.

Example (core package):

```python
def test_my_new_case(self, tmp_path):
    """One-line description of what you're testing."""
    # Setup
    test_file = tmp_path / "test.toml"
    test_file.write_text('version = "1.0"')
    
    # Action
    result = some_function(test_file)
    
    # Assert
    assert result == expected
```

## Configuration

Pytest is configured in `pytest.ini`:
- `testpaths = tests rules` - core package tests, plus every bundled rule's own tests
- `addopts = -v --tb=short` - verbose output, short tracebacks

## CI/CD

To integrate into CI (GitHub Actions, GitLab CI, etc.):

```bash
pip install -e ".[dev]"
pytest
```

Exit code is 0 if all tests pass, 1 if any fail.
