#!/usr/bin/env python3
"""
Scaffold a new fs-org-kit rule directory.

Writes a manifest, a working checker, a test file, and (optionally) a
fixer - all named after the directory, since the directory name IS the
rule's identity and every file repeats it.

    python .claude/skills/new-rule/scaffold_rule.py size-limit-v1 \
        --purpose "Checks no file exceeds a size threshold." \
        --params max_size,recursive --scope single

The generated checker runs and reports `ok` immediately; fill in the
actual check where marked. Nothing here is enforced by the tooling that
isn't also enforced at discovery time - this just gets the invariants
right on the first try.
"""

import argparse
import re
import sys
from pathlib import Path

DIR_NAME = re.compile(r"^(?P<name>[a-z0-9]+(?:-[a-z0-9]+)*)-v(?P<major>\d+)$")

MANIFEST = '''version = "{major}.0"
purpose = "{purpose}"
severity = "{severity}"
scope = "{scope}"
protocol_version = "1.0"
{cache_field}
[params]
names = [{param_names}]

[params.defaults]
{param_defaults}'''

ARG_BLOCK = {
    "single": '    parser.add_argument("--path", required=True)\n',
    "cross": '    parser.add_argument("--paths", action="append", default=[])\n',
    "both": ('    parser.add_argument("--path")\n'
             '    parser.add_argument("--paths", action="append", default=[])\n'),
}

VALIDATE_BLOCK = {
    "single": '''    root = Path(args.path)
    if not root.is_dir():
        print(f"error: --path is not a directory: {root}", file=sys.stderr)
        return 1
    roots = [root]
''',
    "cross": '''    if len(args.paths) < 2:
        print("error: --paths requires 2 or more locations", file=sys.stderr)
        return 1
    roots = [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1
''',
    "both": '''    # scope = "both": the script itself must reject the ambiguous calls.
    if args.path and args.paths:
        print("error: pass --path or --paths, not both", file=sys.stderr)
        return 1
    if not args.path and not args.paths:
        print("error: one of --path or --paths is required", file=sys.stderr)
        return 1
    if args.paths and len(args.paths) < 2:
        print("error: --paths requires 2 or more locations", file=sys.stderr)
        return 1

    roots = [Path(args.path)] if args.path else [Path(p) for p in args.paths]
    for root in roots:
        if not root.is_dir():
            print(f"error: not a directory: {root}", file=sys.stderr)
            return 1
''',
}

CHECKER = '''#!/usr/bin/env python3
"""
{rule_id} - {purpose}

Checker for the fs-org-kit rule protocol (see doc/RULES.md). Prints
exactly one JSON line on stdout; exits 0 when it ran, nonzero only when
the script itself is broken.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="{purpose}")
{arg_block}    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true"){cache_arg}
    args = parser.parse_args()

    if args.fix:
        # The runner never does this - it invokes a -fix.py directly when
        # one exists. Rejecting it anyway turns a runner bug into a loud
        # failure instead of a silently wrong result.
        print("error: {fix_rejection}", file=sys.stderr)
        return 1

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {{e}}", file=sys.stderr)
        return 1

{validate_block}
    violations: list[str] = []

    # --- the actual check goes here ---------------------------------
    # Read only. Anything that mutates the filesystem belongs in a
    # separate -fix.py, never behind a flag in this file.
    for root in roots:
        _ = root

    if violations:
        print(json.dumps({{
            "status": "violation",
            "message": f"{{len(violations)}} problem(s): " + ", ".join(violations[:5]),
        }}))
    else:
        print(json.dumps({{"status": "ok"}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

FIXER = '''#!/usr/bin/env python3
"""
{rule_id} - fixer.

Self-contained: detects the problem AND resolves it in one pass. The
runner invokes this directly in --fix mode; it never runs the checker
first.
"""

import argparse
import json
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description="{purpose}")
{arg_block}    parser.add_argument("--params", required=True)
    parser.add_argument("--fix", action="store_true"){cache_arg}
    args = parser.parse_args()

    try:
        params = json.loads(args.params)
    except json.JSONDecodeError as e:
        print(f"error: --params is not valid JSON: {{e}}", file=sys.stderr)
        return 1

{validate_block}
    found: list[str] = []
    resolved: list[str] = []

    # --- detect and resolve here ------------------------------------
    for root in roots:
        _ = root

    if not found:
        print(json.dumps({{"status": "ok"}}))
    elif len(resolved) == len(found):
        print(json.dumps({{"status": "fixed", "message": f"resolved {{len(resolved)}}"}}))
    elif resolved:
        print(json.dumps({{
            "status": "violation",
            "message": f"resolved {{len(resolved)}} of {{len(found)}}",
        }}))
    else:
        print(json.dumps({{"status": "unfixable", "message": "..."}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
'''

TESTS = '''"""
Tests for {rule_id}.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "{rule_id}-check.py"


def run_check(params: dict, {run_signature}) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
{run_args}    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestBasics:

    def test_clean_directory_is_ok(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        assert verdict(run_check({{}}, {run_call})) == {{"status": "ok"}}


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({{}}, {run_call}, fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({{}}, {missing_call}).returncode != 0
'''

RUN_SHAPES = {
    "single": {
        "run_signature": "path, fix: bool = False",
        "run_args": '    argv += ["--path", str(path)]\n',
        "run_call": "tmp_path",
        "missing_call": 'tmp_path / "nope"',
    },
    "cross": {
        "run_signature": "paths, fix: bool = False",
        "run_args": '    for p in paths:\n        argv += ["--paths", str(p)]\n',
        "run_call": "[tmp_path, tmp_path]",
        "missing_call": '[tmp_path, tmp_path / "nope"]',
    },
    "both": {
        "run_signature": "path=None, paths=None, fix: bool = False",
        "run_args": ('    if path is not None:\n'
                     '        argv += ["--path", str(path)]\n'
                     '    for p in paths or []:\n'
                     '        argv += ["--paths", str(p)]\n'),
        "run_call": "tmp_path",
        "missing_call": 'tmp_path / "nope"',
    },
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("rule_id", help="directory name, e.g. size-limit-v1")
    parser.add_argument("--purpose", default="", help="one sentence, shown in generated docs")
    parser.add_argument("--severity", default="warn", choices=["none", "info", "warn", "error"])
    parser.add_argument("--scope", default="single", choices=["single", "cross", "both"])
    parser.add_argument("--params", default="", help="comma-separated param names")
    parser.add_argument("--fixer", action="store_true", help="also scaffold a -fix.py")
    parser.add_argument("--cache", action="store_true", help="declare uses_cache = true")
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
    major = match.group("major")
    target = Path(args.dir) / rule_id
    if target.exists():
        print(f"error: already exists: {target}", file=sys.stderr)
        return 1

    names = [p.strip() for p in args.params.split(",") if p.strip()]
    shape = RUN_SHAPES[args.scope]
    fmt = {
        "rule_id": rule_id,
        "purpose": args.purpose.replace('"', "'"),
        "arg_block": ARG_BLOCK[args.scope],
        "validate_block": VALIDATE_BLOCK[args.scope],
        "cache_arg": '\n    parser.add_argument("--cache-dir")' if args.cache else "",
        "fix_rejection": (f"{rule_id}: --fix belongs to {rule_id}-fix.py"
                          if args.fixer else f"{rule_id} has no fixer"),
    }

    target.mkdir(parents=True)
    (target / f"{rule_id}.toml").write_text(MANIFEST.format(
        major=major,
        purpose=fmt["purpose"],
        severity=args.severity,
        scope=args.scope,
        cache_field="uses_cache = true\n" if args.cache else "",
        param_names=", ".join(f'"{n}"' for n in names),
        param_defaults="".join(
            f"# {n} = ...   # omit to force every attachment site to supply it\n"
            for n in names),
    ))
    (target / f"{rule_id}-check.py").write_text(CHECKER.format(**fmt))
    (target / f"{rule_id}-check.py").chmod(0o755)
    if args.fixer:
        (target / f"{rule_id}-fix.py").write_text(FIXER.format(**fmt))
        (target / f"{rule_id}-fix.py").chmod(0o755)
    (target / f"test_{rule_id.replace('-', '_')}.py").write_text(
        TESTS.format(rule_id=rule_id, **shape))

    print(f"scaffolded {target}/")
    for child in sorted(target.iterdir()):
        print(f"  {child.name}")
    print("\nnext: fill in the check, then `pytest " f"{target}/ -v`")
    return 0


if __name__ == "__main__":
    sys.exit(main())
