"""
test_basename_sync_v1.py - tests for the basename-sync-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_basename_sync_v1.py -v
Or, from the project root, both bundled rules' tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

RULE_DIR = Path(__file__).resolve().parent
CHECK_SCRIPT = RULE_DIR / "basename-sync-v1-check.py"
FIX_SCRIPT = RULE_DIR / "basename-sync-v1-fix.py"


def run(script: Path, params: dict, *paths: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(script)]
    for p in paths:
        argv += ["--paths", str(p)]
    argv += ["--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


class TestSharedMode:

    def test_ok_when_complete(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "x.flac").touch()
        (b / "x.opus").touch()
        result = run(CHECK_SCRIPT, {"mode": "shared", "extensions": ["flac", "opus"]}, a, b)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_violation_when_incomplete(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "x.flac").touch()
        (a / "y.flac").touch()
        (b / "x.opus").touch()
        result = run(CHECK_SCRIPT, {"mode": "shared", "extensions": ["flac", "opus"]}, a, b)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "y" in payload["message"]


class TestExclusiveMode:

    def test_ok_when_disjoint(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "raw1.cr2").touch()
        (b / "done1.jpg").touch()
        result = run(CHECK_SCRIPT, {"mode": "exclusive"}, a, b)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_violation_when_overlapping(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "dup.cr2").touch()
        (b / "dup.jpg").touch()
        result = run(CHECK_SCRIPT, {"mode": "exclusive"}, a, b)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "dup" in payload["message"]


class TestRecursiveMatching:

    def test_folder_structure_aware_same_name_different_folder_no_match(self, tmp_path):
        """Same filename in a DIFFERENT subfolder must not satisfy the match."""
        a, b = tmp_path / "a", tmp_path / "b"
        (a / "artist" / "album").mkdir(parents=True)
        (b / "artist" / "other-album").mkdir(parents=True)
        (a / "artist" / "album" / "track.flac").touch()
        (b / "artist" / "other-album" / "track.opus").touch()
        result = run(CHECK_SCRIPT, {"mode": "shared", "extensions": ["flac", "opus"], "recursive": True}, a, b)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_non_recursive_ignores_subfolders_entirely(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        (a / "sub").mkdir(parents=True)
        (b / "sub").mkdir(parents=True)
        (a / "sub" / "x.flac").touch()
        result = run(CHECK_SCRIPT, {"mode": "shared", "recursive": False}, a, b)
        assert json.loads(result.stdout)["status"] == "ok"


class TestFilters:

    def test_exclude_filters_out_matches(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "cover.jpg").touch()
        (b / "folder.jpg").touch()
        result = run(CHECK_SCRIPT, {"mode": "shared", "exclude": ["*.jpg"]}, a, b)
        assert json.loads(result.stdout)["status"] == "ok"


class TestValidation:

    def test_mode_has_no_default_and_is_required(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        result = run(CHECK_SCRIPT, {}, a, b)
        assert result.returncode != 0
        assert "mode" in result.stderr

    def test_requires_at_least_two_paths(self, tmp_path):
        a = tmp_path / "a"
        a.mkdir()
        result = run(CHECK_SCRIPT, {"mode": "shared"}, a)
        assert result.returncode != 0


class TestFixer:

    def _make_fake_script(self, tmp_path: Path, fail_on: str = "__never__") -> Path:
        script = tmp_path / "fake_fixer.py"
        script.write_text(f'''#!/usr/bin/env python3
import argparse, sys
p = argparse.ArgumentParser()
p.add_argument("--mode", required=True)
p.add_argument("--stem", required=True)
p.add_argument("--present", required=True)
p.add_argument("--missing", required=True)
args = p.parse_args()
sys.exit(1 if "{fail_on}" in args.stem else 0)
''')
        script.chmod(0o755)
        return script

    def test_no_violations_is_ok(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        fixer = self._make_fake_script(tmp_path)
        result = run(FIX_SCRIPT, {"mode": "shared", "fixer_script": str(fixer)}, a, b, fix=True)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_unconfigured_fixer_script_is_unfixable(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "x.flac").touch()
        result = run(FIX_SCRIPT, {"mode": "shared"}, a, b, fix=True)
        assert json.loads(result.stdout)["status"] == "unfixable"

    def test_all_resolved_is_fixed(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "x.flac").touch()
        (a / "y.flac").touch()
        fixer = self._make_fake_script(tmp_path)
        result = run(FIX_SCRIPT, {"mode": "shared", "fixer_script": str(fixer)}, a, b, fix=True)
        assert json.loads(result.stdout)["status"] == "fixed"

    def test_partial_failure_is_violation(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "good.flac").touch()
        (a / "bad.flac").touch()
        fixer = self._make_fake_script(tmp_path, fail_on="bad")
        result = run(FIX_SCRIPT, {"mode": "shared", "fixer_script": str(fixer)}, a, b, fix=True)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "bad" in payload["message"]

    def test_fixer_receives_present_and_missing_payload(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir(); b.mkdir()
        (a / "x.flac").touch()

        capture_script = tmp_path / "capture.py"
        capture_file = tmp_path / "captured.json"
        capture_script.write_text(f'''#!/usr/bin/env python3
import argparse, json, sys
p = argparse.ArgumentParser()
p.add_argument("--mode", required=True)
p.add_argument("--stem", required=True)
p.add_argument("--present", required=True)
p.add_argument("--missing", required=True)
args = p.parse_args()
with open("{capture_file}", "w") as f:
    json.dump({{"mode": args.mode, "stem": args.stem, "present": json.loads(args.present), "missing": json.loads(args.missing)}}, f)
sys.exit(0)
''')
        capture_script.chmod(0o755)

        run(FIX_SCRIPT, {"mode": "shared", "fixer_script": str(capture_script)}, a, b, fix=True)

        captured = json.loads(capture_file.read_text())
        assert captured["mode"] == "shared"
        assert captured["stem"] == "x"
        assert str(a) in captured["present"]
        assert captured["present"][str(a)] == ["flac"]
        assert str(b) in captured["missing"]


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
