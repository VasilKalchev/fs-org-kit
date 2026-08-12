"""
test_uncataloged_reserved_v1.py - tests for the uncataloged-reserved-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_uncataloged_reserved_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "uncataloged-reserved-v1-check.py"


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


class TestCatalogMatching:

    def test_every_reserved_folder_cataloged_is_ok(self, tmp_path):
        (tmp_path / "_archive").mkdir()
        (tmp_path / "_temp").mkdir()
        assert status(run_check({"cataloged": ["_archive", "_temp"]}, tmp_path)) == "ok"

    def test_uncataloged_reserved_folder_is_violation(self, tmp_path):
        (tmp_path / "_archive").mkdir()
        (tmp_path / "_scratch").mkdir()
        payload = json.loads(run_check({"cataloged": ["_archive"]}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "_scratch" in payload["message"]
        assert payload["message"].startswith("1 folder(s)")

    def test_folder_without_the_prefix_is_never_checked(self, tmp_path):
        (tmp_path / "documents").mkdir()
        (tmp_path / "media").mkdir()
        assert status(run_check({"cataloged": []}, tmp_path)) == "ok"

    def test_empty_catalog_flags_every_reserved_looking_folder(self, tmp_path):
        (tmp_path / "_a").mkdir()
        (tmp_path / "_b").mkdir()
        payload = json.loads(run_check({"cataloged": []}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert payload["message"].startswith("2 folder(s)")

    def test_missing_cataloged_param_behaves_as_an_empty_catalog(self, tmp_path):
        """`cataloged` has no manifest default on purpose - the script
        treats an absent one as "nothing is cataloged" rather than
        refusing, so a bare attachment still reports something."""
        (tmp_path / "_stray").mkdir()
        assert status(run_check({}, tmp_path)) == "violation"

    def test_cataloged_entry_with_no_folder_on_disk_is_not_a_violation(self, tmp_path):
        """This rule only looks at what exists - a catalog entry with no
        folder is required-content-v1's question, not this one."""
        assert status(run_check({"cataloged": ["_archive", "_temp"]}, tmp_path)) == "ok"

    def test_files_are_never_checked(self, tmp_path):
        (tmp_path / "_notes.md").touch()
        assert status(run_check({"cataloged": []}, tmp_path)) == "ok"

    def test_matching_is_case_sensitive(self, tmp_path):
        (tmp_path / "_Archive").mkdir()
        assert status(run_check({"cataloged": ["_archive"]}, tmp_path)) == "violation"


class TestCatalogAsATable:
    """`cataloged` is normally a `{ref = "folders.reserved"}`, which
    substitutes that whole table verbatim - entries and the schema-level
    keys sitting beside them. Taking the names out of it is this
    script's job, not the runner's."""

    RESERVED = {
        "prefix": "_",
        "_archive": {"purpose": "p", "group": {"lifecycle": "archival"}},
        "_inbox": {"purpose": "p"},
    }

    def test_a_table_is_accepted_and_its_entry_names_used(self, tmp_path):
        (tmp_path / "_archive").mkdir()
        (tmp_path / "_inbox").mkdir()
        assert status(run_check({"cataloged": self.RESERVED}, tmp_path)) == "ok"

    def test_a_folder_missing_from_the_table_is_still_a_violation(self, tmp_path):
        (tmp_path / "_scratch").mkdir()
        assert status(run_check({"cataloged": self.RESERVED}, tmp_path)) == "violation"

    def test_a_meta_key_beside_the_entries_is_not_a_cataloged_name(self, tmp_path):
        """A folder literally named `prefix` must not be excused by
        [folders.reserved]'s `prefix` key - an entry is a sub-table, that
        isn't."""
        (tmp_path / "_prefix").mkdir()
        assert status(run_check({"cataloged": {"prefix": "_"}}, tmp_path)) == "violation"

    def test_an_empty_table_catalogs_nothing(self, tmp_path):
        (tmp_path / "_stray").mkdir()
        assert status(run_check({"cataloged": {}}, tmp_path)) == "violation"


class TestPrefix:

    def test_default_prefix_is_underscore(self, tmp_path):
        (tmp_path / "_stray").mkdir()
        (tmp_path / ".hidden").mkdir()
        payload = json.loads(run_check({"cataloged": []}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert payload["message"].startswith("1 folder(s)")
        assert "_stray" in payload["message"]

    def test_custom_prefix(self, tmp_path):
        (tmp_path / "@inbox").mkdir()
        (tmp_path / "_underscore").mkdir()
        payload = json.loads(run_check({"prefix": "@", "cataloged": []}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "@inbox" in payload["message"]
        assert "_underscore" not in payload["message"]

    def test_multi_character_prefix(self, tmp_path):
        (tmp_path / "sys-cache").mkdir()
        (tmp_path / "documents").mkdir()
        payload = json.loads(run_check({"prefix": "sys-", "cataloged": []}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "sys-cache" in payload["message"]

    def test_prefix_names_itself_in_the_message(self, tmp_path):
        (tmp_path / "@inbox").mkdir()
        payload = json.loads(run_check({"prefix": "@", "cataloged": []}, tmp_path).stdout)
        assert "start with '@'" in payload["message"]

    def test_empty_prefix_is_broken(self, tmp_path):
        """An empty prefix matches every folder name - that isn't a
        reserved-name check any more."""
        assert run_check({"prefix": "", "cataloged": []}, tmp_path).returncode != 0

    def test_non_string_prefix_is_broken(self, tmp_path):
        assert run_check({"prefix": 5, "cataloged": []}, tmp_path).returncode != 0


class TestTraversal:

    def test_recursive_by_default(self, tmp_path):
        nested = tmp_path / "projects"
        nested.mkdir()
        (nested / "_stray").mkdir()
        assert status(run_check({"cataloged": []}, tmp_path)) == "violation"

    def test_recursive_false_stays_at_the_top(self, tmp_path):
        nested = tmp_path / "projects"
        nested.mkdir()
        (nested / "_stray").mkdir()
        assert status(run_check({"cataloged": [], "recursive": False}, tmp_path)) == "ok"

    def test_nested_folder_is_reported_by_its_relative_path(self, tmp_path):
        nested = tmp_path / "projects"
        nested.mkdir()
        (nested / "_stray").mkdir()
        payload = json.loads(run_check({"cataloged": []}, tmp_path).stdout)
        assert "projects/_stray" in payload["message"]

    def test_catalog_matches_the_basename_at_any_depth(self, tmp_path):
        """The catalog is a list of names, not of paths - a cataloged
        reserved folder is cataloged wherever it turns up."""
        nested = tmp_path / "projects"
        nested.mkdir()
        (nested / "_archive").mkdir()
        assert status(run_check({"cataloged": ["_archive"]}, tmp_path)) == "ok"

    def test_reserved_folder_inside_a_reserved_folder_is_still_checked(self, tmp_path):
        outer = tmp_path / "_archive"
        outer.mkdir()
        (outer / "_stray").mkdir()
        payload = json.loads(run_check({"cataloged": ["_archive"]}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "_archive/_stray" in payload["message"]

    def test_exclude_by_bare_name(self, tmp_path):
        (tmp_path / "_stray").mkdir()
        assert status(run_check({"cataloged": [], "exclude": ["_stray"]}, tmp_path)) == "ok"

    def test_exclude_glob_matches_a_nested_path(self, tmp_path):
        nested = tmp_path / "vendor"
        nested.mkdir()
        (nested / "_build").mkdir()
        assert status(run_check({"cataloged": [], "exclude": ["vendor/*"]}, tmp_path)) == "ok"

    def test_excluding_a_folder_does_not_prune_its_subtree(self, tmp_path):
        """`exclude` filters what gets reported, it doesn't stop the walk."""
        outer = tmp_path / "_vendor"
        outer.mkdir()
        (outer / "_build").mkdir()
        payload = json.loads(run_check({"cataloged": [], "exclude": ["_vendor"]}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "_vendor/_build" in payload["message"]


class TestMessage:

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(12):
            (tmp_path / f"_stray{i:02d}").mkdir()
        payload = json.loads(run_check({"cataloged": []}, tmp_path).stdout)
        assert payload["message"].startswith("12 folder(s)")
        assert "and 2 more" in payload["message"]

    def test_results_are_sorted(self, tmp_path):
        for name in ("_c", "_a", "_b"):
            (tmp_path / name).mkdir()
        message = json.loads(run_check({"cataloged": []}, tmp_path).stdout)["message"]
        assert message.index("_a") < message.index("_b") < message.index("_c")


class TestArguments:

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        assert run_check({"cataloged": []}, tmp_path, fix=True).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        assert run_check({"cataloged": [], "exclude": "_stray"}, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"cataloged": []}, tmp_path / "nope").returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
