# Examples

Self-contained example standards, each with a toy filesystem to run
against. Nothing here reads or writes anything outside its own
directory.

| Example | Demonstrates |
|---|---|
| [`para/`](para/) | PARA (Projects / Areas / Resources / Archive). Glob path keys, `inherit`, and a fixer that moves a stale project into the archive. |

Each example's `root` is relative, so run its commands from that
example's own directory:

```bash
cd examples/para
fs-org-validate fs-org-std.toml   # the standard itself
fs-org-run      fs-org-std.toml   # the standard against the tree
fs-org-doc      fs-org-std.toml   # Markdown from the standard
```

## Candidates for further examples

Organization schemes that would exercise parts of the kit `para/`
doesn't reach, roughly in order of how much they'd add:

| Scheme | Would exercise |
|---|---|
| **Johnny.Decimal** — `10-19 Finance/11 Tax/11.03 …` | `naming-pattern-v1` on ID prefixes, `folder-structure-v1` on the "never more than ten" limit, `uncataloged-reserved-v1`. A structure defined almost entirely by rules the standard can check. |
| **Media library** — `Shows/Name/Season 01/S01E02.mkv` | `basename-sync-v1` across a video and subtitle tree (a cross-path rule, which `para/` has none of), `mime-type-v1`, strict `naming-pattern-v1`. |
| **Photo library by capture date** — `2026/2026-08-11/` | `timestamp-format-v1` and `timestamp-consistency-v1` against folder names, `duplicate-files-v1` (the only bundled rule that caches), RAW/JPEG pairs via `basename-sync-v1`. |
| **Notes / Zettelkasten** | `link-integrity-v1` and `link-policy-v1` over a densely cross-linked tree, `required-content-v1` for front matter. |
| **XDG base directories** — `~/.config`, `~/.local/share`, `~/.cache` | Absolute and `~`-relative path keys, one standard governing several unrelated trees. |
| **Source checkouts** — `src/<host>/<org>/<repo>` | Nested glob keys, `required-content-v1` for `README`/`LICENSE`/`.git/`, blanket `[[folders.rules]]` for build droppings. |
