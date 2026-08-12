# A PARA tree you can break and re-check

A toy filesystem under [`tree/`](tree/) and a standard,
[`fs-org-std.toml`](fs-org-std.toml), that describes how it is supposed
to be organized. The tree ships with three deliberate mistakes in it, so
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
│   ├── finances/                 README.md, budget-2026.md
│   └── health/                   README.md, running-log.md
├── inbox/
│   ├── electricity-bill-2026-08.md
│   └── untitled.md                          ← (1) zero bytes
├── projects/
│   ├── apartment-move/           README.md, checklist.md, movers-quotes.md
│   ├── guitar-lessons/           practice-log.md   ← (2) no README.md
│   └── website-redesign/         README.md, content-inventory.md
└── resources/
    ├── cooking/                  pasta-technique.md
    ├── typography/               font-pairing.md
    └── Screenshot 2026-07-14 at 09.41.22.png    ← (3) named by the OS
```

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
Category  OK  Warn  Broken  Total
--------  --  ----  ------  -----
paths      7     0       0      7

0 error(s), 0 warning(s)
```

Seven cataloged paths, all clean. Try breaking one — set
`lifecycle = "eternal"` on `[paths."areas/"]`, or delete a `reason` from
a rule attachment — and run it again to see what it catches.

## 2. Check the tree

```console
$ fs-org-run fs-org-std.toml
paths."inbox/".rules.empty-v1[0]: [VIOLATION] empty-v1 (tree/inbox): 1 empty item(s): untitled.md
paths."projects/*/".rules.required-content-v1[0]: [VIOLATION] required-content-v1 (tree/projects/guitar-lessons): missing required: README.md
paths."resources/".rules.naming-pattern-v1[0]: [VIOLATION] naming-pattern-v1 (tree/resources): 1 item(s) that doesn't match the required pattern: Screenshot 2026-07-14 at 09.41.22.png

Summary
         ok  4
  violation  3
      fixed  0
  unfixable  0
     broken  0
    skipped  0

7 invocation(s) total
```

Each line names the attachment that produced it, so you can go straight
to the block of TOML responsible.

Four attachments in the standard became **seven invocations**, because
`[paths."projects/*/"]` is a glob key — one entry covering every folder
it matches:

| Attachment | Runs on |
|---|---|
| `inbox/` → `empty-v1` | `tree/inbox` |
| `projects/` → `staleness-v1` | `tree/projects` |
| `projects/*/` → `required-content-v1` | all three project folders |
| `archive/*/` → `required-content-v1` | `2025-kitchen-remodel` — *inherited* from `projects/*/` |
| `resources/` → `naming-pattern-v1` | `tree/resources` |

Add a fourth project folder and it is covered with no edit to the
standard. The archive entry declares nothing but `lifecycle` and an
`inherit` block: an archived project is the same thing at rest, so it
keeps the same purpose and the same README requirement.

## 3. Fix them by hand

```bash
rm tree/inbox/untitled.md
mv "tree/resources/Screenshot 2026-07-14 at 09.41.22.png" tree/resources/typography/font-specimen.png
printf '# Guitar lessons\n\n**Done when:** the lesson piece is playable at 100 bpm.\n' \
    > tree/projects/guitar-lessons/README.md
```

```console
$ fs-org-run fs-org-std.toml

Summary
         ok  7
  violation  0
...
```

Exit status is 0 when clean, 1 on any violation, 2 if the standard
itself doesn't validate — so this drops straight into a git hook or CI.

None of those three rules ships a fixer, and that is deliberate: whether
a badly-named file should be renamed or refiled, and what a missing
README should *say*, are decisions the tool can't make. See "why there
is no fixer" in each rule's manifest under [`rules/`](../../rules/).

## 4. Let the tool fix one for you

`staleness-v1` does have a fixer, because "this project has gone quiet"
has exactly one sensible response in PARA. Age a project past the 90-day
threshold:

```bash
find tree/projects/website-redesign -exec touch -d '2026-01-15' {} +
```

```console
$ fs-org-run fs-org-std.toml
paths."projects/".rules.staleness-v1[0]: [VIOLATION] staleness-v1 (tree/projects): 1 item(s) violating 'stale' threshold of 90d: website-redesign (hasn't been touched in 209d)
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

Written from the *resolved* standard, so `archive/*/` shows the values
it inherits rather than blanks:

```markdown
| Purpose | One project: its notes, its files, and a README stating what 'done' means. *(inherited from `projects/*/`)* |
```

Includes Mermaid diagrams of the tree, lifecycles, and rule coverage;
`--no-diagrams` drops them, `--sections` picks parts.

## Reset the example

`git restore` doesn't undo the `touch`, so reset timestamps too:

```bash
git clean -fd tree/ && git restore tree/
find tree -exec touch {} +
```

## Where to go next

Things this example deliberately leaves out — see
[`fs-org-std.template.toml`](../../fs-org-std.template.toml) for the
full grammar and [`doc/RULES.md`](../../doc/RULES.md) for writing rules:

- **`allow_missing`** — catalog `projects/x/` *and* `archive/x/`, mark
  both, and moving the real folder between them needs no edit here.
- **Blanket attachments** — `[[paths.rules.<name>]]` runs a rule on
  every cataloged path; `[[folders.rules.<name>]]` on every folder under
  root, cataloged or not.
- **Cross-path rules** — `[[paths.cross]]` hands one rule several paths
  at once, for checks about the relationship between them.
- **Reserved folder names** — `[folders.reserved]`, for a name like
  `_archive` that means the same thing wherever it appears.
- **Your own rules** — drop a directory into `rules.own/` beside your
  standard and it's discovered automatically.

To point this at a real tree: change `root`, keep or drop the entries,
and run the validator until it's quiet. Start with one folder you
already care about rather than cataloging everything at once.
