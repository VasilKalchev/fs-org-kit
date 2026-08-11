# Writing Rules

A guide and technical reference for anyone writing a rule for fs-org-kit -
whether for your own `rules.own/`, to share as `rules.external/`, or to
contribute a bundled rule to this repo.

If you just want to see a complete, working example, skip to
[Worked example: `file-extensions-v1`](#worked-example-file-extensions-v1).

---

## What a rule is

A rule is a directory containing a manifest and one or two scripts:

```
<rule-name>-v<major>/
  <rule-name>-v<major>.toml         # the manifest - REQUIRED
  <rule-name>-v<major>-check.py     # the checker - REQUIRED
  <rule-name>-v<major>-fix.py       # the fixer - OPTIONAL
```

All three files repeat the full directory name. This isn't decoration -
`file-extensions-v1-check.py` identifies itself correctly even opened in
isolation (an editor tab, a stack trace, a code review diff), without
needing its parent folder for context.

Checking and fixing are **always separate files**, never one script that
branches on a flag. This means:

- Whether a rule can *mutate* anything is visible on the filesystem
  itself - `-fix.py` exists, or it doesn't - not something you have to
  read code to find out
- A rule's checker can be run and trusted even in contexts where its
  fixer isn't (or doesn't exist at all)
- The runner never has to guess intent from a flag; file existence is
  the whole signal

---

## Where your rule lives

| Location | Merged automatically? | Notes |
|---|---|---|
| `rules/` (inside fs-org-kit itself) | Yes | Bundled, project-maintained. You'd only touch this if contributing to fs-org-kit directly. |
| `rules.own/` (sibling of your `fs-org-std.toml`) | Yes | Your own rules. This is almost certainly where you're writing. |
| `rules.external/` (sibling of your `fs-org-std.toml`) | **No** - requires `--include-external` | Third-party, unverified rules. Never loaded silently. |

**Rule identity is per directory name, globally**, not per tier. A rule
named `size-limit-v1` in `rules.own/` and one named `size-limit-v1` in
the bundled tier are the *same identity* as far as discovery is
concerned, and only one wins - see [Overriding a bundled
rule](#overriding-a-bundled-rule) below.

---

## Naming: the `-v<major>` suffix is part of the rule's identity

`name-regex-v1/` and `name-regex-v2/` are two independent, coexisting
catalog entries - **not** two revisions of the same rule. Directory name
must match `^<name>-v<digits>$` exactly, checked by discovery; a
directory that doesn't match this pattern is skipped with a warning and
never loaded.

- **Breaking change** to params or behavior → new `-v<major>` directory.
  The old one keeps working for anyone still attached to it.
- **Non-breaking refinement** (smarter pattern, bug fix, better error
  message) → bump `version`'s *minor* number in place, same directory.

The manifest's `version` field major **must match** the directory
suffix - `version = "2.0"` inside a directory named `my-rule-v1/` is a
discovery error, not a warning. This is checked, not just convention.

---

## The manifest: `<rule-name>.toml`

```toml
version = "1.0"
purpose = "One sentence: what does this rule check, for humans reading generated docs."
severity = "warn"           # none | info | warn | error
scope = "single"            # single | cross | both
protocol_version = "1.0"    # which runner<->script wire format this speaks
overrides_bundled = false   # only meaningful in rules.own/, see below

[params]
names = ["allowed", "recursive"]

[params.defaults]
allowed = []
recursive = true
```

### Field reference

| Field | Required | Meaning |
|---|---|---|
| `version` | yes, checked | `"<major>.<minor>"`. Major **must** match the directory's `-v<major>` suffix, or discovery rejects the rule. |
| `purpose` | strongly recommended, not enforced | One sentence, shown in generated documentation. Nothing currently rejects a rule for leaving this empty - but an undocumented rule is a rule nobody else can safely attach. |
| `severity` | no (defaults `"info"`), checked | How loud a violation is reported. Must be a valid value or discovery rejects the rule - see [enums](#enums-severity-and-scope) below. |
| `scope` | no (defaults `"single"`), checked | Where this rule may be attached. Must be a valid value or discovery rejects the rule - see [enums](#enums-severity-and-scope) below. |
| `protocol_version` | no (defaults `"1.0"`) | Which version of the runner↔script wire format `-check.py`/`-fix.py` speak. Independent of `version` - see [below](#protocol_version-vs-version). |
| `overrides_bundled` | no (defaults `false`) | Only meaningful for a rule in `rules.own/`. See [Overriding a bundled rule](#overriding-a-bundled-rule). |
| `uses_cache` | no (defaults `false`) | `true` if your rule keeps state between runs. The runner then passes `--cache-dir <path>`. See [Rules that cache](#rules-that-cache). |
| `sandbox` | no, no default | Table granting capabilities the harness otherwise blocks. See [The sandbox](#the-sandbox). |
| `exclude` | no, no default | List of glob strings this rule never applies to. Omitting it means "no exclusions" - a default value here would erase that distinction, so there isn't one. |
| `params.names` | yes | Every parameter your checker/fixer accepts. |
| `params.defaults` | no | Defaults for some or all of those params. Any param **not** listed here has no default and **must** be supplied at every attachment site in the standard, or validation fails. |

### Enums: `severity` and `scope`

```
severity:
  none  - deliberately silenced, never reported regardless of any default
  info  - worth noting, no action expected
  warn  - should be addressed, but nothing is broken yet
  error - the standard is actively violated and needs correction

scope:
  single - invoked once per path, takes --path, exactly one location
  cross  - invoked once per cross-path set, takes --paths, 2+ locations
  both   - attachable either way; the script itself must accept both
           flags and validate them (error if both given, or if --paths
           has fewer than 2 values)
```

These are read live from `rule.template.toml`, not hardcoded anywhere -
if that file's enums ever change, your manifest is checked against the
current values automatically.

### `protocol_version` vs `version`

Two independent axes, easy to conflate:

- **`version`** is about *this rule's own params and behavior*. Bump it
  when you change what the rule checks or how.
- **`protocol_version`** is about the *wire format every rule shares* -
  how the runner invokes any script, regardless of which rule it is.
  Bump it only when the calling convention itself changes.

You will almost never touch `protocol_version` by hand. Leave it at
`"1.0"` unless you're deliberately building against a newer protocol
that doesn't exist yet.

### Overriding a bundled rule

A rule in `rules.own/` with the **identical directory name** as a
bundled rule can replace it, but only with explicit opt-in:

```toml
overrides_bundled = true
```

Without this flag, a same-named collision is a warning at discovery
time, and the bundled version stays authoritative - your rule simply
doesn't load until you rename it or set the flag.

A rule in `rules.external/` claiming `overrides_bundled = true` has
that claim **ignored, always**, and flagged as suspicious. An
unverified rule must never be able to hijack a trusted rule's identity
just by reusing its name.

---

## The checker script

### What gets invoked, and how

The runner invokes your script as a **plain subprocess** - not imported,
not run inside the runner's own process. This buys three things:

1. **Crash isolation** - one hung or crashing rule can't take down a run
   of twenty others
2. **Dependency isolation** - your rule can use whatever third-party
   packages it wants without conflicting with anyone else's
3. **The lowest possible bar to test** - you can run and debug your
   script directly on the command line, no framework, no fixtures, no
   test harness required

### Arguments your script receives

```
scope = single -> --path <one resolved absolute path>
scope = cross   -> --paths <path> [--paths <path> ...]   (2 or more)
scope = both    -> your script MUST accept both --path and --paths,
                    and must itself error if both are given, or if
                    --paths has fewer than 2 values
always:            --params '<json object>'
uses_cache = true -> --cache-dir <an existing, rule-private directory>
                    (only for rules that declare it; may be absent)
```

You receive **only a location (or locations) and params** - never
`purpose`, `notes`, `lifecycle`, `origin`, or anything else from the
standard. Those fields exist for humans reading generated
documentation, not for your script to branch on. If your rule's
behavior genuinely needs to vary per attachment, that variation belongs
in `params`, declared in your manifest, supplied at the attachment
site.

A param value in the standard can be `{ref = "dotted.path"}` instead of
a literal - resolved, before your script ever runs, to the table's keys
or the list found at that path elsewhere in the standard (see
`fs_org_kit.param_refs`). This is what lets a param like
`spelling-abbreviations-v1`'s `abbreviations` point at `[abbreviations]`
itself instead of the standard's author retyping that list by hand at
every attachment site. It's resolved by the runner/validator, not by
your script - your script still only ever sees a plain JSON value, same
as any other param.

### What your script must print

Exactly **one JSON line on stdout**, nothing else:

```json
{"status": "ok"}
{"status": "violation", "message": "human-readable description"}
```

A checker only ever produces `ok` or `violation` - it never fixes
anything, so `fixed`/`unfixable` don't apply to it (those are for
fixers, below).

### Exit codes

- **`0`** - the script ran successfully. The runner reads stdout for
  the verdict (`ok` or `violation`).
- **Nonzero** - the script itself is broken: bad params, a path that
  doesn't exist, an internal bug. This is **not** the same thing as
  finding a violation - it means the check couldn't even run. Put the
  reason on **stderr**; the runner surfaces it as a `broken` result.

### A checker never writes

A checker must never modify the filesystem. If a rule can fix
something, that logic belongs in a separate `-fix.py`, invoked only in
`--fix` mode.

This is now enforced, not just asked for: the runner gives a checker no
writable location beyond its own cache and the system temp directory,
so a stray write fails the invocation rather than quietly happening.
See [The sandbox](#the-sandbox).

### The sandbox

Every invocation runs inside an audit-hook harness
(`fs_org_kit/sandbox.py`) that blocks network access, starting other
processes, native/ctypes calls, and writes outside what that invocation
may touch:

| | writable |
|---|---|
| a **checker** | its own cache directory, the system temp directory |
| a **fixer** | those, plus `root` and the invocation's own target path(s) |

Most rules never notice. If yours genuinely needs more, declare it -
the same shape as `uses_cache`, and for the same reason: the core reads
a declaration rather than special-casing your rule by name.

```toml
[sandbox]
subprocess = true
```

| capability | grants |
|---|---|
| `network` | opening connections, resolving hostnames |
| `subprocess` | starting other processes - note this also ends the harness's reach, since the child isn't policed |
| `native` | `ctypes` calls, which can bypass the harness entirely |
| `unrestricted_writes` | writing anywhere you can - for a fixer whose destination the core can't know in advance |

Only `true` grants; `false` and omission are both denials, so you can
spell out a denial for a reader without changing behavior. A key that
isn't one of the four is a typo, and discovery warns about it rather
than silently granting nothing.

**Say why in a comment.** A reviewer reads this table before trusting
your rule, and `unrestricted_writes = true` with no explanation is
indistinguishable from carelessness. Only two rules in this repo declare
anything at all, and both are worth reading as examples:
`basename-sync-v1` delegates every file operation to a user-provided
script, and `collect-v1`'s destination comes from the standard, so the
core can't know it ahead of time.

Two things worth knowing while developing:

- Running your script **standalone on the CLI is never sandboxed** - the
  harness is something the runner wraps around it. So a rule can pass
  its own tests and still fail under `fs-org-run`. If that happens, the
  stderr message names the exact operation and lists what was writable.
- **This is a guard against accidents, not a security boundary.** It
  lives inside the interpreter it polices. Don't design a rule around it
  holding against anything deliberate.

`fs-org-run --no-sandbox` turns it off entirely.

### Rules that cache

Most rules are stateless: read the filesystem, decide, exit. If yours
needs to remember something between runs so it doesn't redo expensive
work, declare it in your manifest:

```toml
uses_cache = true
```

The runner then creates a directory that belongs to your rule alone and
passes it as `--cache-dir`. Put whatever you like inside it - a SQLite
database, JSON, whatever fits.

**You do not choose where it goes, and you must not resolve a location
yourself.** The core owns the location (`fs_org_kit/cache.py`), for
three reasons: it keeps an inventory of every cache that exists, so it
can report on them and clear them (`fs-org-cache --list`,
`fs-org-cache --clear <rule-id>`); the per-platform path logic lives in
exactly one place rather than being copied into every caching rule,
free to drift; and a user who wants their disk back has one command
that works for every rule, present and future, instead of needing to
know what each one does.

Two obligations come with the flag:

1. **Work correctly without it.** `--cache-dir` is absent when your
   script is run standalone on the command line, and when the core
   couldn't create the directory (read-only or full filesystem). Both
   mean "run uncached" - slower, never wrong, and never a fallback
   location of your own choosing.
2. **Treat the cache as disposable.** Anything in there must be
   regenerable. A user can delete it at any moment, and the TTL sweep
   in your own code may drop entries; neither may change a verdict.
   Cache what's expensive to recompute, never the only copy of
   something.

A rule that leaves `uses_cache` at its `false` default never receives
the flag at all - which is why adding this didn't break any existing
rule's argument parsing.

`duplicate-files-v1` is the worked example: it caches file hashes keyed
by path + algorithm, reuses one only while the file's size *and* mtime
both match, and sweeps entries not seen for `cache_ttl_days`.

### Minimal skeleton

```python
#!/usr/bin/env python3
import argparse, json, sys
from pathlib import Path

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {e}", file=sys.stderr)
        return 1

    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1

    # ... your actual check goes here ...
    violation_found = False

    if violation_found:
        print(json.dumps({"status": "violation", "message": "explain what and where"}))
    else:
        print(json.dumps({"status": "ok"}))
    return 0

if __name__ == "__main__":
    sys.exit(main())
```

---

## The fixer script (optional)

### When to write one

Only if the fix is genuinely safe to automate. Renaming, deleting, or
moving files is often a decision a human should make - if you're
unsure, don't write a fixer. A check-only rule (see
`file-extensions-v1` below) is a completely normal, permanent design
choice, not a stub waiting to be finished.

### How it's invoked, and what makes it different from a checker

A fixer is **self-contained**: it detects the problem *and* resolves it
in one pass, not "check first, then get told to fix." The runner does
not run your checker before your fixer in `--fix` mode - it invokes
`-fix.py` directly whenever it exists and `--fix` was passed.

Arguments are identical to a checker's (`--path`/`--paths`, `--params`),
with `--fix` added. Your fixer's stdout must be exactly one JSON line,
using whichever of the four statuses actually happened:

```json
{"status": "ok"}          - nothing needed fixing
{"status": "violation", "message": "..."}  - found a problem, could not act on it
{"status": "fixed", "message": "..."}      - found a problem and resolved it
{"status": "unfixable", "message": "..."}  - found a problem this rule can never auto-resolve
```

Exit codes follow the same convention as a checker: `0` = ran fine,
read stdout; nonzero = the fixer itself is broken, reason on stderr.

### If a rule has no fixer

Rules without a fixer are invoked normally (as checkers) even when the
runner is run with `--fix` - fix mode doesn't skip rules that can't be
fixed, it just can't fix them. Nothing extra to do on your end; just
don't create the `-fix.py` file.

---

## Testing your rule before attaching it anywhere

Because a rule is a standalone script, you don't need a standard, the
validator, or the runner to test it - invoke it directly:

```bash
python rules.own/my-rule-v1/my-rule-v1-check.py \
    --path /tmp/some/real/directory \
    --params '{"allowed": ["jpg", "png"]}'
```

Check the output is exactly one JSON line, and that the exit code is
`0`. Once that works standalone, attach it in your `fs-org-std.toml` and
run `fs-org-validate` first (catches manifest problems, unknown params,
scope mismatches) before `fs-org-run` (actually invokes it for real).

### Formal tests (optional, but recommended for anything non-trivial)

If you want proper `pytest`-based tests, not just manual spot-checks,
put them **inside your rule's own directory**, not anywhere in
fs-org-kit's own project structure - that structure only exists for
*this* repo's bundled rules, and a rule in `rules.own/` or
`rules.external/` has no access to it (nor should it need any):

```
my-rule-v1/
  my-rule-v1.toml
  my-rule-v1-check.py
  my-rule-v1-fix.py              # if present
  test_my_rule_v1.py             # underscores, not hyphens - it needs
                                  # to be a valid, importable Python
                                  # module name for pytest to collect it
```

This way your tests travel with the rule wherever it goes - copied into
someone else's `rules.own/`, published as `rules.external/`, or
contributed back as a bundled rule - without needing to touch anyone
else's test suite. Run them from inside the rule's own directory:

```bash
pytest test_my_rule_v1.py -v
```

Invoke your rule's scripts via `subprocess`, exactly as the runner
does, rather than importing their internals - that's the real,
documented contract every rule is written against, and testing through
it catches anything an internals-only test would miss. See
`rules/file-extensions-v1/test_file_extensions_v1.py` and
`rules/basename-sync-v1/test_basename_sync_v1.py` in this repo for
complete, self-contained (no imports outside the standard library)
worked examples you can copy as a starting point.

---

## Language policy: Python only

No compiled languages - a rule runs with your real filesystem
permissions, and the source has to stay readable for anyone to review
before running it. No bash either, despite also being readable: it
isn't available uniformly (no native Windows support), and nothing in
this domain - pattern matching, mtime/size checks, moving files - needs
anything Python's standard library doesn't already cover. One runtime,
one calling convention, one thing a contributor needs installed.

---

## Worked example: `file-extensions-v1`

A complete, real, bundled rule - single-scope, check-only, no fixer.

**Manifest** (`file-extensions-v1.toml`):

```toml
version = "1.0"
purpose = "Checks that every file under the path has an allowed extension, or does not have a disallowed one - exactly one of the two lists is used per attachment."
severity = "warn"
scope = "single"
protocol_version = "1.0"
# No fixer: whether a misplaced file should be deleted, renamed, or moved
# is a human decision, not safe to automate.

[params]
names = ["allowed", "disallowed", "recursive"]

[params.defaults]
allowed = []
disallowed = []
recursive = true
# Both allowed/disallowed default to [] so params.defaults doesn't force
# either as "required" - but the checker itself refuses to run unless
# exactly one is non-empty at call time. That's a runtime constraint the
# manifest can't express, so the script enforces it directly.
```

**Checker** (`file-extensions-v1-check.py`, abbreviated - see the real
file for the complete version):

```python
def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--path", required=True)
    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true")
    args = parser.parse_args()

    if args.fix:
        print("error: file-extensions-v1 has no fixer", file=sys.stderr)
        return 1

    params = json.loads(args.params)
    allowed = normalize(params.get("allowed", []))
    disallowed = normalize(params.get("disallowed", []))

    if bool(allowed) == bool(disallowed):
        print("error: exactly one of `allowed`/`disallowed` must be non-empty", file=sys.stderr)
        return 1

    # ... walk the directory, collect violations ...

    if not violations:
        print(json.dumps({"status": "ok"}))
    else:
        print(json.dumps({"status": "violation", "message": f"{len(violations)} file(s) with a disallowed extension: ..."}))
    return 0
```

**Attaching it in a standard**:

```toml
[[paths."media/img/".rules.file-extensions-v1]]
reason = "keep images to known formats only"

[paths."media/img/".rules.file-extensions-v1.params]
allowed = ["jpg", "png", "gif", "webp"]
```

Notice the `--fix` handling: even though this rule has no `-fix.py`,
the checker defensively rejects being called with `--fix` at all. The
runner should never do this (no fixer means it always invokes the
checker, `--fix` flag included only for actual fixer scripts) - but the
defensive check catches a runner bug early rather than silently doing
the wrong thing.

---

## Checklist before you attach a new rule

- [ ] Directory name matches `<rule-name>-v<major>` exactly (enforced)
- [ ] Manifest's `version` major matches the directory suffix (enforced)
- [ ] `purpose` is a real, non-empty sentence (not enforced, but do it anyway)
- [ ] `severity` and `scope` are valid values (enforced - see enums above)
- [ ] Every param your script reads is listed in `params.names`
- [ ] Params with no sensible default are **not** in `params.defaults` (so validation forces them to be supplied)
- [ ] Checker tested standalone, prints exactly one JSON line, exits 0 on success
- [ ] If you wrote a fixer: it's self-contained (detects *and* resolves), also prints exactly one JSON line
- [ ] If overriding a bundled rule: `overrides_bundled = true` is set
