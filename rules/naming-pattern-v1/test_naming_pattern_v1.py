"""
test_naming_pattern_v1.py - tests for the naming-pattern-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_naming_pattern_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "naming-pattern-v1-check.py"

# The two reference patterns the manifest documents, tested as written.
PORTABLE_CHARSET = r'[<>:"|?*\\]'
DEFAULT_NAMES = r'^[Nn]ew [Ff]older(\s*\(\d+\))?$|^Untitled(\s+\d+)?(\.[A-Za-z0-9]+)?$|^[Cc]opy [Oo]f .+$'


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


class TestAllowMode:
    """Every checked name must match - a name that doesn't is the violation."""

    def test_all_matching_is_ok(self, tmp_path):
        (tmp_path / "kebab-case-name.txt").touch()
        (tmp_path / "another-one.txt").touch()
        params = {"pattern": r"^[a-z0-9.-]+$", "mode": "allow"}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_non_matching_name_is_violation(self, tmp_path):
        (tmp_path / "fine.txt").touch()
        (tmp_path / "Has Spaces.txt").touch()
        params = {"pattern": r"^[a-z0-9.-]+$", "mode": "allow"}
        payload = json.loads(run_check(params, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "Has Spaces.txt" in payload["message"]
        assert "doesn't match" in payload["message"]

    def test_empty_directory_is_ok(self, tmp_path):
        params = {"pattern": r"^[a-z]+$", "mode": "allow"}
        assert status(run_check(params, tmp_path)) == "ok"


class TestDisallowMode:
    """No checked name may match - a name that does is the violation."""

    def test_no_match_is_ok(self, tmp_path):
        (tmp_path / "report.txt").touch()
        assert status(run_check({"pattern": PORTABLE_CHARSET, "mode": "disallow"}, tmp_path)) == "ok"

    def test_match_is_violation(self, tmp_path):
        (tmp_path / "what?.txt").touch()
        payload = json.loads(run_check({"pattern": PORTABLE_CHARSET, "mode": "disallow"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "what?.txt" in payload["message"]
        assert "matches the disallowed pattern" in payload["message"]

    def test_reference_pattern_catches_os_default_names(self, tmp_path):
        (tmp_path / "New folder").mkdir()
        (tmp_path / "Untitled.txt").touch()
        (tmp_path / "Copy of report.pdf").touch()
        (tmp_path / "deliberate-name.md").touch()
        payload = json.loads(run_check({"pattern": DEFAULT_NAMES, "mode": "disallow"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert payload["message"].startswith("3 item(s)")
        assert "deliberate-name.md" not in payload["message"]


class TestMatchingSemantics:

    def test_pattern_is_unanchored_and_matches_anywhere(self, tmp_path):
        """Documented behavior: search, not fullmatch - write ^...$ yourself."""
        (tmp_path / "prefix-draft-suffix.txt").touch()
        assert status(run_check({"pattern": "draft", "mode": "disallow"}, tmp_path)) == "violation"

    def test_anchoring_it_yourself_narrows_the_match(self, tmp_path):
        (tmp_path / "prefix-draft-suffix.txt").touch()
        assert status(run_check({"pattern": "^draft$", "mode": "disallow"}, tmp_path)) == "ok"

    def test_files_are_matched_on_the_full_name_including_extension(self, tmp_path):
        """The extension is part of what the pattern sees, unlike the
        stem-only treatment in spelling-abbreviations-v1."""
        (tmp_path / "report.TXT").touch()
        assert status(run_check({"pattern": r"\.TXT$", "mode": "disallow"}, tmp_path)) == "violation"

    def test_only_the_items_own_name_is_matched_not_its_path(self, tmp_path):
        """A parent folder matching the pattern must not implicate its children."""
        bad = tmp_path / "BAD"
        bad.mkdir()
        (bad / "fine.txt").touch()
        payload = json.loads(run_check({"pattern": "^BAD$", "mode": "disallow"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert payload["message"].startswith("1 item(s)")


class TestTarget:

    def test_target_files_ignores_folder_names(self, tmp_path):
        (tmp_path / "Bad Folder").mkdir()
        (tmp_path / "good.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "target": "files"}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_target_folders_ignores_file_names(self, tmp_path):
        (tmp_path / "goodfolder").mkdir()
        (tmp_path / "Bad File.txt").touch()
        params = {"pattern": r"^[a-z0-9]+$", "mode": "allow", "target": "folders"}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_target_both_checks_everything(self, tmp_path):
        (tmp_path / "Bad Folder").mkdir()
        (tmp_path / "Bad File.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "target": "both"}
        payload = json.loads(run_check(params, tmp_path).stdout)
        assert payload["message"].startswith("2 item(s)")


class TestTraversal:

    def test_recursive_by_default(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "Bad Name.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow"}
        assert status(run_check(params, tmp_path)) == "violation"

    def test_recursive_false_stays_at_the_top(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "Bad Name.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "recursive": False}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_violation_names_the_path_relative_to_the_scanned_root(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "Bad Name.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "target": "files"}
        payload = json.loads(run_check(params, tmp_path).stdout)
        assert "sub/Bad Name.txt" in payload["message"]

    def test_exclude_by_bare_name(self, tmp_path):
        (tmp_path / "Grandfathered.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "exclude": ["Grandfathered.txt"]}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_exclude_glob_matches_a_nested_path(self, tmp_path):
        nested = tmp_path / "vendor"
        nested.mkdir()
        (nested / "Bad Name.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "exclude": ["vendor", "vendor/*"]}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_excluding_a_folder_does_not_prune_its_contents(self, tmp_path):
        """`exclude` filters items, it doesn't stop the walk - the glob has
        to cover what's inside too (which is why the test above lists both)."""
        nested = tmp_path / "vendor"
        nested.mkdir()
        (nested / "Bad Name.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow", "exclude": ["vendor"]}
        assert status(run_check(params, tmp_path)) == "violation"


class TestMessage:

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(13):
            (tmp_path / f"BAD{i:02d}.txt").touch()
        params = {"pattern": r"^[a-z0-9.]+$", "mode": "allow"}
        payload = json.loads(run_check(params, tmp_path).stdout)
        assert payload["message"].startswith("13 item(s)")
        assert "and 3 more" in payload["message"]


class TestArguments:

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        result = run_check({"pattern": "x", "mode": "allow"}, tmp_path, fix=True)
        assert result.returncode != 0

    def test_pattern_is_required(self, tmp_path):
        result = run_check({"mode": "allow"}, tmp_path)
        assert result.returncode != 0
        assert "pattern" in result.stderr

    def test_empty_pattern_is_broken(self, tmp_path):
        """An empty pattern matches everything - a rule that can only ever
        say "all fine" or "all wrong" isn't configured, it's broken."""
        assert run_check({"pattern": "", "mode": "allow"}, tmp_path).returncode != 0

    def test_invalid_regex_is_broken(self, tmp_path):
        result = run_check({"pattern": "[unclosed", "mode": "allow"}, tmp_path)
        assert result.returncode != 0
        assert "regular expression" in result.stderr

    def test_mode_is_required(self, tmp_path):
        result = run_check({"pattern": "x"}, tmp_path)
        assert result.returncode != 0
        assert "mode" in result.stderr

    def test_unknown_mode_is_broken(self, tmp_path):
        assert run_check({"pattern": "x", "mode": "forbid"}, tmp_path).returncode != 0

    def test_unknown_target_is_broken(self, tmp_path):
        assert run_check({"pattern": "x", "mode": "allow", "target": "links"}, tmp_path).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        assert run_check({"pattern": "x", "mode": "allow", "exclude": "a.txt"}, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"pattern": "x", "mode": "allow"}, tmp_path / "nope").returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
