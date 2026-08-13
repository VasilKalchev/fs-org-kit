# fs-org-kit

A standard for how your files should be organized, made machine-enforceable.

You write down how your home directory (or any directory tree) *should*
be organized - as data, in TOML, not as a wiki page you'll stop
maintaining - and a set of small scripts check whether it actually is,
and where possible, fix it.

---

## The core idea

The standard and the rules that check it change at different rates:

- **The standard** - one TOML file, `fs-org-std.toml`, that *you* fill
  in. It describes your directories: what each one is for, its
  lifecycle, where its content came from, and which rules apply to it.
  This changes constantly, in small ways, as you organize more of your
  life.
- **Rules** - small, independently versioned units (a manifest plus one
  or two scripts) that know how to *check* (and sometimes *fix*) one
  specific thing - a naming convention, a staleness policy, a size
  limit. These change rarely once written, and are shared: yours, the
  project's, or someone else's.

Keeping these separate (they used to be one file - see
[doc/DESIGN.md](doc/DESIGN.md)) is what lets rules be authored,
shared, and versioned independently of any one person's standard.

---

## Installation

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

A virtualenv isn't required, but the runner invokes every rule script
with the same interpreter it's running under (`sys.executable`), so
whatever environment you install into is also where a rule's
dependencies need to be installed - a venv keeps that separate from
your system Python and other projects'.

`pip install -e ".[dev]"` installs the core package and pytest; that's
all that's needed to run the bundled rules, which are stdlib-only with
one exception. A rule that needs a third-party package (like
`spelling-abbreviations-v1`, which needs `pyspellchecker`) documents
that requirement in its own manifest - install it the same way, into
the same environment, only if you attach that rule. See
[doc/RULES.md](doc/RULES.md)'s "dependency isolation" for why this is
per-rule rather than something `pip install fs-org-kit` pulls in for
you (`rules.own/` and `rules.external/` aren't even known at that
point).

## Repository layout

```
fs-org-kit/                        (this repo - the tool, not your data)
  pyproject.toml                   # package declaration
  fs-org-std.template.toml         # grammar for a populated fs-org-std.toml
  rules/                           # bundled, project-maintained rules
    file-extensions-v1/
      file-extensions-v1.toml
      file-extensions-v1-check.py
    _template-single-v1/           # copyable starting points, one per
    _template-cross-v1/            # scope; the "_" keeps them out of
    _template-both-v1/             # the catalog
  fs_org_kit/                      # the Python package
    __init__.py
    cache.py                       # where rules keep state between runs
    discovery.py                   # rule discovery - shared by all tools
    doc.py                         # generates Markdown documentation
    fields.py                      # what a namespace declares its entries carry
    inherit.py                     # resolves `inherit` across entries
    param_refs.py                  # {ref = "dotted.path"} param values
    path_keys.py                   # what real location a path key names
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
    BACKLOG.md
    CHANGELOG.md
    DESIGN.md
    RULES.md
    TESTING.md
    VALIDATOR_SPEC.md
    VERSIONING.md
  README.md
  CLAUDE.md
```

The fastest way in is [`examples/para/`](examples/para/) - a toy PARA
tree with three deliberate mistakes in it, a standard that catches them,
and a tutorial that walks from `fs-org-validate` to `--fix`.

Short commands, once installed:

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
nested special case (see [doc/DESIGN.md](doc/DESIGN.md)).

`rules.own/` is found as the sibling of whichever `fs-org-std.toml` is being
checked - no configuration needed for the common case. The file itself
can be named anything; nothing in the tooling assumes the literal name
`fs-org-std.toml`.

---

## The standard: `fs-org-std.toml`

Grammar lives in `fs-org-std.template.toml`. Top-level concepts:

| Table | What it is |
|---|---|
| `root` | the directory this standard governs |
| `meta` | `schema_version` / `standard_version` - see [doc/VERSIONING.md](doc/VERSIONING.md) for how the two relate (or deliberately don't) |
| `paths` | specific, individually documented locations, keyed by path relative to `root` (e.g. `"area/inv/"`) |
| `folders` | rules/definitions that apply *without* being tied to one cataloged path - blanket rules over every folder under root, and reserved folder-**name** patterns (e.g. `_archive`) independent of location |
| `tags` | closed vocabularies for metadata carried by things *on disk* (e.g. an archived project's state) |
| `abbreviations` | local shorthand definitions used throughout the standard |
| `enums` | closed value sets for fields that need one |

### A path entry

An entry is its attributes, plus two tables - free-form documentation
fields and enum-backed grouping fields, each declared by the namespace
itself rather than hardcoded (see [doc/DESIGN.md](doc/DESIGN.md)):

```toml
[paths."area/inv/"]                  # prose, for the generated docs
purpose = "Inventory tracking"
use_for = ["owned item records"]
not_for = ["receipts"]

[paths."area/inv/".group]            # enum-backed, for grouping
lifecycle = "ongoing"
origin = ["self"]

[[paths."area/inv/".rules.file-extensions-v1]]
reason = "keep inventory scans to actual images"
```

A path key is normally relative to `root`, but doesn't have to be:
`"/etc/nginx/"`, `"~/.config/"` and `"../sibling/"` each name exactly
where they say, and rules attached to them run there. A cataloged path
that isn't on disk right now is simply skipped.

Attaching a rule always requires a `reason`, supplied fresh at each
attachment site rather than inherited from the rule itself - see
[doc/RULES.md](doc/RULES.md) for the full attachment grammar, including
blanket and cross-path attachments.

---

## Rules

A rule is a directory - a manifest and one or two scripts - that checks
(and optionally fixes) one specific thing, versioned independently of
the standard itself. This repo ships twenty bundled rules; rules live
in one of three trust tiers (bundled / your own / external) and
communicate with the runner as plain subprocesses over a small
JSON-based protocol.

Every rule script runs inside a sandbox that blocks network access,
starting other processes, and writes outside what that invocation is
entitled to touch - a guard against accidents, not a security boundary.
A few rules keep a cache between runs; the core owns where that lives,
not the rule, so it stays inventoried and clearable in one place
(`fs-org-cache --list` / `--clear [rule-id]`) - which matters since
`pip uninstall` won't clean it up on its own.

**For the full guide to writing a rule** - the manifest schema, the
runner↔script protocol, the sandbox, caching, trust tiers, testing your
rule standalone, and a complete worked example - see
**[doc/RULES.md](doc/RULES.md)**.

---

## Tooling

Four commands, installed by `pip install -e .` (or run directly via
`python -m fs_org_kit.<module>`):

- **`fs-org-validate`** - checks a standard against the schema and its own lint rules.
- **`fs-org-run`** - resolves every rule attachment and runs it against the real filesystem; `--fix` invokes a rule's fixer where one exists.
- **`fs-org-doc`** - generates Markdown documentation from the resolved standard.
- **`fs-org-cache`** - manages the on-disk cache a few rules keep between runs.

Each supports `--help` for its full flag list.

---
