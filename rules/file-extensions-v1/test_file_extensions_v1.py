"""
test_file_extensions_v1.py - tests for the file-extensions-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_file_extensions_v1.py -v
Or, from the project root, both bundled rules' tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "file-extensions-v1-check.py"


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


class TestAllowedList:

    def test_clean_dir_is_ok(self, tmp_path):
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.png").touch()
        result = run_check({"allowed": ["jpg", "png"]}, tmp_path)
        assert result.returncode == 0
        assert json.loads(result.stdout)["status"] == "ok"

    def test_disallowed_extension_is_violation(self, tmp_path):
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.pdf").touch()
        result = run_check({"allowed": ["jpg"]}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "b.pdf" in payload["message"]

    def test_case_insensitive_and_dot_agnostic(self, tmp_path):
        (tmp_path / "a.JPG").touch()
        result = run_check({"allowed": [".jpg"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestDisallowedList:

    def test_disallowed_extension_is_violation(self, tmp_path):
        (tmp_path / "a.exe").touch()
        result = run_check({"disallowed": ["exe"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_other_extensions_pass(self, tmp_path):
        (tmp_path / "a.jpg").touch()
        result = run_check({"disallowed": ["exe"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestRecursive:

    def test_recursive_true_finds_nested_violation(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "bad.pdf").touch()
        result = run_check({"allowed": ["jpg"], "recursive": True}, tmp_path)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_recursive_false_ignores_nested_files(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "bad.pdf").touch()
        result = run_check({"allowed": ["jpg"], "recursive": False}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestExclude:

    def test_excluded_file_is_ignored(self, tmp_path):
        (tmp_path / "a.jpg").touch()
        (tmp_path / "b.pdf").touch()
        result = run_check({"allowed": ["jpg"], "exclude": ["b.pdf"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_excluded_glob_matches_nested_path(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "bad.pdf").touch()
        result = run_check({"allowed": ["jpg"], "exclude": ["sub/*.pdf"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestEdgeCases:

    def test_no_extension_treated_as_none(self, tmp_path):
        (tmp_path / "README").touch()
        result = run_check({"allowed": ["none"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        result = run_check({"allowed": ["jpg"]}, tmp_path, fix=True)
        assert result.returncode != 0

    def test_both_lists_empty_is_broken(self, tmp_path):
        """Exactly one of allowed/disallowed must be non-empty - this is a
        runtime constraint the manifest can't express, so the script
        itself refuses to run rather than silently doing nothing."""
        result = run_check({}, tmp_path)
        assert result.returncode != 0

    def test_both_lists_set_is_broken(self, tmp_path):
        result = run_check({"allowed": ["jpg"], "disallowed": ["exe"]}, tmp_path)
        assert result.returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        result = run_check({"allowed": ["jpg"]}, tmp_path / "does-not-exist")
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
