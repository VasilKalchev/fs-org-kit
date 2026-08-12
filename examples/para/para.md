# tree - fs-org-std

> Generated from `fs-org-std.toml` - standard v1.0, schema v1.0

## Table of Contents

- [Overview](#section-overview)
- [Paths](#section-paths)
  - [`archive/`](#path-archive)
  - [`archive/*/`](#path-archive)
  - [`areas/`](#path-areas)
  - [`inbox/`](#path-inbox)
  - [`projects/`](#path-projects)
  - [`projects/*/`](#path-projects)
  - [`resources/`](#path-resources)
- [Rules](#section-rules)
  - [`empty-v1`](#rule-empty-v1)
  - [`naming-pattern-v1`](#rule-naming-pattern-v1)
  - [`required-content-v1`](#rule-required-content-v1)
  - [`staleness-v1`](#rule-staleness-v1)
- [Enums](#section-enums)

<a id="section-overview"></a>
## Overview

- **Root**: `./tree/`
- PARA (Projects / Areas / Resources / Archive) plus an inbox, as an enforceable standard.
- **Schema version**: 1.0 (2026-08-05)
- **Standard version**: 1.0 (2026-08-11)
- **Cataloged paths**: 7
- **Cross-path sets**: 0
- **Reserved folders**: 0

**Path hierarchy:**

```mermaid
graph TD
    root["(root)"]
    n0["archive/"]
    n1["archive/*/"]
    n2["areas/"]
    n3["inbox/"]
    n4["projects/"]
    n5["projects/*/"]
    n6["resources/"]
    root --> n0
    n0 --> n1
    root --> n2
    root --> n3
    root --> n4
    n4 --> n5
    root --> n6
```

<a id="section-paths"></a>
## Paths

<a id="path-archive"></a>
### `archive/`

| Field | Value |
|---|---|
| Purpose | Everything from the other three categories that is no longer active - kept, not deleted. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | `self` |

**Use for:**
- finished or abandoned projects
- areas you no longer maintain

**Not for:**
- anything you still expect to touch this month

<a id="path-archive"></a>
### `archive/*/`

| Field | Value |
|---|---|
| Purpose | One project: its notes, its files, and a README stating what 'done' means. *(inherited from `projects/*/`)* |
| Lifecycle | [`archival`](#section-enums) |
| Origin | `self` *(inherited from `projects/*/`)* |

**Use for:**
- working files for this project only

**Not for:**
- reference material that outlives the project - move it to resources/ when you finish

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`required-content-v1`](#rule-required-content-v1) *(inherited from `projects/*/`)* | a project without a written definition of done drifts into being an area | `required=["README.md"]` |

<a id="path-areas"></a>
### `areas/`

| Field | Value |
|---|---|
| Purpose | Ongoing responsibilities with a standard to maintain and no finish line - health, finances, the car. |
| Notes | The PARA distinction that does the most work: an area is never 'done'. If it can be finished, it belongs in projects/. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | `self` |

**Use for:**
- a responsibility you hold indefinitely

**Not for:**
- anything with a deadline or a definition of done

<a id="path-inbox"></a>
### `inbox/`

| Field | Value |
|---|---|
| Purpose | Landing zone for anything not yet filed - scans, downloads, half-written notes. |
| Notes | Not part of canonical PARA, but a common addition: without it, filing pressure lands on the four real categories. |
| Lifecycle | [`transient`](#section-enums) |
| Origin | `external`, `self` |

**Use for:**
- anything you haven't decided about yet

**Not for:**
- anything you've already decided about

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`empty-v1`](#rule-empty-v1) | a zero-byte file in the inbox is a failed download, not something waiting to be filed | `check_folders=false` |

<a id="path-projects"></a>
### `projects/`

| Field | Value |
|---|---|
| Purpose | Short-term efforts with a definition of done and (usually) a deadline. |
| Lifecycle | [`temporary`](#section-enums) |
| Origin | `self` |

**Use for:**
- anything you can finish

**Not for:**
- standing responsibilities - those are areas/
- reference material - that's resources/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`staleness-v1`](#rule-staleness-v1) | a project nobody has touched in three months is finished or abandoned - either way it belongs in archive/ | `mode="stale"`, `threshold="90d"`, `destination="archive"` |

<a id="path-projects"></a>
### `projects/*/`

| Field | Value |
|---|---|
| Purpose | One project: its notes, its files, and a README stating what 'done' means. |
| Lifecycle | [`temporary`](#section-enums) |
| Origin | `self` |

**Use for:**
- working files for this project only

**Not for:**
- reference material that outlives the project - move it to resources/ when you finish

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`required-content-v1`](#rule-required-content-v1) | a project without a written definition of done drifts into being an area | `required=["README.md"]` |

<a id="path-resources"></a>
### `resources/`

| Field | Value |
|---|---|
| Purpose | Topics of ongoing interest - reference material that belongs to no single project. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | `self`, `external` |

**Use for:**
- notes, clippings and references you'll want again

**Not for:**
- anything you're actively working on

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`naming-pattern-v1`](#rule-naming-pattern-v1) | reference material is only findable if it is named for what it contains | `pattern="^[a-z0-9]+(-[a-z0-9]+)*(\.[a-z0-9]+)?$"`, `mode="allow"` |

<a id="section-rules"></a>
## Rules

```mermaid
graph LR
    r0["empty-v1"]
    r1["naming-pattern-v1"]
    r2["required-content-v1"]
    r3["staleness-v1"]
    s0("archive/*/")
    s1("inbox/")
    s2("projects/")
    s3("projects/*/")
    s4("resources/")
    r0 --- s1
    r1 --- s4
    r2 --- s0
    r2 --- s3
    r3 --- s2
```

<a id="rule-empty-v1"></a>
### `empty-v1`

Reports zero-byte files and empty folders under a path - leftovers from an interrupted download, a failed export, or a folder whose contents were moved out and never cleaned up.

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `single` |
| Fixable | no |

**Params:**

| Name | Default | Required |
|---|---|---|
| `check_files` | `true` | no |
| `check_folders` | `true` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |
| `folder_empty_means` | `"no_entries"` | no |

**Attached at 1 location(s):**

- [`inbox/`](#path-inbox) - a zero-byte file in the inbox is a failed download, not something waiting to be filed

<a id="rule-naming-pattern-v1"></a>
### `naming-pattern-v1`

Checks file and/or folder names against a regular expression - either every name must match it (allow), or no name may match it (disallow).

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `single` |
| Fixable | no |

**Params:**

| Name | Default | Required |
|---|---|---|
| `pattern` |  | yes |
| `mode` |  | yes |
| `target` | `"both"` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- [`resources/`](#path-resources) - reference material is only findable if it is named for what it contains

<a id="rule-required-content-v1"></a>
### `required-content-v1`

Checks a path for entries it must have, should have, or must not have - e.g. a project folder required to contain README.md and suggested to contain .git/.

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `single` |
| Fixable | no |

**Params:**

| Name | Default | Required |
|---|---|---|
| `required` | `[]` | no |
| `suggested` | `[]` | no |
| `forbidden` | `[]` | no |
| `report_suggested` | `true` | no |

**Attached at 2 location(s):**

- [`archive/*/`](#path-archive) *(inherited from `projects/*/`)* - a project without a written definition of done drifts into being an area
- [`projects/*/`](#path-projects) - a project without a written definition of done drifts into being an area

<a id="rule-staleness-v1"></a>
### `staleness-v1`

Checks each direct child of a path against an age threshold - either flagging things that have gone stale (mode="stale", for active folders that should stay current) or things that are unexpectedly active (mode="active", for archive folders that shouldn't be seeing new activity).

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `single` |
| Fixable | yes |

**Params:**

| Name | Default | Required |
|---|---|---|
| `mode` |  | yes |
| `threshold` |  | yes |
| `basis` | `"mtime"` | no |
| `destination` |  | yes |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- [`projects/`](#path-projects) - a project nobody has touched in three months is finished or abandoned - either way it belongs in archive/

<a id="section-enums"></a>
## Enums

**Lifecycle:**

| Value | Meaning |
|---|---|
| `transient` | meant to be emptied constantly, nothing lingers |
| `temporary` | has a completion condition, then gets archived |
| `ongoing` | continuously active/maintained, no end state |
| `archival` | already at rest, rarely touched |

```mermaid
graph LR
    l0["transient"]
    l1["temporary"]
    l2["ongoing"]
    l3["archival"]
    l0 --> l1
    l1 --> l2
    l2 --> l3
```

**Origin:**

| Value | Meaning |
|---|---|
| `self` | authored directly by you - nothing to re-fetch or resync from elsewhere |
| `external` | sourced from outside this system - downloaded, received, or otherwise not authored by you |
| `generated` | produced automatically by a tool, script, or model - not hand-authored, not fetched externally |

