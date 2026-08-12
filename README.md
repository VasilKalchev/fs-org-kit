# fs-org-kit

A personal filesystem organization standard, made machine-enforceable.

You write down how your home directory (or any directory tree) *should*
be organized - as data, in TOML, not as a wiki page you'll stop
maintaining - and a set of small scripts check whether it actually is,
and where possible, fix it.

> **Status: 0.1 complete.** Validator, rule discovery, runner, and doc
> generator are all functional, with nineteen bundled rules. For what
> changed and when, see [doc/CHANGELOG.md](doc/CHANGELOG.md). For
> important design decisions and architectural details, see
> [doc/DESIGN.md](doc/DESIGN.md). For a guide to writing your own rules,
> see [doc/RULES.md](doc/RULES.md). For what the validator checks and
> why, see [doc/VALIDATOR_SPEC.md](doc/VALIDATOR_SPEC.md).

---

## The core idea

Two kinds of TOML file, two different rates of change:

- **The standard** - one file, `fs-org-std.toml`, that *you* fill in.
  It describes your directories: what each one is for, its lifecycle,
  where its content came from, and which rules apply to it. This
  changes constantly, in small ways, as you organize more of your life.
- **Rules** - small, independently versioned units that know how to
  *check* (and sometimes *fix*) one specific thing - a naming
  convention, a staleness policy, a size limit. These change rarely
  once written, and are shared: yours, the project's, or someone
  else's.

Keeping these separate (they used to be one file - see
[doc/DESIGN.md](doc/DESIGN.md)) is what lets rules be authored,
shared, and versioned independently of any one person's standard.

---

## Repository layout

```
fs-org-kit/                        (this repo - the tool, not your data)
  pyproject.toml                   # package declaration
  fs-org-std.template.toml         # grammar for a populated fs-org-std.toml
  rule.template.toml               # grammar for a single rule's manifest
  rules/                           # bundled, project-maintained rules
    file-extensions-v1/
      file-extensions-v1.toml
      file-extensions-v1-check.py
  fs_org_kit/                      # the Python package
    __init__.py
    cache.py                       # where rules keep state between runs
    discovery.py                   # rule discovery - shared by all tools
    doc.py                         # generates Markdown documentation
    fields.py                      # the three kinds of field an entry carries
    inherit.py                     # resolves `inherit` and attribute defaults
    param_refs.py                  # {ref = "dotted.path"} param values
    path_keys.py                   # what a path key names, incl. outside root
    path_patterns.py               # glob keys in [paths."..."]
    runner.py                      # runs rule checkers against real filesystem
    sandbox.py                     # audit-hook harness rule scripts run inside
    validator.py                   # validates a populated standard
  examples/                        # runnable example standards + toy trees
    para/
      fs-org-std.toml
      README.md                    # tutorial
      tree/
  doc/                              # design docs, changelog, rule-authoring guide
    CHANGELOG.md
    DESIGN.md
    RULES.md
    TESTING.md
    VALIDATOR_SPEC.md
  README.md
  CLAUDE.md
```

The fastest way in is [`examples/para/`](examples/para/) - a toy PARA
tree with three deliberate mistakes in it, a standard that catches them,
and a tutorial that walks from `fs-org-validate` to `--fix`.

Short commands, once installed (`pip install -e .`):

```
fs-org-validate   your-standard.toml [flags]
fs-org-run        your-standard.toml [flags]
fs-org-doc        your-standard.toml [flags]
```

Or without installing, run the modules directly:

```
python -m fs_org_kit.validator   your-standard.toml [flags]
python -m fs_org_kit.runner      your-standard.toml [flags]
python -m fs_org_kit.doc         your-standard.toml [flags]
```

## A user's own directory (not part of this repo)

```
my-standard/
  fs-org-std.toml        # your populated standard
  rules.own/              # your own rules
    my-rule-v1/
      rule.toml
      my-rule-v1-check.py
  rules.external/           # third-party, unverified - opt-in only, never merged in by default
    someone-elses-rule-v1/
      rule.toml
      someone-elses-rule-v1-check.py
```

Two flat, equally-explicit siblings, not one implicit default plus a
nested special case - a downloaded rule dropped straight into
`rules.own/` by mistake was a real gap in an earlier version of this
layout, and structural clarity was worth more here than a shorter path.

`rules.own/` is found as the sibling of whichever `fs-org-std.toml` is being
checked - no configuration needed for the common case. The file itself
can be named anything; nothing in the tooling assumes the literal name
`fs-org-std.toml` (see [Naming](#naming-decisions)).

---

## The standard: `fs-org-std.toml`

Grammar lives in `fs-org-std.template.toml`. Top-level concepts:

| Table | What it is |
|---|---|
| `root` | the directory this standard governs |
| `meta` | `schema_version` / `standard_version`, each `major.minor`, plus their dates |
| `paths` | specific, individually documented locations, keyed by path relative to `root` (e.g. `"area/inv/"`) |
| `folders` | rules/definitions that apply *without* being tied to one cataloged path - blanket rules over every folder under root, and reserved folder-**name** patterns (e.g. `_archive`) independent of location |
| `tags` | metadata tagging paths/folders for organization and cross-cutting concerns |
| `abbreviations` | local shorthand definitions used throughout the standard |
| `enums` | one closed value set per grouping field, as `enums.<namespace>.<field>` |

### A path entry

```toml
[paths."area/inv/"]
purpose = "Inventory tracking"
notes = ""
use_for = ["owned item records"]
not_for = ["receipts"]
lifecycle = "ongoing"
origin = ["self"]
see_also = ""
```

A path key is normally relative to `root`. One that resolves *outside*
it - `"/etc/nginx/"`, `"~/.config/"`, `"../sibling/"` - is legal only on
an entry that says so:

```toml
[paths."~/.config/"]
outside_root = true
purpose = "Application config that lives outside the governed tree"
```

Without the flag it's a validation error. The flag exists because the
escape used to be silent: joining an absolute key onto `root` *discards*
`root` entirely, so a stray leading slash would have quietly pointed
rules at a different tree. Unlike every other field, `outside_root` is
never inherited and never picks up a default - it has to be written on
the entry that escapes, the same way `reason` has to be written at every
rule attachment site.

An entry's fields come in three kinds, declared separately (see
[doc/DESIGN.md](doc/DESIGN.md)):

```toml
# free-form prose - a string or a list of strings, rendered as written
[paths.attributes]
names = ["purpose", "notes", "use_for", "not_for", "see_also"]
required = ["purpose"]

# enum-backed, checked against enums.paths.<field>, and used to group
# paths in the generated docs
[paths.grouping]
names = ["lifecycle", "origin"]
multi = ["origin"]          # origin holds several values; lifecycle one
required = ["lifecycle", "origin"]
```

- **documentation** fields are yours to name - nothing in the code knows
  what `purpose` means, and a standard can carry `owner` or
  `sensitivity` instead. The validator warns on any field the namespace
  never declared.
- **grouping** fields need a vocabulary under
  `enums.<namespace>.<field>`. The template ships `lifecycle`
  (`transient` · `temporary` · `ongoing` · `archival`) and `origin`
  (`self` · `external` · `generated`).
- **control** fields - `allow_missing` and `outside_root` - are the
  tool's own, always allowed on a path entry and never declared in
  either list.

`folders` declares its own two lists and its own vocabularies under
`enums.folders.*`, so reserved folder names can carry a different set of
fields from paths.

### Value format conventions

For rule params that take a duration or a size:

```
duration:  3d (days)   5w (weeks)   2m (months)
size:      500MiB   10GiB   1TiB           (binary units)
```

### Attaching a rule

```toml
[[paths."area/inv/".rules.file-extensions-v1]]
reason = "keep inventory scans to actual images"

[paths."area/inv/".rules.file-extensions-v1.params]
allowed = ["jpg", "png", "pdf"]
```

`reason` is required at every attachment site - hardcoded in the
validator, not a field read from the standard - and has no default.
It's the one thing that must be supplied fresh each time, unlike a
rule's own attributes, which live once in its manifest. Any param
without a default in the rule's own manifest must also be supplied
here.

Rules can attach to a single path, blanket-attach to every path or
every folder (`[[paths.rules.*]]` / `[[folders.rules.*]]`), or - for a
rule whose manifest declares `scope = "cross"` or `"both"` - attach to
a **cross-path set**:

```toml
[[paths.cross]]
paths = ["area/a/", "area/b/"]   # any path set - need not be individually cataloged

[[paths.cross.rules.some-cross-scope-rule-v1]]
reason = "..."
```

### Versioning

`schema_version` tracks this file's *structure* (the grammar);
`standard_version` tracks the *content* - your actual paths and
choices. Both `major.minor`. Their major versions must match each
other; a validator only understands a specific major and refuses to
guess past one it doesn't recognize, rather than produce a flood of
misleading errors against an incompatible grammar.

---

## Rules

A rule is a directory - a manifest and one or two scripts - that checks
(and optionally fixes) one specific thing. Rules are versioned
independently of the standard itself, live in one of three trust tiers
(bundled / your own / external), and communicate with the runner as
plain subprocesses over a small JSON-based protocol.

**For the full guide to writing a rule** - the manifest schema, the
runner↔script protocol, trust tiers, testing your rule standalone, and
a complete worked example - see **[doc/RULES.md](doc/RULES.md)**.

### Rules run sandboxed

Every rule script runs inside an audit-hook harness
(`fs_org_kit/sandbox.py`) that blocks network access, starting other
processes, native/ctypes calls, and writes outside what that invocation
is entitled to touch:

|  | writable |
|---|---|
| a **checker** | its own cache directory, the system temp directory |
| a **fixer** | those, plus `root` and the invocation's own target path(s) |

So "checkers never write" - a documented convention with nothing
enforcing it until now - is enforced, and a fixer pointed at one folder
can't rewrite another.

A rule that genuinely needs more declares it, the same way `uses_cache`
declares a need for storage:

```toml
[sandbox]
subprocess = true      # e.g. basename-sync-v1 delegates to a user script
```

Valid capabilities: `network`, `subprocess`, `native`,
`unrestricted_writes`. The runner reads the declaration and never
special-cases a rule by name. `fs-org-run --no-sandbox` turns the whole
thing off.

**This is a guard against accidents, not a security boundary.** It lives
inside the interpreter it polices, so `ctypes` reaches straight past it,
and nothing here constrains a rule that was malicious rather than
careless. Real isolation means the OS (bubblewrap, Landlock, Seatbelt)
and is out of scope - see [doc/DESIGN.md](doc/DESIGN.md).

### Rules that cache, and uninstalling

Most rules are stateless. A few keep a cache between runs so they don't
redo expensive work - currently only `duplicate-files-v1`, which stores
file hashes so unchanged files aren't re-read every time.

**A rule does not choose where that lives.** It declares
`uses_cache = true` in its manifest, and the runner hands it a
ready-made, rule-private directory. The core owns the location, so it
keeps an inventory of what exists and stays able to manage it:

```bash
fs-org-cache --list                        # what's cached, and how big
fs-org-cache --clear duplicate-files-v1    # one rule
fs-org-cache --clear                       # everything
fs-org-cache --path                        # where the root is
```

The root is your platform's cache directory - never your config
directory, never inside the tree being scanned:

```
$XDG_CACHE_HOME/fs-org-kit/     # Linux/BSD, or ~/.cache/fs-org-kit/
~/Library/Caches/fs-org-kit/    # macOS
%LOCALAPPDATA%\fs-org-kit\      # Windows
      └── rules/<rule-id>/      # one private subdirectory per rule
```

Set `$FS_ORG_KIT_CACHE_DIR` to override it.

**`pip uninstall fs-org-kit` does not remove this directory.** pip only
deletes the files it installed and has no post-uninstall hook, so any
cache is left behind. Clear it *before* uninstalling with
`fs-org-cache --clear`, or afterwards with:

```bash
rm -rf "${XDG_CACHE_HOME:-$HOME/.cache}/fs-org-kit"
```

Either is safe at any time, uninstalling or not: everything in there is
regenerable, so the worst case is one slower run afterwards, never a
wrong result.

---

## Tooling

### `fs_org_kit.validator`

Validates a populated standard against the schema template.

- Every issue is tagged **validation** (schema/structural correctness) or **lint** (style/convention). Both run by default; `--validate-only` / `--lint-only` narrow to one.
- `--only <category>` scopes a run to specific parts of the file (`paths`, `paths.rules`, `paths.cross`, `folders`, `folders.rules`, `meta`).
- `--ignore-warning <code>` silences specific warning types; `--list-warnings` shows all codes.
- `--include-external` / `--rules-dir` control rule discovery (same as the runner).
- Compiler-style output (`file:line: [LEVEL] location: message`) with best-effort line resolution.
- A summary table of component statuses (ok / warnings / broken).
- `--strict` (warnings fail the run too), `--no-color`, `--no-warnings`.

### `fs_org_kit.runner`

Validates first, then resolves every rule attachment into an invocation and runs it.

- Reuses the validator's rule catalog (no redundant discovery).
- `--fix` invokes a rule's `-fix.py` directly where one exists; rules without a fixer still run their checker.
- Handles per-path, blanket (`paths.rules`), cross-path (`paths.cross`), and folder (`folders.rules`) attachments. The rule's own params control behavior (recursion, exclusion, etc.).
- Only non-`ok` results are printed; the summary counts everything.
- `--include-external`, `--rules-dir`, `--no-color` mirror the validator's flags.
- `--no-sandbox` runs scripts directly, without the audit-hook harness; `--timeout` raises the per-invocation limit.
- Exit codes: 0 (clean), 1 (violations/broken), 2 (invalid standard).

---
