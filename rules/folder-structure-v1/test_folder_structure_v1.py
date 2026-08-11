"""
test_folder_structure_v1.py - tests for the folder-structure-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_folder_structure_v1.py -v
Or, from the project root, all bundled rules' tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "folder-structure-v1-check.py"


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


class TestDirectCounts:

    def test_within_limits_is_ok(self, tmp_path):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        result = run_check({"max_folders": 5}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_exceeding_max_is_violation(self, tmp_path):
        for i in range(6):
            (tmp_path / f"f{i}").mkdir()
        result = run_check({"max_folders": 5}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "folder count" in payload["message"]


class TestRecursive:

    def test_non_recursive_ignores_grandchildren(self, tmp_path):
        """max_folders=5 with one direct subfolder containing 1000
        sub-subfolders is fine - only direct children of --path count."""
        sub = tmp_path / "sub"
        sub.mkdir()
        for i in range(1000):
            (sub / f"g{i}").mkdir()
        result = run_check({"max_folders": 5}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_recursive_checks_every_folder_independently(self, tmp_path):
        """The same tree fails under recursive=True because `sub` itself
        is checked against max_folders using its own direct children."""
        sub = tmp_path / "sub"
        sub.mkdir()
        for i in range(1000):
            (sub / f"g{i}").mkdir()
        result = run_check({"max_folders": 5, "recursive": True}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "sub" in payload["message"]

    def test_recursive_root_violation_has_no_under_suffix(self, tmp_path):
        for i in range(6):
            (tmp_path / f"f{i}").mkdir()
        result = run_check({"max_folders": 5, "recursive": True}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "under" not in payload["message"]


class TestExclude:

    def test_excluded_folder_not_counted(self, tmp_path):
        for i in range(6):
            (tmp_path / f"f{i}").mkdir()
        result = run_check({"max_folders": 5, "exclude": ["f5"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_excluded_folder_subtree_pruned_from_recursion(self, tmp_path):
        excluded = tmp_path / "excluded"
        excluded.mkdir()
        for i in range(1000):
            (excluded / f"g{i}").mkdir()
        result = run_check({"max_folders": 5, "recursive": True, "exclude": ["excluded"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_excluded_file_not_counted_in_size(self, tmp_path):
        big = tmp_path / "big.bin"
        big.write_bytes(b"0" * 2048)
        result = run_check({"max_size": "1KiB", "exclude": ["big.bin"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestDepthAndSize:

    def test_max_depth_violation(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        nested.mkdir(parents=True)
        result = run_check({"max_depth": 1}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "depth" in payload["message"]

    def test_max_size_violation(self, tmp_path):
        (tmp_path / "big.bin").write_bytes(b"0" * (2 * 1024 * 1024))
        result = run_check({"max_size": "1MiB"}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "size" in payload["message"]


class TestEdgeCases:

    def test_rejects_fix_flag(self, tmp_path):
        result = run_check({"max_folders": 5}, tmp_path, fix=True)
        assert result.returncode != 0

    def test_no_thresholds_set_is_ok(self, tmp_path):
        (tmp_path / "a").mkdir()
        result = run_check({}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_nonexistent_path_is_broken(self, tmp_path):
        result = run_check({"max_folders": 5}, tmp_path / "does-not-exist")
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
