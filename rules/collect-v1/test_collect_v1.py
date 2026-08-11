"""
Tests for collect-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

This is the one bundled rule whose fixer moves user data, so the fixer
tests assert on where files ended up, not only on the reported status.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "collect-v1-check.py"
FIX_SCRIPT = RULE_DIR / "collect-v1-fix.py"


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params), "--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def run_fix(params: dict, path, fix: bool = True) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(FIX_SCRIPT), "--params", json.dumps(params), "--path", str(path)]
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


class TestWhatGetsSelected:

    def test_loose_files_are_reported(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        (source / "b.txt").write_text("x")
        result = verdict(run_check({"target": str(target)}, source))
        assert result["status"] == "violation"
        assert "2 item(s)" in result["message"]

    def test_empty_source_is_ok(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert verdict(run_check({"target": str(tmp_path / "inbox")}, source))["status"] == "ok"

    def test_keep_holds_entries_back(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "launcher.desktop").write_text("x")
        (source / "loose.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox"), "keep": ["*.desktop"]}, source))
        assert "loose.txt" in result["message"]
        assert "launcher.desktop" not in result["message"]

    def test_move_inverts_the_default(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "scan.pdf").write_text("x")
        (source / "notes.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox"), "move": ["*.pdf"]}, source))
        assert "scan.pdf" in result["message"]
        assert "notes.txt" not in result["message"]

    def test_min_age_leaves_recent_arrivals_alone(self, tmp_path):
        """What makes a daily sweep safe on a folder still being used."""
        source = tmp_path / "desk"
        source.mkdir()
        (source / "fresh.txt").write_text("x")
        old = source / "old.txt"
        old.write_text("x")
        aged(old, 10)
        result = verdict(run_check({"target": str(tmp_path / "inbox"), "min_age": "3d"}, source))
        assert "old.txt" in result["message"]
        assert "fresh.txt" not in result["message"]

    def test_folders_move_whole_by_default(self, tmp_path):
        source = tmp_path / "desk"
        (source / "project" / "deep").mkdir(parents=True)
        (source / "project" / "deep" / "f.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox")}, source))
        assert "1 item(s)" in result["message"]
        assert "project" in result["message"]

    def test_recursive_flattens_files_out_of_subfolders(self, tmp_path):
        source = tmp_path / "desk"
        (source / "project").mkdir(parents=True)
        (source / "project" / "f.txt").write_text("x")
        (source / "top.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox"), "recursive": True}, source))
        assert "project/f.txt" in result["message"]
        assert "2 item(s)" in result["message"]


class TestTargetTemplating:

    def test_strftime_placeholders_are_expanded(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox" / "%Y-%m-%d-dump")}, source))
        assert time.strftime("%Y-%m-%d-dump") in result["message"]

    def test_name_placeholder_expands_to_the_swept_folder(self, tmp_path):
        """What lets one attachment serve several paths."""
        source = tmp_path / "Desktop"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_check({"target": str(tmp_path / "inbox" / "{name}-dump")}, source))
        assert "Desktop-dump" in result["message"]

    def test_relative_target_resolves_against_the_swept_path(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_check({"target": "collected/"}, source))
        assert str(source / "collected") in result["message"]

    def test_target_inside_the_source_is_never_swept_into_itself(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        collected = source / "collected"
        collected.mkdir()
        (collected / "already-here.txt").write_text("x")
        (source / "loose.txt").write_text("x")
        result = verdict(run_check({"target": "collected/"}, source))
        assert "1 item(s)" in result["message"]
        assert "loose.txt" in result["message"]

    def test_target_equal_to_the_source_is_rejected(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        result = run_check({"target": str(source)}, source)
        assert result.returncode != 0
        assert "nothing could move" in result.stderr


class TestTheFixerMoves:

    def test_files_actually_land_in_the_target(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("content-a")
        result = verdict(run_fix({"target": str(target)}, source))
        assert result["status"] == "fixed"
        assert (target / "a.txt").read_text() == "content-a"
        assert not (source / "a.txt").exists()

    def test_target_is_created_when_missing(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox" / "2026-01-01-dump"
        source.mkdir()
        (source / "a.txt").write_text("x")
        assert verdict(run_fix({"target": str(target)}, source))["status"] == "fixed"
        assert target.is_dir()

    def test_create_target_false_reports_unfixable(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = verdict(run_fix({"target": str(target), "create_target": False}, source))
        assert result["status"] == "unfixable"
        assert (source / "a.txt").exists()

    def test_folders_move_whole(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        (source / "project").mkdir(parents=True)
        (source / "project" / "f.txt").write_text("x")
        assert verdict(run_fix({"target": str(target)}, source))["status"] == "fixed"
        assert (target / "project" / "f.txt").read_text() == "x"

    def test_nothing_to_do_is_ok(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert verdict(run_fix({"target": str(tmp_path / "inbox")}, source))["status"] == "ok"

    def test_kept_entries_stay_put(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        (source / "launcher.desktop").write_text("keep me")
        (source / "loose.txt").write_text("x")
        verdict(run_fix({"target": str(target), "keep": ["*.desktop"]}, source))
        assert (source / "launcher.desktop").read_text() == "keep me"
        assert (target / "loose.txt").exists()

    def test_symlinks_move_as_links(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        real = tmp_path / "real.txt"
        real.write_text("x")
        (source / "link").symlink_to(real)
        verdict(run_fix({"target": str(target)}, source))
        assert (target / "link").is_symlink()


class TestConflicts:

    def test_rename_never_overwrites(self, tmp_path):
        """This rule moves things the standard called unimportant enough to
        sweep, which is exactly when destroying an older copy would go
        unnoticed."""
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        target.mkdir()
        (target / "a.txt").write_text("older")
        (source / "a.txt").write_text("newer")
        assert verdict(run_fix({"target": str(target)}, source))["status"] == "fixed"
        assert (target / "a.txt").read_text() == "older"
        assert (target / "a-2.txt").read_text() == "newer"

    def test_rename_preserves_the_extension(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        target.mkdir()
        (target / "scan.pdf").write_text("older")
        (source / "scan.pdf").write_text("newer")
        verdict(run_fix({"target": str(target)}, source))
        assert (target / "scan-2.pdf").exists()

    def test_skip_leaves_the_clash_in_place_and_reports_it(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        target.mkdir()
        (target / "a.txt").write_text("older")
        (source / "a.txt").write_text("newer")
        (source / "b.txt").write_text("x")
        result = verdict(run_fix({"target": str(target), "on_conflict": "skip"}, source))
        assert result["status"] == "violation"
        assert (source / "a.txt").read_text() == "newer"
        assert (target / "b.txt").exists()

    def test_fail_stops_and_reports_unfixable(self, tmp_path):
        source, target = tmp_path / "desk", tmp_path / "inbox"
        source.mkdir()
        target.mkdir()
        (target / "a.txt").write_text("older")
        (source / "a.txt").write_text("newer")
        result = verdict(run_fix({"target": str(target), "on_conflict": "fail"}, source))
        assert result["status"] == "unfixable"
        assert (source / "a.txt").exists()
        assert (target / "a.txt").read_text() == "older"


class TestArgumentHandling:

    def test_checker_rejects_fix(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        result = run_check({"target": str(tmp_path / "inbox")}, source, fix=True)
        assert result.returncode != 0
        assert "collect-v1-fix.py" in result.stderr

    def test_fixer_refuses_to_run_without_fix(self, tmp_path):
        """Otherwise it would move files while looking like a dry run."""
        source = tmp_path / "desk"
        source.mkdir()
        (source / "a.txt").write_text("x")
        result = run_fix({"target": str(tmp_path / "inbox")}, source, fix=False)
        assert result.returncode != 0
        assert (source / "a.txt").exists()

    def test_missing_target_is_rejected(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        result = run_check({}, source)
        assert result.returncode != 0
        assert "target is required" in result.stderr

    def test_fixer_rejects_a_missing_target_too(self, tmp_path):
        """Checker and fixer must refuse the same attachments, or the fixer
        would act on one the report never covered."""
        source = tmp_path / "desk"
        source.mkdir()
        assert run_fix({}, source).returncode != 0

    def test_rejects_unknown_conflict_mode(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert run_check({"target": "x/", "on_conflict": "overwrite"}, source).returncode != 0

    def test_rejects_malformed_duration(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert run_check({"target": "x/", "min_age": "3 fortnights"}, source).returncode != 0

    def test_rejects_non_list_keep(self, tmp_path):
        source = tmp_path / "desk"
        source.mkdir()
        assert run_check({"target": "x/", "keep": "*.txt"}, source).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"target": "x/"}, tmp_path / "nope").returncode != 0
