#!/usr/bin/env python3
"""
Start a new fs-org-kit rule from one of the bundled templates.

Copies rules/_template-<scope>-v1/ to <dir>/<rule-id>/, renames every
file after the new directory, and rewrites the rule id inside them. That
copy is the whole job: the templates are complete, tested, runnable rules
(see rules/_template-single-v1/), so there is no second skeleton here to
drift out of sync with them.

    python .claude/skills/new-rule/scaffold_rule.py size-limit-v1 \
        --purpose "Checks no file exceeds a size threshold." \
        --scope single --fixer

Everything else - severity, params, uses_cache, [sandbox] - is a
one-line edit in the manifest the copy leaves you with, and the template
comments say what each one does.
"""

import argparse
import re
import shutil
import sys
from pathlib import Path

DIR_NAME = re.compile(r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<major>\d+)$")
TEMPLATE_ROOT = Path(__file__).resolve().parents[3] / "rules"
PURPOSE_LINE = re.compile(r'^purpose = ".*"$', re.MULTILINE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rule_id", help="directory name, e.g. size-limit-v1")
    parser.add_argument("--purpose", default="", help="one sentence, shown in generated docs")
    parser.add_argument("--scope", default="single", choices=["single", "cross", "both"])
    parser.add_argument("--fixer", action="store_true",
                        help="keep the template's -fix.py (dropped by default: "
                             "check-only is a normal, permanent design)")
    parser.add_argument("--dir", default="rules", help="tier directory (default: rules)")
    args = parser.parse_args()

    match = DIR_NAME.match(args.rule_id)
    if not match:
        print(f"error: rule id must match <name>-v<major>, got: {args.rule_id}", file=sys.stderr)
        return 1
    if not args.purpose:
        print("error: --purpose is required - an undocumented rule is one "
              "nobody else can safely attach", file=sys.stderr)
        return 1

    rule_id = args.rule_id
    template_id = f"_template-{args.scope}-v1"
    template = TEMPLATE_ROOT / template_id
    if not template.is_dir():
        print(f"error: no template at {template}", file=sys.stderr)
        return 1

    target = Path(args.dir) / rule_id
    if target.exists():
        print(f"error: already exists: {target}", file=sys.stderr)
        return 1

    shutil.copytree(template, target,
                    ignore=shutil.ignore_patterns("__pycache__", ".*"))
    if not args.fixer:
        (target / f"{template_id}-fix.py").unlink()

    for child in sorted(target.iterdir()):
        text = child.read_text().replace(template_id, rule_id)
        if child.suffix == ".toml":
            # The template's header explains how to copy it, which the
            # copy no longer needs; --purpose replaces the placeholder.
            text = text.split("\n\n", 1)[1]
            text = PURPOSE_LINE.sub(f'purpose = "{args.purpose.replace(chr(34), chr(39))}"', text, count=1)
        child.write_text(text)
        renamed = child.name.replace(template_id, rule_id).replace(
            template_id.replace("-", "_"), rule_id.replace("-", "_"))
        child.rename(target / renamed)

    # The manifest's version major is part of the rule's identity and has
    # to match the directory it now lives in.
    manifest = target / f"{rule_id}.toml"
    manifest.write_text(re.sub(r'^version = "\d+\.',
                               f'version = "{match.group("major")}.',
                               manifest.read_text(), count=1, flags=re.MULTILINE))

    print(f"scaffolded {target}/ from {template_id}")
    for child in sorted(target.iterdir()):
        print(f"  {child.name}")
    print(f"\nnext: set severity and params in {manifest.name}, fill in the "
          f"check, then `pytest {target}/ -v`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
