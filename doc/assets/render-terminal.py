#!/usr/bin/env python3
"""
Renders the terminal screenshots in README.md as SVG.

The captures are real output - run the command in `examples/para/`,
paste what it printed into the SESSIONS table below, and re-run this:

    python doc/assets/render-terminal.py

Text is laid out on a fixed character grid (every run is positioned by
column and pinned with `textLength`), so the image looks the same
whichever monospace font the reader's browser picks.

Styles map to the ANSI colours the tools actually emit - `yellow` is
`\\033[33m` (violation), `green` is `\\033[32m` (fixed), `dim` is
`\\033[2m` (skipped). Anything else is default foreground.

The window is drawn as KDE's Breeze decoration - centred title, chevron
buttons on the right - over Konsole's Breeze colour scheme.
"""

from pathlib import Path

OUT = Path(__file__).parent

FONT = ('ui-monospace, SFMono-Regular, "SF Mono", Menlo, Consolas, '
        '"DejaVu Sans Mono", "Liberation Mono", monospace')
FONT_SIZE = 12
CELL_W = FONT_SIZE * 0.6
LINE_H = 19
PAD_X = 18
PAD_TOP = 14
PAD_BOTTOM = 16
BAR_H = 32
COLS = 104

# KDE Breeze window decoration.
CHROME = {
    "titlebar": "#31363b",
    "title_fg": "#b6bdc4",
    "button": "#bdc3c7",
    "border": "#3b4247",
    "bg": "#232629",       # Breeze Dark base, Konsole's background
}

# Konsole's Breeze colour scheme.
PALETTE = {
    "fg": "#eff0f1",       # Breeze foreground
    "dim": "#7f8c8d",      # \033[2m - skipped
    "yellow": "#f67400",   # \033[33m - violation
    "green": "#27ae60",    # \033[32m - fixed
    "red": "#da4453",      # \033[31m - unfixable / broken
    "accent": "#3daee9",   # Breeze blue, for the command itself
}


def wrap(line, cols):
    """Hard-wrap a styled line at `cols`, the way a terminal does -
    no indent on the continuation, styles carried across the break."""
    out, row, col = [], [], 0
    for text, style in line:
        while text:
            room = cols - col
            head, text = text[:room], text[room:]
            row.append((head, style))
            col += len(head)
            if col >= cols:
                out.append(row)
                row, col = [], 0
    out.append(row)
    return out


def escape(text):
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(title, lines, path):
    rows = [r for line in lines for r in wrap(line, COLS)]
    width = round(COLS * CELL_W + 2 * PAD_X)
    height = BAR_H + PAD_TOP + len(rows) * LINE_H + PAD_BOTTOM

    svg = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" '
        f'viewBox="0 0 {width} {height}" role="img" aria-label="{escape(title)} terminal output">',
        f"  <title>{escape(title)}</title>",
        f'  <rect width="{width}" height="{height}" rx="6" fill="{CHROME["bg"]}" '
        f'stroke="{CHROME["border"]}"/>',
        f'  <path d="M0 6a6 6 0 0 1 6-6h{width - 12}a6 6 0 0 1 6 6v{BAR_H - 6}H0z" '
        f'fill="{CHROME["titlebar"]}"/>',
        f'  <path d="M0 {BAR_H}h{width}" stroke="{CHROME["border"]}"/>',
        f'  <text x="{width / 2}" y="{BAR_H // 2 + 4}" fill="{CHROME["title_fg"]}" '
        f'font-size="11.5" text-anchor="middle" font-family=\'{FONT}\'>{escape(title)}</text>',
    ]

    # Breeze titlebar buttons, right-aligned: minimise and maximise are
    # chevrons, close is a cross. Neutral - Breeze only tints on hover.
    cy = BAR_H // 2
    glyphs = (
        "M{x} {a}L{cx} {b}L{y} {a}",              # chevron down - minimise
        "M{x} {b}L{cx} {a}L{y} {b}",              # chevron up   - maximise
        "M{x} {a}L{y} {b}M{y} {a}L{x} {b}",       # cross        - close
    )
    for i, glyph in enumerate(glyphs):
        cx = width - 70 + i * 26
        d = glyph.format(x=cx - 4, y=cx + 4, cx=cx, a=cy - 3, b=cy + 3)
        svg.append(
            f'  <path d="{d}" fill="none" stroke="{CHROME["button"]}" stroke-width="1.5" '
            f'stroke-linecap="round" stroke-linejoin="round"/>'
        )

    svg.append(f"  <g font-family='{FONT}' font-size=\"{FONT_SIZE}\" xml:space=\"preserve\">")
    for r, row in enumerate(rows):
        y = round(BAR_H + PAD_TOP + r * LINE_H + FONT_SIZE, 1)
        col = 0
        for text, style in row:
            stripped = text.strip()
            if stripped:
                x = round(PAD_X + (col + len(text) - len(text.lstrip())) * CELL_W, 1)
                svg.append(
                    f'    <text x="{x}" y="{y}" fill="{PALETTE[style]}" '
                    f'textLength="{round(len(stripped) * CELL_W, 1)}" '
                    f'lengthAdjust="spacingAndGlyphs">{escape(stripped)}</text>'
                )
            col += len(text)
    svg += ["  </g>", "</svg>", ""]

    path.write_text("\n".join(svg))
    print(f"{path.name}: {width}x{height}, {len(rows)} rows")


def prompt(command):
    binary, _, rest = command.partition(" ")
    return [("$ ", "dim"), (binary, "accent"), (" " + rest, "fg")]


def plain(text):
    return [(text, "fg")]


def status(prefix, word, style, rest):
    return [(prefix + " [", "fg"), (word, style), ("] ", "fg"), (rest, "fg")]


SESSIONS = {
    # examples/para $ fs-org-run fs-org-std.toml
    # duplicate-files-v1 reports absolute paths; the leading directories
    # are elided to "..." here, being this machine's and nobody else's.
    "fs-org-run": ("run.svg", [
        prompt("fs-org-run fs-org-std.toml"),
        [],
        status('paths."inbox/".rules.empty-v1[0]:', "VIOLATION", "yellow",
               "empty-v1 (tree/inbox): 1 empty item(s): untitled.md"),
        status('paths."projects/*/".rules.required-content-v1[0]:', "VIOLATION", "yellow",
               "required-content-v1 (tree/projects/guitar-lessons): missing required: README.md"),
        status('paths."resources/".rules.naming-pattern-v1[0]:', "VIOLATION", "yellow",
               "naming-pattern-v1 (tree/resources): 1 item(s) that doesn't match the "
               "required pattern: Screenshot 2026-07-14 at 09.41.22.png"),
        status("paths.cross[0].rules.duplicate-files-v1[0]:", "VIOLATION", "yellow",
               "duplicate-files-v1 (tree/inbox, tree/resources): 1 group(s) of identical "
               "files spanning 2+ of the given paths: [.../tree/inbox/font-pairing.md, "
               ".../tree/resources/typography/font-pairing.md]"),
        status("folders.rules.naming-pattern-v1[0]:", "VIOLATION", "yellow",
               "naming-pattern-v1 (tree): 1 item(s) that doesn't match the required "
               "pattern: areas/Car Maintenance"),
        [],
        plain("Summary"),
        plain("         ok  6"),
        [("  ", "fg"), ("violation", "yellow"), ("  5", "fg")],
        plain("      fixed  0"),
        plain("  unfixable  0"),
        plain("     broken  0"),
        plain("    skipped  0"),
        [],
        plain("11 invocation(s) total"),
    ]),

    # examples/para $ fs-org-run fs-org-std.toml --fix, after resolving
    # the five shipped mistakes and aging website-redesign past the
    # 90-day threshold. The absolute destination path is elided.
    "fs-org-run --fix": ("fix.svg", [
        prompt("fs-org-run fs-org-std.toml --fix"),
        [],
        status('paths."projects/".rules.staleness-v1[0]:', "FIXED", "green",
               "staleness-v1 (tree/projects): 1 item(s) moved to .../tree/archive"),
        status('paths."projects/*/".rules.required-content-v1[0]:', "SKIPPED", "dim",
               "required-content-v1 (tree/projects/website-redesign): no longer exists "
               "(moved or removed during this run)"),
        [],
        plain("Summary"),
        plain("         ok  9"),
        plain("  violation  0"),
        [("  ", "fg"), ("    fixed", "green"), ("  1", "fg")],
        plain("  unfixable  0"),
        plain("     broken  0"),
        [("  ", "fg"), ("  skipped", "dim"), ("  1", "fg")],
        [],
        plain("11 invocation(s) total"),
    ]),
}


if __name__ == "__main__":
    for title, (name, lines) in SESSIONS.items():
        render(title, lines, OUT / name)
