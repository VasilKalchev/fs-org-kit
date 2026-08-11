---
name: new-rule
description: Author a new fs-org-kit rule end to end - scaffold the directory, implement the checker (and optional fixer) against the subprocess protocol, write its tests, and update the docs. Use when adding a bundled rule under rules/, or a user rule under rules.own/ or rules.external/.
---

# Writing a new rule

Full reference: `doc/RULES.md`. This is the procedure and the parts that
are easy to get wrong.

## 1. Decide four things first

| | |
|---|---|
| **scope** | `single` (one `--path`) · `cross` (2+ `--paths`) · `both` (either; the script validates which it got) |
| **severity** | `none` · `info` · `warn` · `error` |
| **params** | Every value the script reads. Anything that can't have a sensible default must be **left out** of `params.defaults`, which is what forces every attachment site to supply it. |
| **fixer?** | Only if automating the fix is genuinely safe. Check-only is a permanent, normal design, not a stub. If which item to change is a policy call, either skip the fixer or delegate to a user-supplied `fixer_script` the way `basename-sync-v1` does. |

## 2. Scaffold

```bash
python .claude/skills/new-rule/scaffold_rule.py <name>-v1 \
    --purpose "One sentence, shown in generated docs." \
    --scope single --severity warn \
    --params first,second [--fixer] [--cache] [--dir rules]
```

Writes the manifest, a runnable checker, and a test file, all named after
the directory. Generated rules discover cleanly and pass their tests
immediately, so anything that breaks afterwards is your change.

## 3. Implement the checker

The scaffold already has the protocol right. What matters as you fill it in:

- **One JSON line on stdout, nothing else.** `{"status": "ok"}` or
  `{"status": "violation", "message": "..."}`. A stray `print` corrupts
  the verdict.
- **Exit 0 means "I ran"** — the verdict is in stdout. Nonzero means the
  *script* is broken (bad params, missing path); reason on stderr, which
  the runner reports as `broken`. Finding a violation is never nonzero.
- **A checker never writes.** This is enforced: `fs_org_kit/sandbox.py`
  gives a checker no writable location beyond its cache and temp, and a
  fixer only root plus its own targets. A rule needing more declares it
  in `[sandbox]` (`network`, `subprocess`, `native`,
  `unrestricted_writes`) with a comment saying why — never work around
  it in the runner. Note that standalone runs are **not** sandboxed, so
  a rule can pass its own tests and still fail under `fs-org-run`;
  exercise a fixer through the runner at least once.
- **You only get locations and params** — never `purpose`, `lifecycle`,
  `origin`. Behavior that varies per attachment must be a declared param.
- **Stdlib by default.** Third-party dependencies are allowed (the
  subprocess boundary isolates them) but they become the user's problem;
  a non-pip-installable one is usually disqualifying.
- **`--fix` is rejected defensively**, even though the runner shouldn't
  send it. Turns a runner bug into a loud failure.

A fixer is **self-contained** — it detects *and* resolves in one pass. The
runner calls `-fix.py` directly, never check-then-fix. Its four statuses
are `ok` / `violation` (found, couldn't act) / `fixed` / `unfixable`.

With `--cache`: the runner passes `--cache-dir`. Never resolve a location
yourself, work correctly when the flag is absent (standalone runs, an
unusable location) by not caching, and keep everything in there
regenerable.

## 4. Tests

They live in the rule's own directory, not `tests/`, so they travel with
the rule when it's copied elsewhere. Invoke scripts via `subprocess`,
exactly as the runner does — never import their internals; the subprocess
call *is* the contract.

Cover the core behavior, each param, and the argument errors the script
raises itself (for `scope = "both"`: `--path` and `--paths` together,
`--paths` with one value).

```bash
pytest rules/<name>-v1/ -v
```

## 5. Update the docs, then let the tests check you

- `doc/TESTING.md` — add a bullet under "Bundled rule tests" as
  ``**`rules/<name>-v1/test_<name>_v1.py`** (N tests): ...`` and correct
  the section's total
- `README.md` — the bundled rule count, in words
- `doc/CHANGELOG.md` — a short entry; rationale goes in `doc/DESIGN.md`,
  not here

```bash
pytest                            # everything
pytest tests/test_docs_current.py # counts, inventories, links
```

`test_docs_current.py` enforces most of step 5 — including that the rule
has tests at all. If it passes, the bookkeeping is right.

Keep documentation concise: state the decision and its constraint, then
stop.
