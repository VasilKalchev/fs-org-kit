"""
test_staleness_v1.py - tests for the staleness-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Note that the scripts are invoked here exactly as the runner invokes
them, but *without* the runner's sandbox - a fixer that writes outside
what it's allowed to touch passes these tests and still fails under
`fs-org-run --fix`. See doc/RULES.md.

Run from anywhere with: pytest test_staleness_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest

RULE_DIR = Path(__file__).resolve().parent
CHECK_SCRIPT = RULE_DIR / "staleness-v1-check.py"
FIX_SCRIPT = RULE_DIR / "staleness-v1-fix.py"

DAY = 86400


def run(script: Path, params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(script), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


def message(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["message"]


def aged(path: Path, days: float) -> Path:
    """Backdates both atime and mtime by `days`."""
    when = time.time() - days * DAY
    os.utime(path, (when, when))
    return path


def old_file(parent: Path, name: str, days: float) -> Path:
    target = parent / name
    target.write_text("x")
    return aged(target, days)


class TestStaleMode:
    """Flags a direct child that hasn't been touched recently enough."""

    def test_recent_children_are_ok(self, tmp_path):
        old_file(tmp_path, "yesterday.txt", 1)
        old_file(tmp_path, "last-week.txt", 7)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "ok"

    def test_old_child_is_violation(self, tmp_path):
        old_file(tmp_path, "fresh.txt", 1)
        old_file(tmp_path, "forgotten.txt", 200)
        payload = json.loads(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "forgotten.txt" in payload["message"]
        assert "fresh.txt" not in payload["message"]
        assert "hasn't been touched in" in payload["message"]

    def test_exactly_at_the_threshold_is_not_stale(self, tmp_path):
        """`stale` is strictly older than the threshold."""
        old_file(tmp_path, "borderline.txt", 89.99)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "ok"

    def test_empty_directory_is_ok(self, tmp_path):
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "ok"


class TestActiveMode:
    """Flags a direct child that has been touched more recently than expected."""

    def test_old_children_are_ok(self, tmp_path):
        old_file(tmp_path, "settled.txt", 400)
        assert status(run(CHECK_SCRIPT, {"mode": "active", "threshold": "180d"}, tmp_path)) == "ok"

    def test_recent_child_is_violation(self, tmp_path):
        old_file(tmp_path, "settled.txt", 400)
        old_file(tmp_path, "meddled-with.txt", 2)
        payload = json.loads(run(CHECK_SCRIPT, {"mode": "active", "threshold": "180d"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "meddled-with.txt" in payload["message"]
        assert "was touched only" in payload["message"]

    def test_the_two_modes_are_opposites_on_the_same_tree(self, tmp_path):
        old_file(tmp_path, "recent.txt", 5)
        stale = run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)
        active = run(CHECK_SCRIPT, {"mode": "active", "threshold": "90d"}, tmp_path)
        assert status(stale) == "ok"
        assert status(active) == "violation"


class TestEffectiveTimestamp:

    def test_a_folder_is_judged_by_the_newest_file_inside_it(self, tmp_path):
        """A folder's own mtime only tracks its direct listing changing,
        so a deep edit has to be what counts - otherwise an actively-used
        project reads as abandoned."""
        project = tmp_path / "project"
        project.mkdir()
        old_file(project, "old-notes.txt", 300)
        deep = project / "src"
        deep.mkdir()
        old_file(deep, "main.py", 2)
        aged(deep, 300)
        aged(project, 300)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "ok"

    def test_a_folder_of_only_old_files_is_stale(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        old_file(project, "notes.txt", 300)
        payload = json.loads(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "project" in payload["message"]

    def test_an_empty_folder_falls_back_to_its_own_timestamp(self, tmp_path):
        empty = tmp_path / "empty"
        empty.mkdir()
        aged(empty, 300)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "violation"

    def test_only_direct_children_are_judged(self, tmp_path):
        """A stale file buried inside a fresh folder is not itself
        reported - the folder is the unit."""
        project = tmp_path / "project"
        project.mkdir()
        old_file(project, "ancient.txt", 900)
        old_file(project, "current.txt", 1)
        payload = json.loads(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path).stdout)
        assert payload["status"] == "ok"

    def test_basis_atime_is_read_separately_from_mtime(self, tmp_path):
        target = tmp_path / "read-recently.txt"
        target.write_text("x")
        stale_when = time.time() - 300 * DAY
        os.utime(target, (time.time(), stale_when))
        params = {"mode": "stale", "threshold": "90d"}
        assert status(run(CHECK_SCRIPT, params, tmp_path)) == "violation"
        assert status(run(CHECK_SCRIPT, {**params, "basis": "atime"}, tmp_path)) == "ok"


class TestThreshold:

    @pytest.mark.parametrize("threshold, days_that_violate", [("30d", 40), ("2w", 20), ("3m", 100)])
    def test_duration_units(self, tmp_path, threshold, days_that_violate):
        old_file(tmp_path, "x.txt", days_that_violate)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": threshold}, tmp_path)) == "violation"

    def test_weeks_are_seven_days(self, tmp_path):
        old_file(tmp_path, "x.txt", 10)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "2w"}, tmp_path)) == "ok"

    def test_months_are_thirty_days(self, tmp_path):
        old_file(tmp_path, "x.txt", 89)
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "3m"}, tmp_path)) == "ok"


class TestExclude:

    def test_exclude_matches_a_direct_childs_own_name(self, tmp_path):
        """Unlike the recursive rules, this one only ever sees direct
        children, so the globs are name-based, not relative-path-based."""
        old_file(tmp_path, "keep.log", 300)
        params = {"mode": "stale", "threshold": "90d", "exclude": ["*.log"]}
        assert status(run(CHECK_SCRIPT, params, tmp_path)) == "ok"

    def test_exclude_by_exact_name(self, tmp_path):
        old_file(tmp_path, "README.md", 300)
        old_file(tmp_path, "other.txt", 300)
        params = {"mode": "stale", "threshold": "90d", "exclude": ["README.md"]}
        payload = json.loads(run(CHECK_SCRIPT, params, tmp_path).stdout)
        assert payload["message"].startswith("1 item(s)")
        assert "README.md" not in payload["message"]


class TestMessage:

    def test_names_the_mode_and_threshold(self, tmp_path):
        old_file(tmp_path, "x.txt", 300)
        assert "'stale' threshold of 90d" in message(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path))

    def test_age_is_reported_in_days(self, tmp_path):
        old_file(tmp_path, "x.txt", 200)
        assert "200d" in message(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path))

    def test_a_sub_day_age_is_reported_in_hours(self, tmp_path):
        old_file(tmp_path, "x.txt", 0.25)
        text = message(run(CHECK_SCRIPT, {"mode": "active", "threshold": "30d"}, tmp_path))
        assert "6.0h" in text

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(13):
            old_file(tmp_path, f"f{i:02d}.txt", 300)
        text = message(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path))
        assert text.startswith("13 item(s)")
        assert "and 3 more" in text


class TestFixer:

    def _setup(self, tmp_path: Path) -> tuple[Path, Path]:
        active = tmp_path / "active"
        archive = tmp_path / "_arch"
        active.mkdir()
        archive.mkdir()
        return active, archive

    def test_nothing_to_do_is_ok(self, tmp_path):
        active, _ = self._setup(tmp_path)
        old_file(active, "fresh.txt", 1)
        params = {"mode": "stale", "threshold": "90d", "destination": "_arch"}
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "ok"

    def test_violating_items_are_moved(self, tmp_path):
        active, archive = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        old_file(active, "fresh.txt", 1)
        params = {"mode": "stale", "threshold": "90d", "destination": "_arch"}
        result = run(FIX_SCRIPT, params, active, fix=True)
        assert status(result) == "fixed"
        assert (archive / "forgotten.txt").is_file()
        assert not (active / "forgotten.txt").exists()
        assert (active / "fresh.txt").is_file()

    def test_a_relative_destination_resolves_against_the_paths_parent(self, tmp_path):
        """"_arch" means the sibling archive folder, not a subfolder of
        the path being swept."""
        active, archive = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        run(FIX_SCRIPT, {"mode": "stale", "threshold": "90d", "destination": "_arch"}, active, fix=True)
        assert (archive / "forgotten.txt").is_file()
        assert not (active / "_arch").exists()

    def test_an_absolute_destination_is_used_as_is(self, tmp_path):
        active, _ = self._setup(tmp_path)
        elsewhere = tmp_path / "trash"
        elsewhere.mkdir()
        old_file(active, "forgotten.txt", 300)
        params = {"mode": "stale", "threshold": "90d", "destination": str(elsewhere)}
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "fixed"
        assert (elsewhere / "forgotten.txt").is_file()

    def test_a_folder_moves_whole(self, tmp_path):
        active, archive = self._setup(tmp_path)
        project = active / "project"
        project.mkdir()
        old_file(project, "notes.txt", 300)
        aged(project, 300)
        run(FIX_SCRIPT, {"mode": "stale", "threshold": "90d", "destination": "_arch"}, active, fix=True)
        assert (archive / "project" / "notes.txt").is_file()

    def test_active_mode_moves_the_recently_touched_item(self, tmp_path):
        archive = tmp_path / "_arch"
        inbox = tmp_path / "inbox"
        archive.mkdir()
        inbox.mkdir()
        old_file(archive, "settled.txt", 400)
        old_file(archive, "meddled.txt", 2)
        params = {"mode": "active", "threshold": "180d", "destination": "inbox"}
        assert status(run(FIX_SCRIPT, params, archive, fix=True)) == "fixed"
        assert (inbox / "meddled.txt").is_file()
        assert (archive / "settled.txt").is_file()

    def test_a_missing_destination_is_unfixable_and_never_created(self, tmp_path):
        active, _ = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        params = {"mode": "stale", "threshold": "90d", "destination": "nowhere"}
        result = run(FIX_SCRIPT, params, active, fix=True)
        assert status(result) == "unfixable"
        assert not (tmp_path / "nowhere").exists()
        assert (active / "forgotten.txt").is_file()

    def test_create_destination_builds_the_missing_folder(self, tmp_path):
        active, _ = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        params = {
            "mode": "stale", "threshold": "90d",
            "destination": "nowhere/deeper", "create_destination": True,
        }
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "fixed"
        assert (tmp_path / "nowhere" / "deeper" / "forgotten.txt").is_file()

    def test_a_missing_destination_with_nothing_to_move_is_still_ok(self, tmp_path):
        """The destination only has to exist when there's actually
        something to put in it."""
        active, _ = self._setup(tmp_path)
        old_file(active, "fresh.txt", 1)
        params = {"mode": "stale", "threshold": "90d", "destination": "nowhere"}
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "ok"

    def test_a_dated_destination_files_under_the_current_year(self, tmp_path):
        """"_arch/%Y" is what keeps an archive "separated by year" from
        being undermined by its own fixer."""
        active, archive = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        params = {
            "mode": "stale", "threshold": "90d",
            "destination": "_arch/%Y", "create_destination": True,
        }
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "fixed"
        assert (archive / time.strftime("%Y") / "forgotten.txt").is_file()

    def test_a_destination_without_placeholders_is_unchanged(self, tmp_path):
        """Every attachment written before dated destinations existed has
        to keep resolving to exactly the same folder."""
        active, archive = self._setup(tmp_path)
        old_file(active, "forgotten.txt", 300)
        run(FIX_SCRIPT, {"mode": "stale", "threshold": "90d", "destination": "_arch"}, active, fix=True)
        assert (archive / "forgotten.txt").is_file()

    def test_a_dated_destination_that_exists_needs_no_opt_in(self, tmp_path):
        active, archive = self._setup(tmp_path)
        (archive / time.strftime("%Y")).mkdir()
        old_file(active, "forgotten.txt", 300)
        params = {"mode": "stale", "threshold": "90d", "destination": "_arch/%Y"}
        assert status(run(FIX_SCRIPT, params, active, fix=True)) == "fixed"
        assert (archive / time.strftime("%Y") / "forgotten.txt").is_file()

    def test_a_name_collision_is_never_overwritten(self, tmp_path):
        active, archive = self._setup(tmp_path)
        old_file(active, "notes.txt", 300)
        (archive / "notes.txt").write_text("the older copy")
        params = {"mode": "stale", "threshold": "90d", "destination": "_arch"}
        result = run(FIX_SCRIPT, params, active, fix=True)
        assert status(result) == "violation"
        assert "already exists" in result.stdout
        assert (archive / "notes.txt").read_text() == "the older copy"
        assert (active / "notes.txt").is_file()

    def test_a_collision_does_not_stop_the_other_moves(self, tmp_path):
        active, archive = self._setup(tmp_path)
        old_file(active, "notes.txt", 300)
        old_file(active, "other.txt", 300)
        (archive / "notes.txt").write_text("the older copy")
        params = {"mode": "stale", "threshold": "90d", "destination": "_arch"}
        result = run(FIX_SCRIPT, params, active, fix=True)
        assert status(result) == "violation"
        assert "1 of 2 item(s) moved" in message(result)
        assert (archive / "other.txt").is_file()


class TestArguments:

    def test_checker_rejects_fix_and_points_at_the_fixer(self, tmp_path):
        result = run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path, fix=True)
        assert result.returncode != 0
        assert "staleness-v1-fix.py" in result.stderr

    def test_fixer_refuses_to_run_without_fix(self, tmp_path):
        """Otherwise it would move files while looking like a dry run."""
        result = run(FIX_SCRIPT, {"mode": "stale", "threshold": "90d", "destination": "_arch"}, tmp_path)
        assert result.returncode != 0

    @pytest.mark.parametrize("script_name, fix", [("check", False), ("fix", True)])
    def test_both_scripts_require_mode(self, tmp_path, script_name, fix):
        script = CHECK_SCRIPT if script_name == "check" else FIX_SCRIPT
        result = run(script, {"threshold": "90d", "destination": "_arch"}, tmp_path, fix=fix)
        assert result.returncode != 0
        assert "mode" in result.stderr

    @pytest.mark.parametrize("script_name, fix", [("check", False), ("fix", True)])
    def test_both_scripts_require_threshold(self, tmp_path, script_name, fix):
        script = CHECK_SCRIPT if script_name == "check" else FIX_SCRIPT
        result = run(script, {"mode": "stale", "destination": "_arch"}, tmp_path, fix=fix)
        assert result.returncode != 0
        assert "threshold" in result.stderr

    def test_fixer_requires_destination(self, tmp_path):
        result = run(FIX_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path, fix=True)
        assert result.returncode != 0
        assert "destination" in result.stderr

    def test_checker_needs_no_destination(self, tmp_path):
        """`destination` is the fixer's param - a read-only attachment
        shouldn't have to name a place it will never move anything to."""
        assert status(run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path)) == "ok"

    def test_unknown_mode_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {"mode": "ancient", "threshold": "90d"}, tmp_path).returncode != 0

    @pytest.mark.parametrize("threshold", ["90", "90 d", "ninety days", "90y", "-5d"])
    def test_malformed_threshold_is_broken(self, tmp_path, threshold):
        result = run(CHECK_SCRIPT, {"mode": "stale", "threshold": threshold}, tmp_path)
        assert result.returncode != 0

    def test_unknown_basis_is_broken(self, tmp_path):
        params = {"mode": "stale", "threshold": "90d", "basis": "ctime"}
        assert run(CHECK_SCRIPT, params, tmp_path).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        params = {"mode": "stale", "threshold": "90d", "exclude": "*.log"}
        assert run(CHECK_SCRIPT, params, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {"mode": "stale", "threshold": "90d"}, tmp_path / "nope").returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
