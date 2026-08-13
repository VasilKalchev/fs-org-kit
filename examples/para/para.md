# tree - fs-org-std

## Table of Contents

- [Overview](#overview)
- [Paths](#paths)
  - [`archive/`](#archive/)
    - [`*/`](#archive/*/)
  - [`areas/`](#areas/)
  - [`inbox/`](#inbox/)
  - [`projects/`](#projects/)
    - [`*/`](#projects/*/)
  - [`resources/`](#resources/)
- [Cross-Path Sets](#cross-path%20sets)
  - [Set 1](#set%201)
- [Reserved Folders](#reserved%20folders)
  - [`_attachments`](#_attachments)
- [Rules](#rules)
  - [`duplicate-files-v1`](#duplicate-files-v1)
  - [`empty-v1`](#empty-v1)
  - [`link-policy-v1`](#link-policy-v1)
  - [`naming-pattern-v1`](#naming-pattern-v1)
  - [`required-content-v1`](#required-content-v1)
  - [`staleness-v1`](#staleness-v1)
- [Enums](#enums)

## Overview

- **Root**: `./tree/`
- PARA (Projects / Areas / Resources / Archive) plus an inbox, as an enforceable standard.
- **Schema version**: 2.1 (2026-08-12)
- **Standard version**: 2.1 (2026-08-12)
- **Cataloged paths**: 7
- **Cross-path sets**: 1
- **Reserved folders**: 1

## Paths

### `archive/`

| Field | Value |
|---|---|
| Purpose | Everything from the other three categories that is no longer active - kept, not deleted. |
| Lifecycle | [`archival`](#enums) |
| Origin | [`self`](#enums) |

**Use for:**

- finished or abandoned projects
- areas you no longer maintain

**Not for:**

- anything you still expect to touch this month

### `archive/*/`

| Field | Value |
|---|---|
| Purpose | One project: its notes, its files, and a README stating what 'done' means. |
| Lifecycle | [`archival`](#enums) |
| Origin | [`self`](#enums) |

**Use for:**

- working files for this project only

**Not for:**

- reference material that outlives the project - move it to resources/ when you finish

**Attached rules:**

| Rule | Reason |
|---|---|
| [`required-content-v1`](#required-content-v1) | a project without a written definition of done drifts into being an area |

### `areas/`

| Field | Value |
|---|---|
| Purpose | Ongoing responsibilities with a standard to maintain and no finish line - health, finances, the car. |
| Notes | The PARA distinction that does the most work: an area is never 'done'. If it can be finished, it belongs in projects/. |
| Lifecycle | [`ongoing`](#enums) |
| Origin | [`self`](#enums) |

**Use for:**

- a responsibility you hold indefinitely

**Not for:**

- anything with a deadline or a definition of done

### `inbox/`

| Field | Value |
|---|---|
| Purpose | Landing zone for anything not yet filed - scans, downloads, half-written notes. |
| Notes | Not part of canonical PARA, but a common addition: without it, filing pressure lands on the four real categories. |
| Lifecycle | [`transient`](#enums) |
| Origin | [`external`](#enums), [`self`](#enums) |

**Use for:**

- anything you haven't decided about yet

**Not for:**

- anything you've already decided about

**Attached rules:**

| Rule | Reason |
|---|---|
| [`empty-v1`](#empty-v1) | a zero-byte file in the inbox is a failed download, not something waiting to be filed |

### `projects/`

| Field | Value |
|---|---|
| Purpose | Short-term efforts with a definition of done and (usually) a deadline. |
| Lifecycle | [`temporary`](#enums) |
| Origin | [`self`](#enums) |

**Use for:**

- anything you can finish

**Not for:**

- standing responsibilities - those are areas/
- reference material - that's resources/

**Attached rules:**

| Rule | Reason |
|---|---|
| [`staleness-v1`](#staleness-v1) | a project nobody has touched in three months is finished or abandoned - either way it belongs in archive/ |

### `projects/*/`

| Field | Value |
|---|---|
| Purpose | One project: its notes, its files, and a README stating what 'done' means. |
| Lifecycle | [`temporary`](#enums) |
| Origin | [`self`](#enums) |

**Use for:**

- working files for this project only

**Not for:**

- reference material that outlives the project - move it to resources/ when you finish

**Attached rules:**

| Rule | Reason |
|---|---|
| [`required-content-v1`](#required-content-v1) | a project without a written definition of done drifts into being an area |

### `resources/`

| Field | Value |
|---|---|
| Purpose | Topics of ongoing interest - reference material that belongs to no single project. |
| Lifecycle | [`ongoing`](#enums) |
| Origin | [`self`](#enums), [`external`](#enums) |

**Use for:**

- notes, clippings and references you'll want again

**Not for:**

- anything you're actively working on

**Attached rules:**

| Rule | Reason |
|---|---|
| [`naming-pattern-v1`](#naming-pattern-v1) | reference material is only findable if it is named for what it contains |

## Cross-Path Sets

### Set 1

**Members**: [`inbox/`](#inbox/), [`resources/`](#resources/)

**Attached rules:**

| Rule | Reason |
|---|---|
| [`duplicate-files-v1`](#duplicate-files-v1) | a file that is in the inbox and already filed is a filing job that stopped halfway |

## Reserved Folders

Reserved-name prefix: `_`

### `_attachments`

| Field | Value |
|---|---|
| Purpose | Files a document refers to, kept beside it rather than in a shared pile. |
| Notes | Deliberately location-independent: a note and the things it points at should move together, whichever of the four categories the note is sitting in this month. |
| Lifecycle | [`ongoing`](#enums) |

**Use for:**

- images, scans and PDFs referenced by a document next to this folder

**Not for:**

- anything a second document also refers to - that's a resource, not an attachment

**Attached rules:**

| Rule | Reason |
|---|---|
| [`link-policy-v1`](#link-policy-v1) | an attachments folder that has grown subfolders has stopped being an attachments folder |

## Rules

### `duplicate-files-v1`

**Attached at 1 location(s):**

- [`Cross-Path Set 1`](#set%201) - a file that is in the inbox and already filed is a filing job that stopped halfway

### `empty-v1`

**Attached at 1 location(s):**

- [`inbox/`](#inbox/) - a zero-byte file in the inbox is a failed download, not something waiting to be filed

### `link-policy-v1`

**Attached at 1 location(s):**

- [`folders.reserved."_attachments"`](#_attachments) - an attachments folder that has grown subfolders has stopped being an attachments folder

### `naming-pattern-v1`

**Attached at 2 location(s):**

- `every folder under root (blanket)` - a folder is found by its name long before anything looks inside it
- [`resources/`](#resources/) - reference material is only findable if it is named for what it contains

### `required-content-v1`

**Attached at 2 location(s):**

- [`archive/*/`](#archive/*/) - a project without a written definition of done drifts into being an area
- [`projects/*/`](#projects/*/) - a project without a written definition of done drifts into being an area

### `staleness-v1`

**Attached at 1 location(s):**

- [`projects/`](#projects/) - a project nobody has touched in three months is finished or abandoned - either way it belongs in archive/

## Enums

**`enums.group.lifecycle`:**

| Value | Meaning |
|---|---|
| `transient` | meant to be emptied constantly, nothing lingers |
| `temporary` | has a completion condition, then gets archived |
| `ongoing` | continuously active/maintained, no end state |
| `archival` | already at rest, rarely touched |

**`enums.group.origin`:**

| Value | Meaning |
|---|---|
| `self` | authored directly by you - nothing to re-fetch or resync from elsewhere |
| `external` | sourced from outside this system - downloaded, received, or otherwise not authored by you |
| `generated` | produced automatically by a tool, script, or model - not hand-authored, not fetched externally |

---
*Generated from `fs-org-std.toml` - standard v2.1, schema v2.1*
