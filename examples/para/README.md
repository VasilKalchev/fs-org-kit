# A PARA tree you can break and re-check

A toy filesystem under [`tree/`](tree/) and a standard,
[`fs-org-std.toml`](fs-org-std.toml), that describes how it is supposed
to be organized. The tree ships with five deliberate mistakes in it, so
the very first run has something to say.

Nothing here touches anything outside this directory. Break it, run the
tools, `git restore` it (see [Reset](#reset-the-example)).

## What PARA is

PARA (Tiago Forte) sorts everything you keep into four categories, by
**how soon you'll act on it** rather than by subject:

| | | |
|---|---|---|
| **Projects** | something you can finish | "Move apartments by 30 September" |
| **Areas** | a standing responsibility with no finish line | Health, finances |
| **Resources** | reference material for its own sake | Cooking notes, typography |
| **Archive** | anything from the other three that's gone inactive | Last year's kitchen remodel |

The interesting part is the movement between them: a project that goes
quiet belongs in the archive, an archived project that restarts comes
back out. Learn more: <https://fortelabs.com/blog/para/>.

This example adds an `inbox/` — not canonical PARA, but common, and it
gives the "not decided yet" pile somewhere to live.

## The tree

```
tree/
├── archive/
│   └── 2025-kitchen-remodel/     README.md, final-invoice.md
├── areas/
│   ├── Car Maintenance/          ← (4) named in a file manager, not kebab-case
│   ├── finances/                 README.md, budget-2026.md
│   └── health/                   README.md, running-log.md
├── inbox/
│   ├── electricity-bill-2026-08.md
│   ├── font-pairing.md           ← (5) identical to the filed copy in resources/
│   └── untitled.md               ← (1) zero bytes
├── projects/
│   ├── apartment-move/           README.md, checklist.md, movers-quotes.md
│   │   └── _attachments/         a reserved name: means the same thing anywhere
│   ├── guitar-lessons/           practice-log.md   ← (2) no README.md
│   └── website-redesign/         README.md, content-inventory.md
└── resources/
    ├── cooking/                  pasta-technique.md
    ├── typography/               font-pairing.md
    │   └── _attachments/         the same reserved name, somewhere else entirely
    └── Screenshot 2026-07-14 at 09.41.22.png    ← (3) named by the OS
```

Each of the five mistakes is caught by a different kind of attachment,
which is the real point of the example — see
[the five, and what catches each](#the-five-and-what-catches-each).

## Setup

From the repository root:

```bash
pip install -e ".[dev]"
cd examples/para
```

**Run every command below from `examples/para/`.** The standard says
`root = "./tree/"`, and a relative root resolves against the directory
you run from, not against the file.

## 1. Validate the standard

Before checking the tree, check the file that describes it — this reads
no filesystem at all:

```console
$ fs-org-validate fs-org-std.toml

Summary
Category                OK  Warn  Broken  Total
----------------------  --  ----  ------  -----
paths                    7     0       0      7
cross-path sets          1     0       0      1
reserved folders         1     0       0      1
folder rules (blanket)   1     0       0      1

0 error(s), 0 warning(s)
```

Four categories, all clean. Try breaking one — set
`lifecycle = "eternal"` in `[paths."areas/".group]`, or delete a `reason` from
a rule attachment — and run it again to see what it catches.

## 2. Check the tree

```console
$ fs-org-run fs-org-std.toml
paths."inbox/".rules.empty-v1[0]: [VIOLATION] empty-v1 (tree/inbox): 1 empty item(s): untitled.md
paths."projects/*/".rules.required-content-v1[0]: [VIOLATION] required-content-v1 (tree/projects/guitar-lessons): missing required: README.md
paths."resources/".rules.naming-pattern-v1[0]: [VIOLATION] naming-pattern-v1 (tree/resources): 1 item(s) that doesn't match the required pattern: Screenshot 2026-07-14 at 09.41.22.png
paths.cross[0].rules.duplicate-files-v1[0]: [VIOLATION] duplicate-files-v1 (tree/inbox, tree/resources): 1 group(s) of identical files spanning 2+ of the given paths: [.../tree/inbox/font-pairing.md, .../tree/resources/typography/font-pairing.md]
folders.rules.naming-pattern-v1[0]: [VIOLATION] naming-pattern-v1 (tree): 1 item(s) that doesn't match the required pattern: areas/Car Maintenance

Summary
         ok  6
  violation  5
      fixed  0
  unfixable  0
     broken  0
    skipped  0

11 invocation(s) total
```

(`duplicate-files-v1` prints absolute paths; they're shortened to `...`
here.)

Each line names the attachment that produced it, so you can go straight
to the block of TOML responsible.

### The five, and what catches each

Seven attachments in the standard became **eleven invocations**, and no
two of the five mistakes are found the same way:

| # | Mistake | Caught by | Which is |
|---|---|---|---|
| 1 | `inbox/untitled.md` is zero bytes | `inbox/` → `empty-v1` | a rule on one cataloged path |
| 2 | `guitar-lessons/` has no README | `projects/*/` → `required-content-v1` | a **glob key** — one entry, every folder it matches |
| 3 | a screenshot with the OS's name | `resources/` → `naming-pattern-v1` | a rule on one cataloged path |
| 4 | `areas/Car Maintenance/` | `[[folders.rules]]` → `naming-pattern-v1` | a **blanket rule** over every folder under root, cataloged or not |
| 5 | the same file in `inbox/` and `resources/` | `[[paths.cross]]` → `duplicate-files-v1` | a **cross-path rule**, asking about the relationship between two paths |

The eleven invocations:

| Attachment | Runs on |
|---|---|
| `inbox/` → `empty-v1` | `tree/inbox` |
| `projects/` → `staleness-v1` | `tree/projects` |
| `projects/*/` → `required-content-v1` | all three project folders |
| `archive/*/` → `required-content-v1` | `2025-kitchen-remodel` — *inherited* from `projects/*/` |
| `resources/` → `naming-pattern-v1` | `tree/resources` |
| `[[paths.cross]]` → `duplicate-files-v1` | `tree/inbox` and `tree/resources`, together, once |
| `[[folders.rules]]` → `naming-pattern-v1` | `tree` — **once**, not once per folder |
| `_attachments` → `link-policy-v1` | both folders named `_attachments`, wherever they sit |

Three of those are worth a second look:

- **A blanket `[[folders.rules]]` attachment is one invocation**, handed
  root. Whether it reaches one folder or all of them is decided by the
  rule's own `recursive` param, not by the runner walking the tree for
  you. Set `recursive = false` on it and mistake 4 stops being found.
- **A reserved name matches by name, not location.** `_attachments`
  isn't cataloged as a path and doesn't need to be; the runner finds
  every folder called that, anywhere under root, and both of this tree's
  pass. Move one and it's still checked.
- **The archive entry declares almost nothing.** It has `lifecycle` and
  an `inherit` block: an archived project is the same thing at rest, so
  it keeps the same purpose and the same README requirement. A project
  moving between `projects/` and `archive/` needs no edit to the
  standard.

Add a fourth project folder and it is covered with no edit either.

## 3. Fix them by hand

```bash
rm tree/inbox/untitled.md
rm tree/inbox/font-pairing.md            # already filed under resources/
mv "tree/resources/Screenshot 2026-07-14 at 09.41.22.png" tree/resources/typography/font-specimen.png
mv "tree/areas/Car Maintenance" tree/areas/car-maintenance
printf '# Guitar lessons\n\n**Done when:** the lesson piece is playable at 100 bpm.\n' \
    > tree/projects/guitar-lessons/README.md
```

```console
$ fs-org-run fs-org-std.toml

Summary
         ok  11
  violation  0
      fixed  0
  unfixable  0
     broken  0
    skipped  0

11 invocation(s) total
```

Exit status is 0 when clean, 1 on any violation, 2 if the standard
itself doesn't validate — so this drops straight into a git hook or CI.

None of those five rules ships a fixer, and that is deliberate: whether
a badly-named file should be renamed or refiled, which copy of a
duplicate is the one to keep, and what a missing README should *say*,
are decisions the tool can't make. See "why there is no fixer" in each
rule's manifest under [`rules/`](../../rules/).

## 4. Let the tool fix one for you

`staleness-v1` does have a fixer, because "this project has gone quiet"
has exactly one sensible response in PARA. Age a project past the 90-day
threshold:

```bash
find tree/projects/website-redesign -exec touch -d '200 days ago' {} +
```

```console
$ fs-org-run fs-org-std.toml
paths."projects/".rules.staleness-v1[0]: [VIOLATION] staleness-v1 (tree/projects): 1 item(s) violating 'stale' threshold of 90d: website-redesign (hasn't been touched in 200d)
```

```console
$ fs-org-run fs-org-std.toml --fix
paths."projects/".rules.staleness-v1[0]: [FIXED] staleness-v1 (tree/projects): 1 item(s) moved to .../tree/archive
paths."projects/*/".rules.required-content-v1[0]: [SKIPPED] required-content-v1 (tree/projects/website-redesign): no longer exists (moved or removed during this run)
```

The project is now in `tree/archive/`. The `[SKIPPED]` line follows from
moving a folder mid-run: every invocation is planned up front from the
tree as it was, and `projects/*/` had already matched a folder that was
gone by the time its turn came. Skipping doesn't count as a failure — a
run whose only oddity is a skip still exits 0. **Run it again** for the
true state: the moved project is now matched by `archive/*/` instead,
still checked for its README, and passing.

Rules without a fixer still run their checker under `--fix`; they just
report.

## 5. Generate the documentation

```bash
fs-org-doc fs-org-std.toml --output para.md
```

[`para.md`](para.md) is the result, checked in so you can read it
without running anything. It has a section per cataloged path, per
cross-path set and per reserved folder — each with its purpose, its
grouping fields, and the rules attached to it with the reason given at
each attachment site:

```markdown
### `_attachments`

| Field | Value |
|---|---|
| Purpose | Files a document refers to, kept beside it rather than in a shared pile. |
| Lifecycle | [`ongoing`](#enums) |
```

Then a `Rules` section inverts it — every rule, and everywhere it is
attached — which is the view the TOML can't give you, since attachments
are scattered across it by location:

```markdown
### `naming-pattern-v1`

**Attached at 2 location(s):**

- `every folder under root (blanket)` - a folder is found by its name long before anything looks inside it
- [`resources/`](#resources/) - reference material is only findable if it is named for what it contains
```

It's written from the *resolved* standard, so `archive/*/` documents the
purpose and rules it inherits from `projects/*/` with their real values
rather than blanks.

## Reset the example

`git restore` won't remove new files or undo the `touch`, so:

```bash
git clean -fd tree/ && git restore tree/
find tree -exec touch {} +
```

## Where to go next

Things this example still leaves out — see
[`fs-org-std.template.toml`](../../fs-org-std.template.toml) for the
full grammar and [`doc/RULES.md`](../../doc/RULES.md) for writing rules:

- **Blanket attachments over cataloged paths** — `[[paths.rules.<name>]]`
  runs a rule on every path in the catalog. (This example uses the other
  blanket form, `[[folders.rules.<name>]]`, over every folder on disk.)
- **Tags** — `[tags]` declares closed vocabularies for metadata carried
  by things *on disk*, handed to a rule as one param via
  `{ref = "tags.<namespace>"}`.
- **Abbreviations** — `[abbreviations]`, for shorthand used throughout a
  standard.
- **Out-of-root path keys** — `"/etc/nginx/"`, `"~/.config/"` and
  `"../sibling/"` each name exactly where they say, so one standard can
  govern several unrelated trees.
- **Your own rules** — drop a directory into `rules.own/` beside your
  standard and it's discovered automatically.

To point this at a real tree: change `root`, keep or drop the entries,
and run the validator until it's quiet. Start with one folder you
already care about rather than cataloging everything at once.
