# Versioning

Six independent version-shaped things exist in this project. None of them
share a number with any other by coincidence - where two are checked
against each other, it's because they're the same fact stated twice, never
because two different facts happen to co-occur. This document says what
each one means, why it's separate, and what happens when it changes.

## Quick reference

| Axis | Lives in | Format | Owned by | Support policy |
|---|---|---|---|---|
| Tool release | `pyproject.toml` `version` | semver | the project | ordinary package release |
| Schema version | `meta.schema_version` | `major.minor` | the project | one supported major at a time, hard stop otherwise |
| Standard version | `meta.standard_version` | free-form | you | none - entirely your own bookkeeping |
| Rule identity | `<rule>-v<major>/` directory | `major` | rule author | majors coexist forever, no migration forced |
| Rule revision | manifest `version` | `major.minor` | rule author | major must equal the directory suffix |
| Protocol version | manifest `protocol_version` | `major.minor` | the project | additive - the runner keeps every major it has ever supported |

---

## The tool's own version

`pyproject.toml`'s `version` is an ordinary package release number. It
moves on anything - a bug fix, a new bundled rule, an internal refactor -
and has no relationship to any axis below.

This project is normally installed editable (`pip install -e .`), so "which
tool version am I on" and "which code is actually running" are the same
thing - there's no deployment step where they could drift apart. That's
part of why none of the axes below need the tool's own version number to
reason about compatibility; each carries what it needs to know on itself
(see `schema_version` and `protocol_version` below).

## `schema_version` - the standard's grammar

The validator supports exactly **one** schema major at a time
(`SUPPORTED_SCHEMA_MAJOR` in `validator.py`). A standard whose major
doesn't match is a hard stop before any further check runs - one clear
error naming both versions, instead of a flood of misleading noise from
running the wrong grammar's checks.

This is deliberately **not** multi-version - no "supports current and
previous major" grace window. A standard is one file with one owner: if
you haven't migrated it past a major bump, you simply don't upgrade the
tool yet, and the old tool version keeps validating it exactly as it
always did, at zero ongoing cost to the project. Carrying two live
grammars in the validator permanently would be real, structural
complexity - paid on every release - for a benefit ("smoother transition")
a single-checkout personal tool doesn't need. (The rule population is
different - see `protocol_version` below, where that same reasoning
argues for the opposite policy.)

**What makes a schema change a minor vs. a major** is one mechanical test,
not a judgment call made fresh each time: *does this change invalidate or
reinterpret anything that was previously valid?*

- **Safe as a minor**: a wholly new, independent top-level construct (e.g.
  adding `[tags]`). Nothing before could reference it, so nothing gets
  reinterpreted - old and new validators simply differ in whether they
  understand the new block, and `param_refs.py`'s generic, name-agnostic
  `{ref = "..."}` resolution means even a validator that predates the
  construct still resolves references into it correctly.
- **Not safe as a minor**: reserving a name that was previously free-form
  user territory - for example, adding a fourth entry-level structural key
  alongside `group`/`rules`/`inherit`. Even though the change looks small,
  a standard could have legitimately used that name as an ordinary
  attribute before. Taking away that validity is a breaking change by
  definition, whatever else it looks like - it must be a major bump, and
  the existing "attribute can't share a structural key's name" check
  (`fields.py`) would then rightly reject it.

If a future major bump needs to do exactly that - reserve a name out of
previously-open space - the transition should degrade gracefully rather
than silently reinterpreting a document written before the reservation
existed: warn, and let the older, attribute meaning win for a standard
that declared that name explicitly, rather than hard-erroring or silently
switching interpretation underneath it. No structural key has ever been
added after the fact, so this has no code behind it yet - it's the policy
for if/when it happens, not a mechanism that exists today.

No compatibility matrix needs to be maintained by hand: the discovery-time
error already names both the standard's major and what this validator
supports, and `doc/CHANGELOG.md` records the day a bump happened, the same
as any other breaking change.

## `standard_version` - your own bookkeeping

Fully independent from `schema_version` - no required major-match, no
required `major.minor` shape. Format, meaning, and cadence are entirely up
to you.

This used to be coupled: the major had to match `schema_version`'s major,
and only the minor was "yours." That meant the major slot was never really
yours - you couldn't advance it without a schema bump forcing your hand,
and you couldn't hold it still if a schema bump happened without your
content actually changing. The only thing that ever read this field was
`doc.py`, to print it in the generated doc's header and footer - nothing
validates against it, nothing branches on its value - so decoupling it
loses nothing and gives you the whole number, not just half of it.

## Rule identity - the `-v<major>` directory suffix

The reason a rule's major lives in its **name**
(`file-extensions-v1/`, `file-extensions-v2/`) is to let multiple versions
of the same rule coexist while you migrate - it is not primarily a
consistency-checking mechanism. A rule already attached in a standard must
never change checking behavior under its owner without an explicit,
visible choice; making the major part of the identity itself, not just a
field inside the manifest, makes that a structural guarantee rather than a
convention someone could get wrong: two different checking behaviors
literally cannot share one rule-id. Old and new majors sit in the catalog
side by side indefinitely, and can even be attached to different paths in
the same standard, for as long as you want - there is no forced migration
and no concept of "latest."

**Bump the major** (new directory) for a breaking change to what the rule
checks or how its params work: a param removed, a value's meaning
changed, an optional param made required.

**Don't bump the major** for a `protocol_version` change alone (see
below), or for an additive param change - a new *optional* param with a
default doesn't break anything already attached, since an existing
attachment simply doesn't set it and gets the default.

## A rule's own manifest `version`

The major **must equal** the directory suffix - checked by discovery, not
convention. This isn't a second, independent number: both are naming the
exact same fact (which generation of this one rule this is), so requiring
them to match is a guard rail, not a design decision in its own right - it
catches an author promoting a directory to `-v2` and forgetting the
manifest, or the reverse.

The **minor** is free bookkeeping for a rule author - the same shape
`standard_version` is for you. A smarter pattern, a clearer error message,
a bug fix that only makes a previously-wrong result more correct: all of
these bump the minor in place, same directory, no downstream code reads
the value.

## `protocol_version` - the runner↔script wire format

Separate from a rule's own `version` entirely. This axis is the calling
convention every rule script shares - CLI flags, stdout JSON shape - not
anything about what a specific rule checks.

`SUPPORTED_PROTOCOL_MAJORS` (`discovery.py`) is an **additive set**, not a
single replaced value like `SUPPORTED_SCHEMA_MAJOR`. The asymmetry is
deliberate: a standard is one file with one owner, migrated in one
sitting; rules are numerous and independently maintained - bundled ones
move in step with the tool, `rules.own/` ones may not have been touched in
years, `rules.external/` ones are on someone else's schedule entirely. If
the runner replaced its single supported protocol major on every bump,
upgrading the tool would simultaneously break every rule still on the old
wire format, including third-party ones you have no ability to fix on
demand. Keeping an old adapter around is cheap, because the thing being
versioned here - invocation shape and stdout parsing - is small and
isolable per major, unlike schema grammar, which touches the whole
validator. Dropping an old adapter is a deliberate, rare decision of its
own, not the default outcome of a protocol bump.

A rule declaring a protocol major with no adapter is excluded from the
catalog with a **warning**, not an error that blocks the whole standard.
Unlike a broken manifest (bad TOML, missing checker script, a
`version`/directory mismatch - all still hard errors), an unsupported
protocol isn't a mistake to fix, it resolves itself once either side
updates. If you're not using that rule, the rest of your standard still
validates and runs normally; if you are, the existing "this rule reference
doesn't resolve to anything in the catalog" check already fires, at that
specific attachment site - no separate mechanism was needed for that half.

Migrating one rule to a new protocol never requires bumping that rule's
own `version` major or renaming its directory. It's a self-contained
change to that one rule: rewrite its scripts to the new wire shape, bump
`protocol_version`, done. Every standard that already has that rule
attached keeps working unmodified, because nothing about the rule's
identity, params, or checking behavior moved.

---

## See also

- [doc/DESIGN.md](DESIGN.md) - why the standard and rules are two separate
  file types in the first place
- [doc/RULES.md](RULES.md) - the manifest schema and the runner↔script
  protocol, from a rule author's side
- [doc/VALIDATOR_SPEC.md](VALIDATOR_SPEC.md) - exactly what the validator
  checks about `meta` and rule discovery
- [doc/BACKLOG.md](BACKLOG.md) - work planned but not yet built
