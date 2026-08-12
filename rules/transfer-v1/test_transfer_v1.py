"""
Tests for transfer-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

This rule's fixer moves/copies user data, so its tests assert on where
files ended up, not only on the reported status.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "transfer-v1-check.py"
FIX_SCRIPT = RULE_DIR / "transfer-v1-fix.py"


def run_check(params: dict, paths: list, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
    for p in paths:
        argv += ["--paths", str(p)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def run_fix(params: dict, paths: list, fix: bool = True) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(FIX_SCRIPT), "--params", json.dumps(params)]
    for p in paths:
        argv += ["--paths", str(p)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def aged(path: Path, days: int) -> Path:
    old = time.time() - days * 86400
    os.utime(path, (old, old))
    return path


def base_params(**overrides) -> dict:
    params = {"operation": "move", "direction": "forward"}
    params.update(overrides)
    return params


class TestSelection:

    def test_loose_files_are_reported(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        (source / "b.txt").write_text("x")
        result = verdict(run_check(base_params(), [source, target]))
        assert result["status"] == "violation"
        assert "2 item(s)" in result["message"]

    def test_empty_source_is_ok(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert verdict(run_check(base_params(), [source, tmp_path / "inbox"]))["status"] == "ok"

    def test_exclude_holds_entries_back(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "launcher.desktop").write_text("x")
        (source / "loose.txt").write_text("x")
        result = verdict(run_check(base_params(exclude=["*.desktop"]), [source, tmp_path / "inbox"]))
        assert "loose.txt" in result["message"]
        assert "launcher.desktop" not in result["message"]

    def test_min_age_leaves_recent_arrivals_alone(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "fresh.txt").write_text("x")
        old = source / "old.txt"
        old.write_text("x")
        aged(old, 10)
        result = verdict(run_check(base_params(min_age="3d"), [source, tmp_path / "inbox"]))
        assert "old.txt" in result["message"]
        assert "fresh.txt" not in result["message"]

    def test_folders_move_whole_by_default(self, tmp_path):
        source = tmp_path / "desk"
        (source / "project" / "deep").mkdir(parents=True)
        (source / "project" / "deep" / "f.txt").write_text("x")
        result = verdict(run_check(base_params(), [source, tmp_path / "inbox"]))
        assert "1 item(s)" in result["message"]

    def test_recursive_flattens_into_the_target(self, tmp_path):
        source = tmp_path / "desk"
        (source / "sub").mkdir(parents=True)
        (source / "sub" / "f.txt").write_text("x")
        result = verdict(run_check(base_params(recursive=True), [source, tmp_path / "inbox"]))
        assert "1 item(s)" in result["message"]
        assert "f.txt" in result["message"]

    def test_dated_target_expands_strftime(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        stamp = time.strftime("%Y-%m-%d")
        result = verdict(run_check(base_params(), [source, tmp_path / f"inbox/{stamp}-dump"]))
        assert f"{stamp}-dump" in result["message"]

    def test_name_placeholder_expands_to_source_basename(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_check(base_params(), [source, tmp_path / "archive/{name}-copy"]))
        assert "desk-copy" in result["message"]

    def test_direction_reverse_swaps_source_and_target(self, tmp_path):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        (b / "f.txt").write_text("x")
        result = verdict(run_check(base_params(direction="reverse"), [a, b]))
        assert result["status"] == "violation"
        assert "f.txt" in result["message"]

    def test_target_nested_in_source_does_not_collect_itself(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        target = source / "_archive" / "dump"
        (source / "_archive").mkdir()
        result = verdict(run_check(base_params(), [source, target]))
        assert result["status"] == "violation"
        assert "1 item(s)" in result["message"]
        assert "a.txt" in result["message"]


class TestMoveFixer:

    def test_moves_files_and_empties_the_source(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_fix(base_params(), [source, target]))
        assert result["status"] == "fixed"
        assert (target / "a.txt").exists()
        assert not (source / "a.txt").exists()

    def test_moves_a_folder_whole(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        (source / "project").mkdir(parents=True)
        (source / "project" / "f.txt").write_text("x")
        result = verdict(run_fix(base_params(), [source, target]))
        assert result["status"] == "fixed"
        assert (target / "project" / "f.txt").exists()
        assert not (source / "project").exists()

    def test_rechecking_after_a_move_is_ok(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        assert verdict(run_fix(base_params(), [source, target]))["status"] == "fixed"
        assert verdict(run_check(base_params(), [source, target]))["status"] == "ok"

    def test_creates_the_target_by_default(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox" / "dated"
        source.mkdir()
        (source / "a.txt").write_text("x")
        verdict(run_fix(base_params(), [source, target]))
        assert target.is_dir()

    def test_create_target_false_reports_unfixable(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_fix(base_params(create_target=False), [source, target]))
        assert result["status"] == "unfixable"
        assert not target.exists()

    def test_conflict_default_renames(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("existing")
        source.mkdir()
        (source / "a.txt").write_text("new")
        result = verdict(run_fix(base_params(), [source, target]))
        assert result["status"] == "fixed"
        assert (target / "a.txt").read_text() == "existing"
        assert (target / "a-2.txt").read_text() == "new"

    def test_conflict_skip_leaves_source_entry_and_reports_it(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("existing")
        source.mkdir()
        (source / "a.txt").write_text("new")
        result = verdict(run_fix(base_params(on_conflict="skip"), [source, target]))
        assert result["status"] == "violation"
        assert (source / "a.txt").exists()
        assert "left in place" in result["message"]

    def test_conflict_fail_stops_and_reports_unfixable(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("existing")
        source.mkdir()
        (source / "a.txt").write_text("new")
        result = verdict(run_fix(base_params(on_conflict="fail"), [source, target]))
        assert result["status"] == "unfixable"
        assert (source / "a.txt").exists()

    def test_nothing_is_ever_overwritten(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("must-survive")
        source.mkdir()
        (source / "a.txt").write_text("new")
        for mode in ("rename", "skip", "fail"):
            verdict(run_fix(base_params(on_conflict=mode), [source, target]))
        assert (target / "a.txt").read_text() == "must-survive"


class TestCopyFixer:

    def test_copies_and_leaves_the_source_intact(self, tmp_path):
        source, target = tmp_path / "lib", tmp_path / "mirror"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_fix(base_params(operation="copy"), [source, target]))
        assert result["status"] == "fixed"
        assert (target / "a.txt").exists()
        assert (source / "a.txt").exists()

    def test_rechecking_after_a_copy_is_ok(self, tmp_path):
        """The source keeping its own copy isn't evidence anything is
        still outstanding - only the target's state is."""
        source, target = tmp_path / "lib", tmp_path / "mirror"
        source.mkdir()
        (source / "a.txt").write_text("x")
        verdict(run_fix(base_params(operation="copy"), [source, target]))
        assert verdict(run_check(base_params(operation="copy"), [source, target]))["status"] == "ok"

    def test_copies_a_folder_whole(self, tmp_path):
        source, target = tmp_path / "lib", tmp_path / "mirror"
        (source / "project").mkdir(parents=True)
        (source / "project" / "f.txt").write_text("x")
        verdict(run_fix(base_params(operation="copy"), [source, target]))
        assert (target / "project" / "f.txt").exists()
        assert (source / "project" / "f.txt").exists()


class TestSyncFixer:

    def test_missing_entries_are_synced(self, tmp_path):
        source, target = tmp_path / "lib", tmp_path / "mirror"
        target.mkdir(parents=True)
        (target / "already.txt").write_text("keep")
        source.mkdir()
        (source / "already.txt").write_text("ignored")
        (source / "new.txt").write_text("x")
        result = verdict(run_fix(base_params(operation="sync"), [source, target]))
        assert result["status"] == "fixed"
        assert (target / "new.txt").exists()
        assert (target / "already.txt").read_text() == "keep"

    def test_an_entry_already_at_the_target_is_not_a_violation(self, tmp_path):
        source, target = tmp_path / "lib", tmp_path / "mirror"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("x")
        source.mkdir()
        (source / "a.txt").write_text("x")
        assert verdict(run_check(base_params(operation="sync"), [source, target]))["status"] == "ok"

    def test_fully_synced_source_is_ok_after_fixing(self, tmp_path):
        source, target = tmp_path / "lib", tmp_path / "mirror"
        target.mkdir(parents=True)
        (target / "a.txt").write_text("x")
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_fix(base_params(operation="sync"), [source, target]))
        assert result["status"] == "ok"


class TestArgumentHandling:

    def test_checker_rejects_fix(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(), [source, target], fix=True).returncode != 0

    def test_fixer_refuses_to_run_without_fix(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_fix(base_params(), [source, target], fix=False).returncode != 0

    def test_requires_exactly_two_paths(self, tmp_path):
        source = tmp_path / "a"
        source.mkdir()
        assert run_check(base_params(), [source]).returncode != 0

    def test_missing_operation_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        params = {"direction": "forward"}
        assert run_check(params, [source, target]).returncode != 0

    def test_unknown_operation_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(operation="rsync"), [source, target]).returncode != 0

    def test_missing_direction_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        params = {"operation": "move"}
        assert run_check(params, [source, target]).returncode != 0

    def test_unknown_direction_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(direction="sideways"), [source, target]).returncode != 0

    def test_unknown_on_conflict_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(on_conflict="overwrite"), [source, target]).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(exclude="*.txt"), [source, target]).returncode != 0

    def test_nonexistent_source_is_broken(self, tmp_path):
        assert run_check(base_params(), [tmp_path / "nope", tmp_path / "b"]).returncode != 0

    def test_source_and_target_the_same_path_is_broken(self, tmp_path):
        source = tmp_path / "a"
        source.mkdir()
        assert run_check(base_params(), [source, source]).returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--paths", str(source), "--paths", str(target),
             "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0

    def test_invalid_min_age_is_broken(self, tmp_path):
        source, target = tmp_path / "a", tmp_path / "b"
        source.mkdir()
        assert run_check(base_params(min_age="soon"), [source, target]).returncode != 0


if __name__ == "__main__":
    import pytest
    pytest.main([__file__, "-v"])
