"""
Tests for changed-since-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

Every test that compares two states runs the script twice against the
same --cache-dir, which is exactly how the runner drives a caching rule.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "changed-since-v1-check.py"


def run_check(params: dict, path, cache_dir=None, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params), "--path", str(path)]
    if cache_dir is not None:
        argv += ["--cache-dir", str(cache_dir)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def cache(tmp_path: Path) -> Path:
    """A stand-in for the rule-private directory the runner hands over."""
    d = tmp_path / "cache"
    d.mkdir(exist_ok=True)
    return d


def tree(tmp_path: Path) -> Path:
    watched = tmp_path / "watched"
    watched.mkdir()
    (watched / "stable.txt").write_text("unchanged")
    return watched


def touch_later(path: Path) -> None:
    """Move a file's mtime forward. Writing alone can leave it unchanged
    when both writes land in the same filesystem timestamp tick."""
    future = time.time() + 10
    os.utime(path, (future, future))


class TestBaseline:

    def test_first_run_records_a_baseline_and_reports_ok(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        assert verdict(run_check({}, watched, c)) == {"status": "ok"}

    def test_second_run_with_no_changes_is_ok(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        assert verdict(run_check({}, watched, c)) == {"status": "ok"}

    def test_without_a_cache_dir_every_run_is_a_first_run(self, tmp_path):
        """The rule must still work when the runner can't give it a cache
        directory - by not comparing at all, never by picking its own."""
        watched = tree(tmp_path)
        assert verdict(run_check({}, watched)) == {"status": "ok"}
        (watched / "new.txt").write_text("x")
        assert verdict(run_check({}, watched)) == {"status": "ok"}

    def test_separate_paths_get_separate_baselines(self, tmp_path):
        c = cache(tmp_path)
        first, second = tmp_path / "one", tmp_path / "two"
        for d in (first, second):
            d.mkdir()
            (d / "a.txt").write_text("x")
        run_check({}, first, c)
        run_check({}, second, c)
        (first / "added.txt").write_text("x")
        assert verdict(run_check({}, first, c))["status"] == "violation"
        assert verdict(run_check({}, second, c))["status"] == "ok"

    def test_a_corrupt_snapshot_is_treated_as_no_snapshot(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        for stored in c.glob("*.json"):
            stored.write_text("{ this is not a snapshot")
        (watched / "added.txt").write_text("x")
        assert verdict(run_check({}, watched, c))["status"] == "ok"


class TestDetectingChanges:

    def test_added_file_is_reported(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        (watched / "added.txt").write_text("x")
        result = verdict(run_check({}, watched, c))
        assert result["status"] == "violation"
        assert "+added.txt" in result["message"]
        assert "1 added" in result["message"]

    def test_removed_file_is_reported(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        (watched / "doomed.txt").write_text("x")
        run_check({}, watched, c)
        (watched / "doomed.txt").unlink()
        result = verdict(run_check({}, watched, c))
        assert "-doomed.txt" in result["message"]
        assert "1 removed" in result["message"]

    def test_modified_file_is_reported(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        (watched / "stable.txt").write_text("different content")
        result = verdict(run_check({}, watched, c))
        assert "~stable.txt" in result["message"]
        assert "1 modified" in result["message"]

    def test_added_directory_is_reported(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        (watched / "newdir").mkdir()
        assert "+newdir" in verdict(run_check({}, watched, c))["message"]

    def test_nested_change_found_when_recursive(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        sub = watched / "sub"
        sub.mkdir()
        run_check({}, watched, c)
        (sub / "deep.txt").write_text("x")
        assert "sub/deep.txt" in verdict(run_check({}, watched, c))["message"]

    def test_nested_change_ignored_when_not_recursive(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        sub = watched / "sub"
        sub.mkdir()
        run_check({"recursive": False}, watched, c)
        (sub / "deep.txt").write_text("x")
        assert verdict(run_check({"recursive": False}, watched, c))["status"] == "ok"

    def test_a_folder_is_never_reported_as_modified(self, tmp_path):
        """A folder's own mtime moves whenever anything inside it appears
        or disappears. Tracking that would report one edit twice when
        recursive, and would leak deep edits when not."""
        watched, c = tree(tmp_path), cache(tmp_path)
        sub = watched / "sub"
        sub.mkdir()
        run_check({}, watched, c)
        (sub / "deep.txt").write_text("x")
        message = verdict(run_check({}, watched, c))["message"]
        assert "+sub/deep.txt" in message
        assert "~sub" not in message
        assert "1 change(s)" in message

    def test_excluded_entries_never_register(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({"exclude": ["*.log"]}, watched, c)
        (watched / "noisy.log").write_text("x")
        assert verdict(run_check({"exclude": ["*.log"]}, watched, c))["status"] == "ok"


class TestTrackModes:

    def test_size_only_ignores_a_pure_timestamp_change(self, tmp_path):
        """The honest choice for a tree restored from backups or synced
        with tools that rewrite timestamps."""
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({"track": "size"}, watched, c)
        touch_later(watched / "stable.txt")
        assert verdict(run_check({"track": "size"}, watched, c))["status"] == "ok"

    def test_both_notices_a_pure_timestamp_change(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        touch_later(watched / "stable.txt")
        assert verdict(run_check({}, watched, c))["status"] == "violation"

    def test_size_only_ignores_a_same_length_edit(self, tmp_path):
        """The blind spot size-only tracking accepts in exchange for
        surviving timestamp rewrites: content replaced byte for byte."""
        watched, c = tree(tmp_path), cache(tmp_path)
        stable = watched / "stable.txt"
        run_check({"track": "size"}, watched, c)
        stable.write_text("X" * len(stable.read_text()))
        touch_later(stable)
        assert verdict(run_check({"track": "size"}, watched, c))["status"] == "ok"

    def test_mtime_only_catches_that_same_edit(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        stable = watched / "stable.txt"
        run_check({"track": "mtime"}, watched, c)
        stable.write_text("X" * len(stable.read_text()))
        touch_later(stable)
        assert verdict(run_check({"track": "mtime"}, watched, c))["status"] == "violation"

    def test_file_becoming_a_directory_is_a_change_under_any_mode(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        swap = watched / "swap"
        swap.write_text("")
        run_check({"track": "size"}, watched, c)
        swap.unlink()
        swap.mkdir()
        assert verdict(run_check({"track": "size"}, watched, c))["status"] == "violation"


class TestUpdateBaseline:

    def test_baseline_advances_by_default(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        (watched / "added.txt").write_text("x")
        assert verdict(run_check({}, watched, c))["status"] == "violation"
        assert verdict(run_check({}, watched, c))["status"] == "ok"

    def test_update_baseline_false_keeps_reporting(self, tmp_path):
        """So a change stays reported until someone deals with it, instead
        of becoming the new normal on the next run."""
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({"update_baseline": False}, watched, c)
        (watched / "added.txt").write_text("x")
        assert verdict(run_check({"update_baseline": False}, watched, c))["status"] == "violation"
        assert verdict(run_check({"update_baseline": False}, watched, c))["status"] == "violation"


class TestReportFormats:

    def _three_changes(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        deep = watched / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "old.txt").write_text("x")
        run_check({}, watched, c)
        (deep / "new.txt").write_text("x")
        (deep / "old.txt").unlink()
        return watched, c

    def test_summary_is_one_line(self, tmp_path):
        watched, c = self._three_changes(tmp_path)
        message = verdict(run_check({"report": "summary"}, watched, c))["message"]
        assert "\n" not in message

    def test_list_puts_each_change_on_its_own_line(self, tmp_path):
        watched, c = self._three_changes(tmp_path)
        message = verdict(run_check({"report": "list"}, watched, c))["message"]
        assert "+ a/b/new.txt" in message
        assert "- a/b/old.txt" in message

    def test_tree_draws_the_hierarchy_with_markers(self, tmp_path):
        watched, c = self._three_changes(tmp_path)
        message = verdict(run_check({"report": "tree"}, watched, c))["message"]
        assert "-- + new.txt" in message
        assert "-- - old.txt" in message
        # intermediate directories appear as structure, without a marker
        assert "a" in message and "b" in message
        assert "a/b/new.txt" not in message

    def test_tree_collapses_unchanged_branches(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        quiet = watched / "quiet"
        quiet.mkdir()
        (quiet / "untouched.txt").write_text("x")
        noisy = watched / "noisy"
        noisy.mkdir()
        run_check({}, watched, c)
        (noisy / "new.txt").write_text("x")
        message = verdict(run_check({"report": "tree"}, watched, c))["message"]
        assert "new.txt" in message
        assert "untouched.txt" not in message

    def test_max_reported_truncates_and_says_so(self, tmp_path):
        watched, c = tree(tmp_path), cache(tmp_path)
        run_check({}, watched, c)
        for i in range(10):
            (watched / f"f{i}.txt").write_text("x")
        message = verdict(run_check({"max_reported": 3}, watched, c))["message"]
        assert "10 change(s)" in message
        assert "7 more" in message


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({}, tree(tmp_path), cache(tmp_path), fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({}, tmp_path / "nope", cache(tmp_path)).returncode != 0

    def test_rejects_unknown_track_mode(self, tmp_path):
        assert run_check({"track": "content"}, tree(tmp_path), cache(tmp_path)).returncode != 0

    def test_rejects_unknown_report_mode(self, tmp_path):
        assert run_check({"report": "graph"}, tree(tmp_path), cache(tmp_path)).returncode != 0

    def test_rejects_non_positive_max_reported(self, tmp_path):
        assert run_check({"max_reported": 0}, tree(tmp_path), cache(tmp_path)).returncode != 0

    def test_rejects_non_list_exclude(self, tmp_path):
        assert run_check({"exclude": "*.log"}, tree(tmp_path), cache(tmp_path)).returncode != 0
