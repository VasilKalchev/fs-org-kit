# Testing fs-org-kit

## Quick start

Install pytest and run the test suite:

```bash
pip install -e ".[dev]"    # installs the package + pytest
pytest                      # runs everything: core package + bundled rules
pytest tests/                       # core package only
pytest rules/                       # bundled rules only
pytest tests/test_inherit.py -v     # run just inheritance tests
pytest tests/test_runner.py -v      # run just runner tests
pytest -k "scope_mismatch"          # run a single test by name
```

## Test organization

**Core package** (`fs_org_kit/`) tests live in `tests/`, one file per module:

- `tests/test_cache.py` - tests for `fs_org_kit.cache`
- `tests/test_discovery.py` - tests for `fs_org_kit.discovery`
- `tests/test_doc.py` - tests for `fs_org_kit.doc`
- `tests/test_inherit.py` - tests for `fs_org_kit.inherit`
- `tests/test_param_refs.py` - tests for `fs_org_kit.param_refs`
- `tests/test_path_patterns.py` - tests for `fs_org_kit.path_patterns`
- `tests/test_runner.py` - tests for `fs_org_kit.runner`
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

This is the same convention documented in `RULES.md` for anyone writing
their own rule: a rule in `rules.own/` or `rules.external/` has no
access to (and shouldn't need) fs-org-kit's own `tests/` - putting a
rule's tests in its own directory means they travel with it wherever it
goes, and can be run standalone (`pytest test_my_rule_v1.py`, from
inside that directory) with zero dependency on this project's
structure. `pytest.ini`'s `testpaths` includes both `tests` and `rules`,
so a bare `pytest` at the project root still picks up everything -
that's a convenience for *this* repo, not something a rule depends on.

## Test coverage

### Docs-currency tests (13 tests, `tests/test_docs_current.py`)

Guards every count and inventory in the sections below, so they can't
quietly go stale.

- **Coverage**: every module has a `tests/test_<module>.py`; every bundled rule has its own `test_*.py`, apart from a named debt list that must shrink rather than grow (a rule on it that gains tests fails until it's removed)
- **Rule inventory**: the bundled tier discovers with no errors and no surprises; every manifest's `version` major matches its directory suffix; `README.md` states the real rule count, in words, in exactly one form
- **Counts**: every `(N tests, path)` claim in this file matches what pytest collects, the bundled total matches the sum, and no collected test file is left undocumented
- **References**: every relative Markdown link resolves, and every `doc/<name>.md` mentioned in prose or in a docstring exists - the case a link check misses

### Cache tests (22 tests, `tests/test_cache.py`)

- **Location**: `$FS_ORG_KIT_CACHE_DIR` wins and gets `~` expanded; the Linux/macOS/Windows fallbacks each resolve to the right per-platform directory (`sys.platform` monkeypatched, so all three are covered on any host); each rule gets its own subdirectory; `rule_cache_dir` is pure - it creates nothing
- **`ensure_rule_cache_dir`**: creates the directory, is idempotent, and returns `None` rather than raising when the location is unusable (a file where the directory should be) - the caller degrades to "run uncached", never to broken
- **List and clear**: an absent root lists empty, sizes are reported per rule and count nested files, clearing one rule leaves the others alone, clearing everything empties the root, and clearing something that was never cached is not an error
- **CLI**: `--path`, `--list` (both the empty and populated forms, including the human-readable size), `--clear <rule-id>`, `--clear`

Every test points `$FS_ORG_KIT_CACHE_DIR` at a `tmp_path`, so the real user cache is never read or written.

### Discovery tests (11 tests, `tests/test_discovery.py`)

- **Baseline**: discovers bundled rules when no own/external rules exist
- **Tier collisions**: own rule vs. bundled (with/without override flag), external rule (can never override)
- **Scan control**: `include_external=False` truly skips the tier, not just filters results
- **Structure validation**: broken TOML, missing checker script, directory name format, version major mismatch, invalid severity/scope values
- **Metadata**: RuleEntry fields are properly populated

### Inherit tests (13 tests, `tests/test_inherit.py`)

- **Basic inheritance**: full attribute inherit with per-field override, standard-wide defaults, an explicit `false` correctly overriding an inherited `true` (the trickiest edge case - booleans have no "empty" state)
- **Rule inheritance**: `exclude_rules` drops specific inherited rule ids while keeping the rest; the same rule id inherited and separately declared both apply (stack, never silently override); `attributes` and `rules` inheriting from different sources
- **Errors and cycles**: undefined references, 2- and 3-level cycles, a broken reference on one entry not blocking resolution of every other entry, `exclude_rules` without `inherit.rules` set, `exclude_rules` referencing something that was never actually inherited

### Validator tests (24 tests, `tests/test_validator.py`)

- **Baseline**: a valid standard with rule attachment produces no errors (except expected lint warnings)
- **Rule attachment errors**: unknown rule, scope mismatch, missing reason, unknown param
- **Pattern keys**: a pattern key alone is fine; a pattern overlapping a literal (or another pattern) is an error; a literal overriding a pattern via `inherit.attributes`/`inherit.rules` is sanctioned and produces no error; the same overlap *without* that `inherit` link is still an error; two overlapping patterns are never sanctioned even with an `inherit` link; two ordinary distinct literals are never flagged
- **Inheritance integration**: an inherited field satisfies required-field validation, undefined/cyclic `inherit` references are errors, `exclude_rules` actually removes a rule from validation (not just from the runner), a purely-inherited entry isn't mistaken for an orphaned rule attachment, `allow_missing` must be a boolean
- **folders.attributes**: unknown-field checking on `folders.reserved.*` entries
- **Param refs**: a `{ref = "..."}` value to `folders.reserved` or `abbreviations` resolves with no errors, a broken ref is an error naming the bad path, a ref satisfies a required-param-with-no-default check the same as a literal would
- **Discovery options**: `include_external` threaded through to the rule catalog used for validation

### Param refs tests (15 tests, `tests/test_param_refs.py`)

- **`is_ref`**: a `{ref: "..."}` table is recognized, a plain string/list/extra-keyed table/non-string ref value is not
- **`expand_param_value`**: a non-ref value passes through unchanged; a table ref expands to its keys; a list ref expands to the list itself; `folders.reserved`'s `prefix` meta key is excluded from its expansion; an unresolvable path, a ref to a scalar, and a partially-missing path are each an error
- **`expand_params`**: literal and ref values coexist in one params dict, an error names the specific param it's about, an empty params dict is fine

### Path patterns tests (20 tests, `tests/test_path_patterns.py`)

- **`is_pattern`**: a literal path is not a pattern; `*`, `**`, `?`, `[abc]` each make a key a pattern
- **`patterns_may_overlap`, fixed-length**: two distinct literals, and two patterns with mismatched segment counts, never overlap; a wildcard segment against a matching (or non-matching) literal prefix; two mutually-compatible wildcard patterns; `[abc]` vs `[xyz]` at the same position conservatively "may overlap" even though they can't really share a character (the documented approximation); a key overlaps with itself
- **`patterns_may_overlap`, `**`**: a `**` pattern against an incompatible literal root doesn't overlap; against a compatible prefix, or another `**` pattern sharing a prefix, it does; two `**` patterns with different literal prefixes don't
- **`expand_pattern`**: matches only real directories (not files), sorted; no matches returns an empty list; a `[1-3]`-style char class range; `**` matches at any depth

### Runner tests (29 tests, `tests/test_runner.py`)

- **Active target resolution**: an existing path is active; a missing path marked `allow_missing` is silently skipped (not reported at all); a missing path without it is reported
- **Pattern keys**: a pattern key expands to every real match, sharing the same catalog key; zero matches with/without `allow_missing` mirrors a literal path's missing/skipped behavior exactly; a real match already claimed by its own explicit literal entry is excluded from the pattern's own expansion (no double invocation); a pattern whose every real match is claimed by literals still isn't "missing"
- **Invocation collection**: per-path attachments, `paths.rules` blanket, `paths.cross`, `folders.rules` blanket (targets root), a missing path correctly excluded from invocations, a pattern-key attachment produces one invocation per real match sharing the same rule
- **Param refs**: a `{ref = "folders.reserved"}` param reaches the invocation as the actual list of reserved-folder names (not the raw ref table, and without the `prefix` meta key leaking in), a ref to a list elsewhere in the standard is expanded verbatim
- **Script invocation**: `ok`/`violation`/`broken` status parsing, a rule with no fixer falls back to its checker even when `--fix` is requested
- **Cache-dir wiring**: a rule declaring `uses_cache` is handed `--cache-dir` and really writes into `<root>/rules/<rule-id>/`; a rule that doesn't declare it never receives the flag (which is what keeps the change additive - every existing rule's argparse would reject an unknown flag) and causes no cache root to be created at all; an unusable cache location still produces the correct verdict
- **Full integration through `main()`**: clean run exits 0, a violation exits 1, a missing path with/without `allow_missing` exits 1/0, an invalid standard exits 2, and the core PARA scenario end-to-end - moving a real folder on disk between two `allow_missing`-marked, inheritance-linked locations needs zero standard edits and the run stays clean before and after

### Doc generator tests (28 tests, `tests/test_doc.py`)

- **Helpers**: slug generation (`/` becomes `-`, special characters stripped, empty falls back), value formatting for booleans/strings/lists
- **Validate first**: an invalid or missing standard exits 2 and generates nothing; warnings don't block
- **Sections**: all present sections by default, `--sections`/`--exclude-sections` filtering, an unknown section name errors, an empty section is omitted rather than emitted blank
- **Diagrams**: `--no-diagrams`, `--diagrams` filtering, the tree reflects real nesting, the 40-node guard, the lifecycle diagram appears only for the known vocabulary, and Mermaid-breaking characters in a path key are sanitized
- **ToC**: present by default, `--no-toc`, and every link has a matching anchor
- **Rendering**: an inherited field shows its value marked as inherited; the rules section lists every attachment site
- **Output style**: generated Markdown contains no em dashes

### Bundled rule tests (130 tests, inside `rules/`)

- **`rules/file-extensions-v1/test_file_extensions_v1.py`** (14 tests): allow list, disallow list, case/dot-agnostic matching, recursive on/off, no-extension files, `exclude` glob filtering (bare name and nested), rejects `--fix` (it has no fixer), rejects an ambiguous "neither list set" call, rejects both-lists-set, rejects a nonexistent path
- **`rules/basename-sync-v1/test_basename_sync_v1.py`** (14 tests): `shared` mode (ok when complete, violation when incomplete), `exclusive` mode (ok when disjoint, violation when overlapping), recursive matching is folder-structure-aware (same filename in a *different* subfolder does not satisfy the match), non-recursive ignores subfolders entirely, `exclude` filtering, `mode` is required with no default, requires 2+ paths, and the fixer: no violations is `ok`, no `fixer_script` configured is `unfixable`, everything resolved is `fixed`, partial success is `violation`, and the exact JSON payload (`--present`/`--missing`) a user's `fixer_script` receives is verified byte-for-byte
- **`rules/folder-structure-v1/test_folder_structure_v1.py`** (13 tests): direct-children counts ok/violation, `recursive` off (a subfolder's own huge child count doesn't count against the root) vs. on (that subfolder is checked against the same threshold using its own direct children, and the violation message names it via a `under '<relpath>'` suffix - absent for the root's own violation), `exclude` removing an item from counts, pruning an excluded folder's subtree from recursion entirely, and excluding a file from the size total, `max_depth`/`max_size` violations, rejects `--fix` (no fixer), no thresholds set is `ok`, rejects a nonexistent path
- **`rules/duplicate-files-v1/test_duplicate_files_v1.py`** (39 tests): single scope (no duplicates, identical content, same-size-different-content is still `ok` so the size prefilter can't be mistaken for the verdict, recursive on/off, three copies collapse into one group); filters (`min_size` defaulting to 1 so empty files aren't one giant group, `min_size` 0 and 1024, `extensions` narrowing and its dot/case-insensitivity, `exclude` by bare name and by relative path, symlinks and hardlinks are never duplicates); cross scope (a group spanning two roots is a violation, a group living entirely inside one root is *not*, the same tree flagged by a single-scope attachment and clean under a cross one, three roots where only two share a file, full paths in the cross message); the cache (created inside the `--cache-dir` it was handed, *nothing* cached anywhere when that flag is absent so the rule can't invent a fallback location, second run agrees with the first, invalidated by a content change, invalidated by a size change *with mtime deliberately restored* so the size half of the check is what has to catch it, `cache = false` writes nothing, switching algorithm mid-cache still works, expired rows are swept, `cache_ttl_days = 0` disables the sweep, a cache hit under one algorithm does *not* refresh the same path's row under another, and a sweep that removed rows actually shrinks the file on disk - a 5000-row fixture must come back under half its bloated size, which only passes because of the `VACUUM`); argument handling (rejects `--fix`, both `--path` and `--paths`, neither, a single-valued `--paths`, a nonexistent path, an unknown algorithm, a negative `min_size`, a non-list `exclude`). Every test passes `--cache-dir` explicitly, pointed at a temp directory - the same flag the runner supplies - so no test ever reads or writes the real user cache
- **`rules/file-size-v1/test_file_size_v1.py`** (32 tests): per-file `max_size` (under, over, exactly at the inclusive threshold) and `min_size` (including an empty file violating any minimum), both set at once reporting independently, and the two cases that distinguish this rule from `folder-structure-v1` - one oversized file is flagged even when the tree total is small, and many small files never aggregate into a violation; the violation message names the file and formats both sizes, and truncates past five with a count; size units (binary units understood, case and spacing flexible, a bare number is bytes); `recursive` on/off, `extensions` narrowing with dot/case-insensitivity, `exclude` by name and pruning a whole subtree; symlinks skipped (target deliberately placed outside the tree, so following it would have reported a violation) and folders having no size of their own; argument handling (rejects `--fix`, no threshold at all, `min_size` above `max_size`, an unparseable size, an unknown unit, a non-list `exclude`/`extensions`, a nonexistent path, malformed `--params` JSON)
- **`rules/timestamp-format-v1/test_timestamp_format_v1.py`** (18 tests): a plain name and a digit-shaped-but-not-a-real-date name are both `ok`, correctly formatted names (with and without a required trailing separator) are `ok`, a squashed datetime and a date missing its required separator are each a `violation` naming the malformed span, a wrong-shape datetime against a narrower accepted list is a `violation`, a longer digit run isn't misread as a truncated shorter date, `target`/`recursive`/`exclude` behave the same as the other naming rules, rejects `--fix` (no fixer), empty/missing `formats` is broken, rejects a nonexistent path

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
6. **Filter on `.location`, not `.message`**, when checking which field a validator issue is about - `Issue.message` describes *what's wrong* ("must be a boolean if present"), it doesn't repeat the field name; `Issue.location` has the dotted path (`paths."x/".allow_missing`). This bit two tests during development - both looked like validator bugs at first and were actually just the test checking the wrong attribute.
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
