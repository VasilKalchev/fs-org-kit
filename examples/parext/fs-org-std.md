# usr - fs-org-std

> Generated from `fs-org-std.toml` - standard v2.0, schema v2.0

## Table of Contents

- [Overview](#section-overview)
- [Paths](#section-paths)
  - [`area/`](#path-area)
  - [`area/3dp/`](#path-area-3dp)
  - [`area/fin/`](#path-area-fin)
  - [`area/infra/`](#path-area-infra)
  - [`area/inv/`](#path-area-inv)
  - [`area/inv/item/`](#path-area-inv-item)
  - [`area/lrn/`](#path-area-lrn)
  - [`area/paper/`](#path-area-paper)
  - [`area/rc/`](#path-area-rc)
  - [`area/std/`](#path-area-std)
  - [`inbox/`](#path-inbox)
  - [`knwl/`](#path-knwl)
  - [`media/`](#path-media)
  - [`media/book/`](#path-media-book)
  - [`media/cam/`](#path-media-cam)
  - [`media/music/`](#path-media-music)
  - [`media/pic/`](#path-media-pic)
  - [`media/vid/`](#path-media-vid)
  - [`prj/`](#path-prj)
  - [`prj/_arch/`](#path-prj-arch)
  - [`res/`](#path-res)
  - [`strg/`](#path-strg)
  - [`strg/app/`](#path-strg-app)
  - [`strg/bkup/`](#path-strg-bkup)
  - [`strg/driver/`](#path-strg-driver)
  - [`strg/game/`](#path-strg-game)
  - [`strg/unk/`](#path-strg-unk)
  - [`sys/`](#path-sys)
  - [`sys/lnk/`](#path-sys-lnk)
  - [`sys/lnk/cur/`](#path-sys-lnk-cur)
  - [`sys/lnk/nav/`](#path-sys-lnk-nav)
  - [`sys/lnk/os/`](#path-sys-lnk-os)
  - [`sys/prog/`](#path-sys-prog)
  - [`sys/scr/`](#path-sys-scr)
  - [`sys/vm/`](#path-sys-vm)
  - [`task/`](#path-task)
  - [`task/_arch/`](#path-task-arch)
  - [`tmp/`](#path-tmp)
  - [`ws/`](#path-ws)
  - [`ws/lib/`](#path-ws-lib)
  - [`ws/tmpl/`](#path-ws-tmpl)
  - [`ws/tool/`](#path-ws-tool)
- [Cross-Path Sets](#section-cross)
  - [Set 1](#cross-1)
- [Reserved Folders](#section-folders)
  - [`_arch`](#folder-arch)
  - [`_inbox`](#folder-inbox)
  - [`_unsorted`](#folder-unsorted)
  - [`_util`](#folder-util)
- [Rules](#section-rules)
  - [`basename-sync-v1`](#rule-basename-sync-v1)
  - [`duplicate-files-v1`](#rule-duplicate-files-v1)
  - [`empty-v1`](#rule-empty-v1)
  - [`file-extensions-v1`](#rule-file-extensions-v1)
  - [`link-integrity-v1`](#rule-link-integrity-v1)
  - [`link-policy-v1`](#rule-link-policy-v1)
  - [`naming-pattern-v1`](#rule-naming-pattern-v1)
  - [`spelling-abbreviations-v1`](#rule-spelling-abbreviations-v1)
  - [`staleness-v1`](#rule-staleness-v1)
  - [`timestamp-consistency-v1`](#rule-timestamp-consistency-v1)
  - [`timestamp-format-v1`](#rule-timestamp-format-v1)
  - [`uncataloged-reserved-v1`](#rule-uncataloged-reserved-v1)
- [Enums](#section-enums)
- [Abbreviations](#section-abbreviations)

<a id="section-overview"></a>
## Overview

- **Root**: `~/usr/`
- Personal filesystem standard for ~/usr/ - a PARA-style split (area/prj/task/res/knwl) with state carried by folder location and `_`-prefixed reserved names.
- **Schema version**: 2.0 (2026-08-12)
- **Standard version**: 2.0 (2026-08-12)
- **Cataloged paths**: 42
- **Cross-path sets**: 1
- **Reserved folders**: 4

*(path hierarchy diagram skipped - 42 paths exceeds the 40-node readability limit)*

<a id="section-paths"></a>
## Paths

**By `lifecycle`:**

- `archival` - [`prj/_arch/`](#path-prj-arch), [`strg/`](#path-strg), [`strg/app/`](#path-strg-app), [`strg/bkup/`](#path-strg-bkup), [`strg/driver/`](#path-strg-driver), [`strg/game/`](#path-strg-game), [`strg/unk/`](#path-strg-unk), [`task/_arch/`](#path-task-arch)
- `ongoing` - [`area/`](#path-area), [`area/3dp/`](#path-area-3dp), [`area/fin/`](#path-area-fin), [`area/infra/`](#path-area-infra), [`area/inv/`](#path-area-inv), [`area/inv/item/`](#path-area-inv-item), [`area/paper/`](#path-area-paper), [`area/rc/`](#path-area-rc), [`area/std/`](#path-area-std), [`knwl/`](#path-knwl), [`media/`](#path-media), [`media/book/`](#path-media-book), [`media/cam/`](#path-media-cam), [`media/music/`](#path-media-music), [`media/pic/`](#path-media-pic), [`media/vid/`](#path-media-vid), [`res/`](#path-res), [`sys/`](#path-sys), [`sys/lnk/`](#path-sys-lnk), [`sys/lnk/cur/`](#path-sys-lnk-cur), [`sys/lnk/nav/`](#path-sys-lnk-nav), [`sys/lnk/os/`](#path-sys-lnk-os), [`sys/prog/`](#path-sys-prog), [`sys/scr/`](#path-sys-scr), [`sys/vm/`](#path-sys-vm), [`ws/`](#path-ws), [`ws/lib/`](#path-ws-lib), [`ws/tmpl/`](#path-ws-tmpl), [`ws/tool/`](#path-ws-tool)
- `temporary` - [`area/lrn/`](#path-area-lrn), [`prj/`](#path-prj), [`task/`](#path-task)
- `transient` - [`inbox/`](#path-inbox), [`tmp/`](#path-tmp)

**By `origin`:**

- `external` - [`area/`](#path-area), [`area/3dp/`](#path-area-3dp), [`area/fin/`](#path-area-fin), [`area/inv/item/`](#path-area-inv-item), [`area/lrn/`](#path-area-lrn), [`area/paper/`](#path-area-paper), [`inbox/`](#path-inbox), [`media/`](#path-media), [`media/book/`](#path-media-book), [`media/cam/`](#path-media-cam), [`media/music/`](#path-media-music), [`media/pic/`](#path-media-pic), [`media/vid/`](#path-media-vid), [`res/`](#path-res), [`strg/`](#path-strg), [`strg/app/`](#path-strg-app), [`strg/bkup/`](#path-strg-bkup), [`strg/driver/`](#path-strg-driver), [`strg/unk/`](#path-strg-unk), [`sys/`](#path-sys), [`sys/prog/`](#path-sys-prog), [`sys/scr/`](#path-sys-scr), [`sys/vm/`](#path-sys-vm), [`task/`](#path-task), [`tmp/`](#path-tmp), [`ws/`](#path-ws), [`ws/lib/`](#path-ws-lib), [`ws/tmpl/`](#path-ws-tmpl), [`ws/tool/`](#path-ws-tool)
- `generated` - [`area/3dp/`](#path-area-3dp), [`area/inv/`](#path-area-inv), [`strg/unk/`](#path-strg-unk), [`sys/lnk/cur/`](#path-sys-lnk-cur), [`sys/lnk/nav/`](#path-sys-lnk-nav), [`tmp/`](#path-tmp)
- `self` - [`area/`](#path-area), [`area/3dp/`](#path-area-3dp), [`area/fin/`](#path-area-fin), [`area/infra/`](#path-area-infra), [`area/inv/`](#path-area-inv), [`area/lrn/`](#path-area-lrn), [`area/rc/`](#path-area-rc), [`area/std/`](#path-area-std), [`knwl/`](#path-knwl), [`media/`](#path-media), [`media/cam/`](#path-media-cam), [`prj/`](#path-prj), [`prj/_arch/`](#path-prj-arch), [`strg/`](#path-strg), [`strg/bkup/`](#path-strg-bkup), [`strg/game/`](#path-strg-game), [`sys/`](#path-sys), [`sys/lnk/`](#path-sys-lnk), [`sys/lnk/cur/`](#path-sys-lnk-cur), [`sys/lnk/nav/`](#path-sys-lnk-nav), [`sys/lnk/os/`](#path-sys-lnk-os), [`sys/scr/`](#path-sys-scr), [`task/`](#path-task), [`task/_arch/`](#path-task-arch), [`tmp/`](#path-tmp), [`ws/`](#path-ws), [`ws/lib/`](#path-ws-lib), [`ws/tmpl/`](#path-ws-tmpl), [`ws/tool/`](#path-ws-tool)

<a id="path-area"></a>
### `area/`

| Field | Value |
|---|---|
| Purpose | Long-lived areas of responsibility, ownership, or interest. |
| Notes | Areas require maintenance but do not have a fixed completion date. If it can be finished, it is a project or a task. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums), [`self`](#section-enums) |

**Use for:**

- long-term responsibilities
- hobbies

**Not for:**

- storing referential materials
- projects or tasks

**See also:**

- prj/
- task/

<a id="path-area-3dp"></a>
### `area/3dp/`

| Field | Value |
|---|---|
| Purpose | 3D printing hobby and its associated files. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- printable models and print-related records
- 3D printing activity and results

**Not for:**

- active design projects
- general 3D printing knowledge

**See also:**

- prj/
- knwl/

<a id="path-area-fin"></a>
### `area/fin/`

| Field | Value |
|---|---|
| Purpose | Personal financial administration. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- bank documents
- investment documents
- tax documents
- payslips
- invoices

**Not for:**

- shopping

**See also:**

- area/paper/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`file-extensions-v1`](#rule-file-extensions-v1) | financial records must stay documents; anything else here arrived by accident | `allowed=["pdf", "xlsx"]` |

<a id="path-area-infra"></a>
### `area/infra/`

| Field | Value |
|---|---|
| Purpose | Infrastructure documentation. |
| Notes | Separated by system. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- documentation
- records
- documentation of how systems work together

**Not for:**

- files consumed by the system
- technical reference material

**See also:**

- sys/

<a id="path-area-inv"></a>
### `area/inv/`

| Field | Value |
|---|---|
| Purpose | Inventory of owned items. |
| Notes | Indexes describing collections of items. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- inventory indexes

**Not for:**

- reference materials unrelated to owned items
- shopping materials

**See also:**

- area/inv/item/

<a id="path-area-inv-item"></a>
### `area/inv/item/`

| Field | Value |
|---|---|
| Purpose | Information belonging to individual owned items. |
| Notes | Separated by item. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- manuals
- warranties
- photos
- specifications
- configuration information

**Not for:**

- indexes of multiple items
- general items information

**See also:**

- area/inv/

<a id="path-area-lrn"></a>
### `area/lrn/`

| Field | Value |
|---|---|
| Purpose | Active learning subjects. |
| Notes | Similar to projects, but the output is knowledge rather than a product. |
| Lifecycle | [`temporary`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- study notes
- exercises
- learning plans
- links to resources

**Not for:**

- finished distilled knowledge
- storing resources

**See also:**

- res/
- knwl/

<a id="path-area-paper"></a>
### `area/paper/`

| Field | Value |
|---|---|
| Purpose | Official documents that are retained as records. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- scanned documents
- electronic documents

**Not for:**

- unofficial documents
- actively managed domains

**See also:**

- area/fin/

<a id="path-area-rc"></a>
### `area/rc/`

| Field | Value |
|---|---|
| Purpose | RC hobby and its associated working material. |
| Notes | Should include links to RC related folders. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- RC hobby activity and experiments
- RC-specific working material and test results

**Not for:**

- photos/videos related to RC
- personal firmware/PCB projects
- general technical material

**See also:**

- prj/
- res/
- knwl/
- area/inv/
- media/cam/

<a id="path-area-std"></a>
### `area/std/`

| Field | Value |
|---|---|
| Purpose | Personal standards and conventions. |
| Notes | This file's own home. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- infrastructure conventions
- naming conventions
- workflow standards
- filesystem organization standards

**Not for:**

- configuration files
- transient notes
- documentation

**See also:**

- sys/scr/
- area/infra/

<a id="path-inbox"></a>
### `inbox/`

| Field | Value |
|---|---|
| Purpose | Temporary location for files that have not yet been classified. |
| Notes | Files must eventually be moved to their final location, deleted, transformed into knowledge, or archived. |
| Lifecycle | [`transient`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- newly acquired files

**Not for:**

- permanent files

**See also:**

- tmp/
- _inbox
- _unsorted

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`empty-v1`](#rule-empty-v1) | a zero-byte file here is a failed transfer, not something waiting to be filed | `check_folders=false` |
| [`staleness-v1`](#rule-staleness-v1) | an arrival that survives a month in the inbox is being avoided, not triaged | `mode="stale"`, `threshold="1m"`, `destination="inbox/_unsorted"`, `create_destination=true`, `exclude=["_*", ".*"]` |

<a id="path-knwl"></a>
### `knwl/`

| Field | Value |
|---|---|
| Purpose | Personal distilled knowledge. |
| Notes | Used with Obsidian. A completed note must not exist simultaneously with its source in res/ - enforced by the cross-path rule at the end of this section. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- self-written notes
- distilled references
- personal cheat sheets
- processed external information

**Not for:**

- raw downloaded references
- manuals
- unprocessed documents

**See also:**

- res/
- area/lrn/

<a id="path-media"></a>
### `media/`

| Field | Value |
|---|---|
| Purpose | Entertainment media. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- leisure books
- downloaded videos
- pictures and wallpapers
- personal photos

**Not for:**

- technical literature
- video courses

**See also:**

- res/

<a id="path-media-book"></a>
### `media/book/`

| Field | Value |
|---|---|
| Purpose | Books intended for leisure reading. |
| Notes | Separated by genre. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- fiction
- popular science
- philosophy
- biographies

**Not for:**

- technical references
- manuals
- datasheets

**See also:**

- res/

<a id="path-media-cam"></a>
### `media/cam/`

| Field | Value |
|---|---|
| Purpose | Personal photos and video. |
| Notes | Separated by year and optionally date. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- personal photography
- personal videography

**Not for:**

- project photos
- inventory photos

**See also:**

- area/inv/item/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`duplicate-files-v1`](#rule-duplicate-files-v1) | a re-imported card silently doubles the library; only content hashing finds it | `recursive=true`, `min_size=65536` |
| [`timestamp-consistency-v1`](#rule-timestamp-consistency-v1) | a photo filed under a date that contradicts its own name is lost, not misfiled | `recursive=true` |
| [`timestamp-format-v1`](#rule-timestamp-format-v1) | mixed date spellings in one tree break every sort and every range query over it | `formats=["%Y-%m-%d", "%Y%m%d_%H%M%S"]`, `target="both"` |

<a id="path-media-music"></a>
### `media/music/`

| Field | Value |
|---|---|
| Purpose | Music collection. |
| Notes | Separated primarily by artist. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- songs

**Not for:**

- sounds
- ringtones

<a id="path-media-pic"></a>
### `media/pic/`

| Field | Value |
|---|---|
| Purpose | Pictures. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- wallpapers
- pictures
- funny images

**Not for:**

- general personal photos
- general project photos

**See also:**

- media/cam/

<a id="path-media-vid"></a>
### `media/vid/`

| Field | Value |
|---|---|
| Purpose | Videos. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- general videos
- ambient videos
- home theater demos

**Not for:**

- movies
- series
- courses
- personal videography

**See also:**

- media/cam/

<a id="path-prj"></a>
### `prj/`

| Field | Value |
|---|---|
| Purpose | Active projects. |
| Notes | A project is a transient effort which produces an outcome based on defined goals. |
| Lifecycle | [`temporary`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- software/firmware projects
- PCB projects
- other multi-session efforts

**Not for:**

- small tasks
- reusable resources

**See also:**

- task/
- prj/_arch/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`staleness-v1`](#rule-staleness-v1) | a project untouched for half a year is finished or abandoned; leaving it in prj/ hides the ones that aren't | `mode="stale"`, `threshold="6m"`, `destination="prj/_arch/%Y"`, `create_destination=true`, `exclude=["_*", ".*"]` |

<a id="path-prj-arch"></a>
### `prj/_arch/`

| Field | Value |
|---|---|
| Purpose | Inactive projects. |
| Notes | Separated by year. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- completed projects
- abandoned projects
- paused projects
- obsolete projects

**Not for:**

- active projects
- backups

**See also:**

- prj/
- _arch

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`naming-pattern-v1`](#rule-naming-pattern-v1) | the archive is only navigable while every folder at this level is a year | `pattern="^[0-9]{4}$"`, `mode="allow"`, `target="folders"`, `recursive=false` |

<a id="path-res"></a>
### `res/`

| Field | Value |
|---|---|
| Purpose | External knowledge materials. |
| Notes | Organized by subject. Must mirror knwl/'s structure. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- datasheets
- application notes
- technical literature
- courses
- tutorials
- cheat-sheets

**Not for:**

- distilled knowledge
- device manuals
- project files

**See also:**

- knwl/
- area/lrn/

<a id="path-strg"></a>
### `strg/`

| Field | Value |
|---|---|
| Purpose | Long-term storage for files that are rarely accessed but need to be preserved. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- backups
- installers
- game saves

**Not for:**

- backup scripts
- game reference materials

**See also:**

- sys/

<a id="path-strg-app"></a>
### `strg/app/`

| Field | Value |
|---|---|
| Purpose | Application installers. |
| Notes | Separated by platform. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- applications
- games

**Not for:**

- installed applications/games
- application/games configuration
- game saves

**See also:**

- sys/prog/

<a id="path-strg-bkup"></a>
### `strg/bkup/`

| Field | Value |
|---|---|
| Purpose | Recovery data. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- system backups
- device backups
- configuration backups
- binary dumps used for restoration

**Not for:**

- scripts
- active files

**See also:**

- sys/scr/

<a id="path-strg-driver"></a>
### `strg/driver/`

| Field | Value |
|---|---|
| Purpose | Hardware drivers. |
| Notes | Separated by platform. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- vendor driver packages
- hardware support packages

**Not for:**

- applications
- hardware documentation

**See also:**

- strg/app/

<a id="path-strg-game"></a>
### `strg/game/`

| Field | Value |
|---|---|
| Purpose | Game saves. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- saves

**Not for:**

- game reference
- game clips

**See also:**

- strg/app/

<a id="path-strg-unk"></a>
### `strg/unk/`

| Field | Value |
|---|---|
| Purpose | Unknown files that might be important. |
| Notes | A holding pen, not a destination: anything identified here moves to where it belongs. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`external`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- unknown encryption keys
- unknown binaries

**Not for:**

- files with known purpose

**See also:**

- inbox/

<a id="path-sys"></a>
### `sys/`

| Field | Value |
|---|---|
| Purpose | Files consumed by this system and specific to it. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- machine specific scripts
- virtual machines
- portable programs
- virtual views

**Not for:**

- project dependencies
- documentation

**See also:**

- area/infra/
- ws/

<a id="path-sys-lnk"></a>
### `sys/lnk/`

| Field | Value |
|---|---|
| Purpose | Curated navigation spaces. |
| Notes | Nothing is stored here; every leaf points somewhere else. The two rules below apply to the whole subtree, so cur/, nav/ and os/ declare none of their own. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- navigation links
- custom views of the filesystem

**Not for:**

- canonical file storage
- machine-specific files unrelated to navigation

**See also:**

- sys/lnk/cur/
- sys/lnk/nav/
- sys/lnk/os/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`link-integrity-v1`](#rule-link-integrity-v1) | a dangling entry in a navigation space is worse than a missing one - it looks navigable | `recursive=true`, `follow_chains=true` |
| [`link-policy-v1`](#rule-link-policy-v1) | a real file in a navigation view is a file that exists only here, where nothing looks for it | `files="forbidden"`, `folders="allowed"`, `links="required"`, `recursive=true`, `exclude=[".*", "*/.*"]` |

<a id="path-sys-lnk-cur"></a>
### `sys/lnk/cur/`

| Field | Value |
|---|---|
| Purpose | Links to files and folders currently being worked on or used. |
| Notes | Contents change as current work and interests change. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- current projects, tasks, and other work
- currently used books and resources

**Not for:**

- long-term navigation links

**See also:**

- prj/
- task/
- res/
- knwl/

<a id="path-sys-lnk-nav"></a>
### `sys/lnk/nav/`

| Field | Value |
|---|---|
| Purpose | Curated navigation view of frequently accessed locations. |
| Notes | Organized for navigation rather than by the purpose of the linked files. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- frequently accessed locations
- convenient groupings of locations

**Not for:**

- temporary current-work links

**See also:**

- sys/lnk/cur/

<a id="path-sys-lnk-os"></a>
### `sys/lnk/os/`

| Field | Value |
|---|---|
| Purpose | Links to OS specific locations. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- special OS locations with configuration files

**Not for:**

- general purpose OS locations

**See also:**

- area/infra/

<a id="path-sys-prog"></a>
### `sys/prog/`

| Field | Value |
|---|---|
| Purpose | Installed programs. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- portable programs
- AppImages
- manually installed applications
- Wine prefixes

**Not for:**

- installers
- project tools

**See also:**

- ws/tool/
- strg/app/

<a id="path-sys-scr"></a>
### `sys/scr/`

| Field | Value |
|---|---|
| Purpose | Machine-specific scripts. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- system helper scripts
- startup scripts
- maintenance scripts
- automation scripts

**Not for:**

- project scripts
- snippets

**See also:**

- prj/
- area/std/

<a id="path-sys-vm"></a>
### `sys/vm/`

| Field | Value |
|---|---|
| Purpose | Virtual machines. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- VM images
- VM configurations

**Not for:**

- VM backups

**See also:**

- strg/bkup/

<a id="path-task"></a>
### `task/`

| Field | Value |
|---|---|
| Purpose | Small tasks with defined goals. |
| Notes | Tasks are smaller than projects in regards to effort and complexity. |
| Lifecycle | [`temporary`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- writing scripts
- measurements
- investigations
- comparisons
- one-off activities

**Not for:**

- creating distilled knowledge
- complex scripts

**See also:**

- prj/
- task/_arch/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`staleness-v1`](#rule-staleness-v1) | a task open for a quarter has outgrown being a task; archive it or promote it to a project | `mode="stale"`, `threshold="3m"`, `destination="task/_arch/%Y"`, `create_destination=true`, `exclude=["_*", ".*"]` |

<a id="path-task-arch"></a>
### `task/_arch/`

| Field | Value |
|---|---|
| Purpose | Inactive tasks. |
| Notes | Separated by year. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums) |

**Use for:**

- completed tasks
- abandoned tasks
- paused tasks
- obsolete tasks

**Not for:**

- active tasks

**See also:**

- task/
- _arch

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`naming-pattern-v1`](#rule-naming-pattern-v1) | the archive is only navigable while every folder at this level is a year | `pattern="^[0-9]{4}$"`, `mode="allow"`, `target="folders"`, `recursive=false` |

<a id="path-tmp"></a>
### `tmp/`

| Field | Value |
|---|---|
| Purpose | Transient files. |
| Notes | Separated by activity or collection. A sub-folder name may identify a deletion trigger. |
| Lifecycle | [`transient`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums), [`generated`](#section-enums) |

**Use for:**

- files that are known to be disposable
- temporary collections associated with an activity or event

**Not for:**

- files whose destination has not yet been decided
- files that may need to be retained indefinitely

**See also:**

- inbox/
- task/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`staleness-v1`](#rule-staleness-v1) | a file declared disposable a month ago and still here was never actually decided about | `mode="stale"`, `threshold="1m"`, `destination="inbox"`, `exclude=["_*", ".*"]` |

<a id="path-ws"></a>
### `ws/`

| Field | Value |
|---|---|
| Purpose | Reusable assets and building blocks. |
| Notes | Primarily for projects, but not specific to one project. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- libraries and SDKs
- development tools
- templates

**Not for:**

- project-specific dependencies

**See also:**

- prj/
- sys/

<a id="path-ws-lib"></a>
### `ws/lib/`

| Field | Value |
|---|---|
| Purpose | Libraries and dependencies. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- reusable libraries
- vendor libraries
- SDKs

**Not for:**

- frozen dependencies
- project-specific libraries

**See also:**

- prj/

<a id="path-ws-tmpl"></a>
### `ws/tmpl/`

| Field | Value |
|---|---|
| Purpose | Reusable starting points. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- project templates
- configuration templates

**Not for:**

- projects
- directly usable files

**See also:**

- prj/

<a id="path-ws-tool"></a>
### `ws/tool/`

| Field | Value |
|---|---|
| Purpose | Tools that support projects. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- development utilities
- helper programs
- CLI tools

**Not for:**

- general applications

**See also:**

- sys/prog/

<a id="section-cross"></a>
## Cross-Path Sets

<a id="cross-1"></a>
### Set 1

**Members**: [`knwl/`](#path-knwl), [`res/`](#path-res)

```mermaid
graph LR
    cs["Set 1"]
    m0["knwl/"]
    cs --- m0
    m1["res/"]
    cs --- m1
```

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`basename-sync-v1`](#rule-basename-sync-v1) | source material that has been completely distilled must be removed; a name in both halves means it wasn't | `mode="exclusive"`, `recursive=true` |

<a id="section-folders"></a>
## Reserved Folders

Reserved-name prefix: `_`

**By `lifecycle`:**

- `archival` - [`_arch`](#folder-arch)
- `ongoing` - [`_util`](#folder-util)
- `transient` - [`_inbox`](#folder-inbox), [`_unsorted`](#folder-unsorted)

**By `origin`:**

- `external` - [`_arch`](#folder-arch), [`_inbox`](#folder-inbox), [`_unsorted`](#folder-unsorted), [`_util`](#folder-util)
- `self` - [`_arch`](#folder-arch), [`_unsorted`](#folder-unsorted), [`_util`](#folder-util)

<a id="folder-arch"></a>
### `_arch`

| Field | Value |
|---|---|
| Purpose | Archive of inactive information/containers. |
| Notes | Indicates that contents are no longer part of the active workflow. Exception to the principle of tagging state rather than moving things. |
| Lifecycle | [`archival`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- projects/tasks that are no longer active
- domains that are no longer maintained
- non-versioned but obsolete files

**Not for:**

- general archival
- backups

**See also:**

- prj/_arch/
- task/_arch/
- strg/

<a id="folder-inbox"></a>
### `_inbox`

| Field | Value |
|---|---|
| Purpose | Local landing zone for arrivals belonging to the parent directory. |
| Notes | The inline counterpart to inbox/: something arrived for this area specifically, but where it goes inside it hasn't been decided. Distinct from _unsorted, where the destination IS known and only the shelf isn't. |
| Lifecycle | [`transient`](#section-enums) |
| Origin | [`external`](#section-enums) |

**Use for:**

- newly acquired files that clearly belong to this area
- downloads collected during one activity

**Not for:**

- files whose area hasn't been decided at all
- files already known to belong somewhere specific here

**See also:**

- inbox/
- _unsorted

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`empty-v1`](#rule-empty-v1) | a zero-byte file here is a failed transfer, not something waiting to be filed | `check_folders=false` |

<a id="folder-unsorted"></a>
### `_unsorted`

| Field | Value |
|---|---|
| Purpose | Local unsorted files. |
| Notes | Files that belong under the parent directory but need additional classification. Unlike _inbox, the destination is already known - only the shelf isn't. |
| Lifecycle | [`transient`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- files awaiting classification
- transient holding area during organization
- files returned from original organization

**Not for:**

- general transient files
- long-term storage
- archived information

**See also:**

- inbox/
- tmp/

<a id="folder-util"></a>
### `_util`

| Field | Value |
|---|---|
| Purpose | Frequently used utilities related to the parent directory. |
| Notes | Contains links to utilities that are commonly used with the parent directory. |
| Lifecycle | [`ongoing`](#section-enums) |
| Origin | [`self`](#section-enums), [`external`](#section-enums) |

**Use for:**

- links to applications
- scripts
- directory-specific workflows

**Not for:**

- general applications
- general scripts
- installers

**See also:**

- sys/scr/
- sys/prog/
- ws/tool/

**Attached rules:**

| Rule | Reason | Params |
|---|---|---|
| [`link-integrity-v1`](#rule-link-integrity-v1) | a shortcut to a utility outlives the utility, and nothing about the folder looks wrong when it does | `recursive=true` |

<a id="section-rules"></a>
## Rules

```mermaid
graph LR
    r0["basename-sync-v1"]
    r1["duplicate-files-v1"]
    r2["empty-v1"]
    r3["file-extensions-v1"]
    r4["link-integrity-v1"]
    r5["link-policy-v1"]
    r6["naming-pattern-v1"]
    r7["spelling-abbreviations-v1"]
    r8["staleness-v1"]
    r9["timestamp-consistency-v1"]
    r10["timestamp-format-v1"]
    r11["uncataloged-reserved-v1"]
    s0("Cross-Path Set 1")
    s1("area/fin/")
    s2("every folder under root (blanket)")
    s3("folders.reserved.'_inbox'")
    s4("folders.reserved.'_util'")
    s5("inbox/")
    s6("media/cam/")
    s7("prj/")
    s8("prj/_arch/")
    s9("sys/lnk/")
    s10("task/")
    s11("task/_arch/")
    s12("tmp/")
    r0 --- s0
    r1 --- s6
    r2 --- s5
    r2 --- s3
    r3 --- s1
    r4 --- s9
    r4 --- s4
    r5 --- s9
    r6 --- s8
    r6 --- s11
    r6 --- s2
    r7 --- s2
    r8 --- s5
    r8 --- s7
    r8 --- s10
    r8 --- s12
    r9 --- s6
    r10 --- s6
    r11 --- s2
```

<a id="rule-basename-sync-v1"></a>
### `basename-sync-v1`

Checks whether 2+ paths agree on which files exist by name (ignoring or comparing extensions) - e.g. a lossless library that should have a matching lossy mirror, or a not-processed/processed pair where the source should disappear once processed.

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `cross` |
| Fixable | yes |

**Params:**

| Name | Default | Required |
|---|---|---|
| `mode` |  | yes |
| `recursive` | `true` | no |
| `extensions` | `[]` | no |
| `exclude` | `[]` | no |
| `fixer_script` | `""` | no |

**Attached at 1 location(s):**

- [`Cross-Path Set 1`](#cross-1) - source material that has been completely distilled must be removed; a name in both halves means it wasn't

<a id="rule-duplicate-files-v1"></a>
### `duplicate-files-v1`

Finds byte-identical files by content hash - either within a single path (scope=single) or only across the given paths (scope=cross), e.g. the same photo sitting in both an inbox and its filed destination. Hashes are cached on disk and reused until a file's size or mtime changes.

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `warn` |
| Scope | `both` |
| Fixable | no |

**Params:**

| Name | Default | Required |
|---|---|---|
| `recursive` | `true` | no |
| `extensions` | `[]` | no |
| `exclude` | `[]` | no |
| `min_size` | `1` | no |
| `algorithm` | `"blake2b"` | no |
| `cache` | `true` | no |
| `cache_ttl_days` | `30` | no |

**Attached at 1 location(s):**

- [`media/cam/`](#path-media-cam) - a re-imported card silently doubles the library; only content hashing finds it

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

**Attached at 2 location(s):**

- [`folders.reserved."_inbox"`](#folder-inbox) - a zero-byte file here is a failed transfer, not something waiting to be filed
- [`inbox/`](#path-inbox) - a zero-byte file here is a failed transfer, not something waiting to be filed

<a id="rule-file-extensions-v1"></a>
### `file-extensions-v1`

Checks that every file under the path has an allowed extension, or does not have a disallowed one - exactly one of the two lists is used per attachment.

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
| `allowed` | `[]` | no |
| `disallowed` | `[]` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- [`area/fin/`](#path-area-fin) - financial records must stay documents; anything else here arrived by accident

<a id="rule-link-integrity-v1"></a>
### `link-integrity-v1`

Reports links whose target no longer exists - symlinks, XDG .desktop entries, Windows .lnk/.url shortcuts, and macOS .webloc bookmarks.

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
| `kinds` | `["symlink", "desktop", "shortcut", "webloc"]` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |
| `foreign_links` | `"skip"` | no |
| `follow_chains` | `true` | no |

**Attached at 2 location(s):**

- [`folders.reserved."_util"`](#folder-util) - a shortcut to a utility outlives the utility, and nothing about the folder looks wrong when it does
- [`sys/lnk/`](#path-sys-lnk) - a dangling entry in a navigation space is worse than a missing one - it looks navigable

<a id="rule-link-policy-v1"></a>
### `link-policy-v1`

Constrains which kinds of entry may appear under a path - real files, folders, and links each independently required, allowed, or forbidden.

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
| `files` | `"allowed"` | no |
| `folders` | `"allowed"` | no |
| `links` | `"allowed"` | no |
| `link_kinds` | `["symlink", "desktop", "shortcut", "webloc"]` | no |
| `recursive` | `false` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- [`sys/lnk/`](#path-sys-lnk) - a real file in a navigation view is a file that exists only here, where nothing looks for it

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

**Attached at 3 location(s):**

- `every folder under root (blanket)` - a name that can't survive a copy to a FAT-formatted drive fails silently, years after it was written
- [`prj/_arch/`](#path-prj-arch) - the archive is only navigable while every folder at this level is a year
- [`task/_arch/`](#path-task-arch) - the archive is only navigable while every folder at this level is a year

<a id="rule-spelling-abbreviations-v1"></a>
### `spelling-abbreviations-v1`

Checks that words in file/folder names are either spelled correctly or are known abbreviations - catches typos and undocumented shorthand before they spread across a tree.

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
| `abbreviations` |  | yes |
| `languages` | `["en"]` | no |
| `min_word_length` | `3` | no |
| `ignore` | `[]` | no |
| `numbers_ok` | `true` | no |
| `target` | `"both"` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- `every folder under root (blanket)` - folder names are the standard's vocabulary; an undeclared shorthand today is an inconsistent one next year

<a id="rule-staleness-v1"></a>
### `staleness-v1`

Checks each direct child of a path against an age threshold - either flagging things that have gone stale (mode="stale", for active folders that should stay current) or things that are unexpectedly active (mode="active", for archive folders that shouldn't be seeing new activity).

| | |
|---|---|
| Tier | bundled |
| Version | 1.1 |
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
| `create_destination` | `false` | no |
| `exclude` | `[]` | no |

**Attached at 4 location(s):**

- [`inbox/`](#path-inbox) - an arrival that survives a month in the inbox is being avoided, not triaged
- [`prj/`](#path-prj) - a project untouched for half a year is finished or abandoned; leaving it in prj/ hides the ones that aren't
- [`task/`](#path-task) - a task open for a quarter has outgrown being a task; archive it or promote it to a project
- [`tmp/`](#path-tmp) - a file declared disposable a month ago and still here was never actually decided about

<a id="rule-timestamp-consistency-v1"></a>
### `timestamp-consistency-v1`

Checks that a file or folder's embedded timestamp is consistent with the timestamps embedded in its ancestor folder names - a file dated 2026-03-06 inside a 2026-03-05 folder is a contradiction, even though both are individually valid dates.

| | |
|---|---|
| Tier | bundled |
| Version | 1.0 |
| Severity | `error` |
| Scope | `single` |
| Fixable | no |

**Params:**

| Name | Default | Required |
|---|---|---|
| `recursive` | `true` | no |
| `require_all_components_timestamped` | `false` | no |

**Attached at 1 location(s):**

- [`media/cam/`](#path-media-cam) - a photo filed under a date that contradicts its own name is lost, not misfiled

<a id="rule-timestamp-format-v1"></a>
### `timestamp-format-v1`

Checks that any name whose leading characters form a real calendar date or datetime uses one of the standard's accepted formats - a name with no such leading timestamp at all is left alone, not flagged.

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
| `formats` |  | yes |
| `target` | `"both"` | no |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- [`media/cam/`](#path-media-cam) - mixed date spellings in one tree break every sort and every range query over it

<a id="rule-uncataloged-reserved-v1"></a>
### `uncataloged-reserved-v1`

Checks for folders that use the standard's reserved-name prefix (e.g. "_") but aren't cataloged under [folders.reserved."..."] - a folder that LOOKS reserved but isn't documented.

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
| `prefix` | `"_"` | no |
| `cataloged` |  | yes |
| `recursive` | `true` | no |
| `exclude` | `[]` | no |

**Attached at 1 location(s):**

- `every folder under root (blanket)` - a folder that looks reserved but isn't documented is an undeclared convention spreading through the tree

<a id="section-enums"></a>
## Enums

**`enums.paths.lifecycle`:**

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

**`enums.paths.origin`:**

| Value | Meaning |
|---|---|
| `self` | authored directly by you - nothing to re-fetch or resync from elsewhere |
| `external` | sourced from outside this system - downloaded, received, or otherwise not authored by you |
| `generated` | produced automatically by a tool, script, or model - not hand-authored, not fetched externally |

**`enums.folders.lifecycle`:**

| Value | Meaning |
|---|---|
| `transient` | meant to be emptied constantly, nothing lingers |
| `temporary` | has a completion condition, then gets archived |
| `ongoing` | continuously active/maintained, no end state |
| `archival` | already at rest, rarely touched |

**`enums.folders.origin`:**

| Value | Meaning |
|---|---|
| `self` | authored directly by you - nothing to re-fetch or resync from elsewhere |
| `external` | sourced from outside this system - downloaded, received, or otherwise not authored by you |
| `generated` | produced automatically by a tool, script, or model - not hand-authored, not fetched externally |

<a id="section-abbreviations"></a>
## Abbreviations

| Abbreviation | Meaning |
|---|---|
| `3dp` | 3D printing |
| `app` | Application |
| `arch` | Archive |
| `area` | Area of responsibility |
| `bkup` | Backup |
| `cam` | Camera |
| `cur` | Current |
| `embd` | Embedded |
| `fin` | Finance |
| `fw` | Firmware |
| `infra` | Infrastructure |
| `inv` | Inventory |
| `item` | Individual owned item |
| `knwl` | Knowledge |
| `lib` | Library |
| `lnk` | Link |
| `lrn` | Learn |
| `med` | Medical |
| `nav` | Navigation |
| `ndx` | Index |
| `pic` | Picture |
| `prj` | Project |
| `prog` | Program |
| `rc` | Radio control |
| `res` | Resource |
| `scr` | Script |
| `std` | Standard |
| `strg` | Storage |
| `sys` | System |
| `task` | Task |
| `tmp` | Temporary |
| `tmpl` | Template |
| `tool` | Tool |
| `unk` | Unknown |
| `util` | Utility |
| `vid` | Video |
| `vm` | Virtual machine |
| `ws` | Workspace |

