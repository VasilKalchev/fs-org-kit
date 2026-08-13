# Roadmap

Small, concrete to-do list for manifest fields and design intent that
exist today but aren't acted on yet. Not a wishlist — each item already
has a stated purpose (see `doc/RULES.md` / `doc/DESIGN.md`); what's
missing is the code that reads the field.

A separate "Ideas" section below holds things with no committed design
yet - worth remembering, not worth planning around.

---

## `purpose` → generated docs

Every bundled rule manifest already carries a one-sentence `purpose`
(`doc/RULES.md`'s field table: "shown in generated documentation").
`doc.py` never reads it. Add it to the per-namespace rule-attachment
rendering — next to each rule ID and its `reason`, the way `reason`
already renders, so a generated doc explains both *why* a rule is
attached (`reason`, per-attachment) and *what it checks*
(`purpose`, per-rule).

## `severity`-aware reporting

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

## Ideas

Not scheduled, no design yet - recorded so they're not re-discovered
from scratch later.

### Migrator scripts for schema major bumps

A schema major bump (`SUPPORTED_SCHEMA_MAJOR`) requires every existing
standard to be manually rewritten before the new tool version will
touch it. A per-major-bump migrator script (old-grammar TOML in,
new-grammar TOML out) would turn that into a one-command upgrade
instead of a manual rewrite against the changelog. Only worth building
once a real major bump happens and its actual grammar delta is known.

---

Order above is not priority order. Each item is independent and can be
picked up on its own.
