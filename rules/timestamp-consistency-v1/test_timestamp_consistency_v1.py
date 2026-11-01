"""
test_timestamp_consistency_v1.py - tests for the timestamp-consistency-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_timestamp_consistency_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "timestamp-consistency-v1-check.py"


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


def message(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["message"]


def tree(root: Path, *relative_paths: str) -> None:
    """Creates each path; a trailing slash means "directory"."""
    for spec in relative_paths:
        target = root / spec.rstrip("/")
        if spec.endswith("/"):
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.touch()


class TestConsistentTrees:

    def test_year_month_day_chain_is_ok(self, tmp_path):
        tree(tmp_path, "2026/2026-03/2026-03-05/20260305_143000_notes.txt")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_separatorless_forms_are_equivalent(self, tmp_path):
        tree(tmp_path, "2026/202603/20260305/")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_undated_folder_does_not_break_the_chain(self, tmp_path):
        """A component matching nothing is skipped, not treated as a reset."""
        tree(tmp_path, "2026/Photos/2026-03-05/")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_undated_leaf_files_are_fine(self, tmp_path):
        tree(tmp_path, "2026-03-05/notes.txt", "2026-03-05/receipt.pdf")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_empty_directory_is_ok(self, tmp_path):
        assert status(run_check({}, tmp_path)) == "ok"

    def test_siblings_are_independent(self, tmp_path):
        """Two dated sibling folders don't constrain each other - only
        ancestors constrain descendants."""
        tree(tmp_path, "2025-01-01/", "2026-12-31/")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_the_scanned_root_itself_is_never_parsed(self, tmp_path):
        """The walk starts with nothing established - --path's own name
        isn't part of the chain, since the rule can't know whether it's a
        catalog key or an accident of where the tree happens to live."""
        root = tmp_path / "2025"
        root.mkdir()
        tree(root, "2026-03-05/")
        assert status(run_check({}, root)) == "ok"


class TestConflicts:

    def test_year_contradicting_its_parent_year(self, tmp_path):
        tree(tmp_path, "2025/2026-03-05/")
        payload = json.loads(run_check({}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "2025/2026-03-05" in payload["message"]
        assert "year 2026 contradicts already-established year 2025" in payload["message"]

    def test_month_contradicting_its_parent_month(self, tmp_path):
        tree(tmp_path, "2026-03/2026-04-05/")
        assert "month 4 contradicts already-established month 3" in message(run_check({}, tmp_path))

    def test_file_datetime_contradicting_its_folder_date(self, tmp_path):
        tree(tmp_path, "2026-03-05/20260306_101500_note.txt")
        payload = json.loads(run_check({}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "day 6 contradicts already-established day 5" in payload["message"]

    def test_file_datetime_agreeing_with_its_folder_date(self, tmp_path):
        tree(tmp_path, "2026-03-05/20260305_101500_note.txt")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_several_fields_conflicting_are_reported_together(self, tmp_path):
        tree(tmp_path, "2026-03-05/20250406_101500_note.txt")
        text = message(run_check({}, tmp_path))
        assert "year 2025 contradicts" in text
        assert "month 4 contradicts" in text
        assert "day 6 contradicts" in text
        assert ";" in text

    def test_an_intermediate_folder_is_checked_on_its_own(self, tmp_path):
        """Not just leaf files - a wrongly-dated folder is a violation
        regardless of whether anything is inside it."""
        tree(tmp_path, "2025/2026-03/")
        assert status(run_check({}, tmp_path)) == "violation"

    def test_a_conflict_is_not_re_reported_for_everything_beneath_it(self, tmp_path):
        """Descent continues with the pre-conflict state, so one bad
        folder is one violation, not one per file under it."""
        tree(tmp_path,
             "2025/2026-03/a.txt", "2025/2026-03/b.txt",
             "2025/2026-03/deeper/c.txt")
        payload = json.loads(run_check({}, tmp_path).stdout)
        assert payload["message"].startswith("1 item(s)")

    def test_a_later_conflict_under_the_same_parent_is_still_found(self, tmp_path):
        tree(tmp_path, "2025/2026-03/", "2025/2027-04/")
        payload = json.loads(run_check({}, tmp_path).stdout)
        assert payload["message"].startswith("2 item(s)")


class TestRecognizedForms:

    @pytest.mark.parametrize("name", ["2026", "2026-03", "202603", "2026-03-05", "20260305"])
    def test_folder_forms_establish_a_constraint(self, tmp_path, name):
        tree(tmp_path, f"{name}/2027-01-01/")
        assert status(run_check({}, tmp_path)) == "violation"

    def test_datetime_form_is_recognized_in_a_filename(self, tmp_path):
        tree(tmp_path, "2026/20250101_120000_report.txt")
        assert status(run_check({}, tmp_path)) == "violation"

    def test_a_dated_filename_with_an_extension_is_not_recognized(self, tmp_path):
        """The date-only patterns are fully anchored, so "2025-01-01.md"
        parses as nothing - only the YYYYMMDD_HHMMSS prefix form carries
        a timestamp into a filename."""
        tree(tmp_path, "2026/2025-01-01.md")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_a_bare_dated_filename_is_recognized(self, tmp_path):
        tree(tmp_path, "2026/2025-01-01")
        assert status(run_check({}, tmp_path)) == "violation"

    def test_a_dated_prefix_on_a_named_folder_is_not_recognized(self, tmp_path):
        """"2026-03-05-holiday" is not one of the accepted date shapes -
        timestamp-format-v1 is the rule about how names are shaped."""
        tree(tmp_path, "2025/2026-03-05-holiday/")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_a_digit_run_of_the_wrong_length_is_not_a_date(self, tmp_path):
        tree(tmp_path, "2026/12345/")
        assert status(run_check({}, tmp_path)) == "ok"


class TestRequireAllComponents:

    def test_off_by_default(self, tmp_path):
        tree(tmp_path, "Photos/")
        assert status(run_check({}, tmp_path)) == "ok"

    def test_on_flags_an_undated_folder(self, tmp_path):
        tree(tmp_path, "Photos/")
        payload = json.loads(run_check({"require_all_components_timestamped": True}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "no recognizable timestamp in name" in payload["message"]

    def test_on_flags_an_undated_file(self, tmp_path):
        tree(tmp_path, "2026-03-05/notes.txt")
        assert status(run_check({"require_all_components_timestamped": True}, tmp_path)) == "violation"

    def test_on_still_passes_a_fully_dated_tree(self, tmp_path):
        tree(tmp_path, "2026/2026-03/20260305_143000_x.txt")
        assert status(run_check({"require_all_components_timestamped": True}, tmp_path)) == "ok"


class TestRecursive:

    def test_recursive_by_default(self, tmp_path):
        tree(tmp_path, "2026/deep/deeper/2025-01-01/")
        assert status(run_check({}, tmp_path)) == "violation"

    def test_recursive_false_checks_only_direct_children(self, tmp_path):
        tree(tmp_path, "2026/2025-01-01/")
        assert status(run_check({"recursive": False}, tmp_path)) == "ok"

    def test_recursive_false_still_checks_the_direct_children_themselves(self, tmp_path):
        tree(tmp_path, "2026-03-05/", "notes.txt")
        result = run_check({"recursive": False, "require_all_components_timestamped": True}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "notes.txt" in payload["message"]


class TestMessage:

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(12):
            tree(tmp_path, f"2025/2026-03-{i + 1:02d}/")
        payload = json.loads(run_check({}, tmp_path).stdout)
        assert payload["message"].startswith("12 item(s)")
        assert "and 2 more" in payload["message"]


class TestArguments:

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        assert run_check({}, tmp_path, fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({}, tmp_path / "nope").returncode != 0

    def test_a_file_as_path_is_broken(self, tmp_path):
        target = tmp_path / "a.txt"
        target.touch()
        assert run_check({}, target).returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestRobustness:

    @pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
    def test_a_symlink_back_up_the_tree_is_not_followed(self, tmp_path):
        tree(tmp_path, "2025/2025-03/notes.txt")
        (tmp_path / "2025" / "loop").symlink_to(tmp_path)
        result = run_check({}, tmp_path)
        assert result.returncode == 0, result.stderr
        assert status(result) == "ok"

    def test_digits_naming_no_real_date_are_not_a_timestamp(self, tmp_path):
        """"2025-13" has a timestamp's shape but there's no month 13 - it's
        an ordinary name, so it can't contradict the 2026 above it."""
        tree(tmp_path, "2026/2025-13/notes.txt")
        assert status(run_check({}, tmp_path)) == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
