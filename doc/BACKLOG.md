# Backlog

Things worth doing that aren't done yet - somewhere between an idea and
a to-do, split by how soon each is actually worth picking up.

---

## Next

Ready to implement whenever someone sits down to it: scoped, no open
design questions, no dependency on anything that hasn't happened yet.

### `purpose` → generated docs

Every bundled rule manifest already carries a one-sentence `purpose`
(`doc/RULES.md`'s field table: "shown in generated documentation").
`doc.py` never reads it. Add it to the per-namespace rule-attachment
rendering — next to each rule ID and its `reason`, the way `reason`
already renders, so a generated doc explains both *why* a rule is
attached (`reason`, per-attachment) and *what it checks*
(`purpose`, per-rule).

### `severity`-aware reporting

`severity` is enum-checked at discovery time but never leaves
`RuleEntry` — the runner's report tracks only protocol *status*
(`ok` / `violation` / `fixed` / `unfixable` / `broken` / `skipped`), so
an `info`-severity and an `error`-severity violation print identically.
Needs: `RunResult` (or `_print_result`/`summarize` in `runner.py`) to
carry the attached rule's `severity` through and use it for
label/color, and a decision on whether `none`-severity should suppress
the line entirely (per its stated meaning: "deliberately silenced -
never reported, regardless of any default") or just skip coloring.

---

## Someday

No committed design, and not worth one yet - either speculative or
waiting on something that hasn't happened. Recorded so they're not
re-discovered from scratch later, not planned around.

### Migrator scripts for schema major bumps

A schema major bump (`SUPPORTED_SCHEMA_MAJOR`) requires every existing
standard to be manually rewritten before the new tool version will
touch it. A per-major-bump migrator script (old-grammar TOML in,
new-grammar TOML out) would turn that into a one-command upgrade
instead of a manual rewrite against the changelog. Only worth building
once a real major bump happens and its actual grammar delta is known -
waiting on that, not on design work.

---

Within a section, order is not priority order. Each item is
independent and can be picked up on its own.
