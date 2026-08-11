"""
Tests for empty-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "empty-v1-check.py"


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
    argv += ["--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def populated(tmp_path: Path) -> Path:
    """A directory with real content, so the root itself is never the
    finding and tests can focus on what's inside it."""
    (tmp_path / "occupied.txt").write_text("content")
    return tmp_path


class TestEmptyFiles:

    def test_zero_byte_file_is_reported(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "empty.txt").write_text("")
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "empty.txt" in result["message"]

    def test_file_with_content_is_not_reported(self, tmp_path):
        populated(tmp_path)
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_single_whitespace_byte_is_not_empty(self, tmp_path):
        """Zero bytes is a fact about the file; "looks blank" is not."""
        populated(tmp_path)
        (tmp_path / "space.txt").write_text(" ")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_check_files_false_ignores_them(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "empty.txt").write_text("")
        assert verdict(run_check({"check_files": False}, tmp_path))["status"] == "ok"

    def test_nested_empty_file_found_when_recursive(self, tmp_path):
        populated(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "keep.txt").write_text("x")
        (sub / "empty.txt").write_text("")
        result = verdict(run_check({}, tmp_path))
        assert "sub/empty.txt" in result["message"]

    def test_nested_empty_file_ignored_when_not_recursive(self, tmp_path):
        populated(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "keep.txt").write_text("x")
        (sub / "empty.txt").write_text("")
        assert verdict(run_check({"recursive": False}, tmp_path))["status"] == "ok"


class TestEmptyFolders:

    def test_empty_folder_is_reported(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "hollow").mkdir()
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert "hollow/" in result["message"]

    def test_folder_with_content_is_not_reported(self, tmp_path):
        populated(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "f.txt").write_text("x")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_check_folders_false_ignores_them(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "hollow").mkdir()
        assert verdict(run_check({"check_folders": False}, tmp_path))["status"] == "ok"

    def test_the_scanned_path_itself_is_reported_when_empty(self, tmp_path):
        """A cataloged location that exists but holds nothing is usually
        the finding, not a detail to skip past."""
        result = verdict(run_check({}, tmp_path))
        assert result["status"] == "violation"
        assert str(tmp_path) in result["message"]

    def test_reported_folder_does_not_also_list_its_contents(self, tmp_path):
        """Under "no_files", a tree of empty folders is one finding at the
        top, not one per level."""
        populated(tmp_path)
        (tmp_path / "a" / "b" / "c").mkdir(parents=True)
        result = verdict(run_check({"folder_empty_means": "no_files"}, tmp_path))
        assert "1 empty item" in result["message"]
        assert "a/" in result["message"]
        assert "a/b" not in result["message"]


class TestFolderEmptyMeans:

    def test_no_entries_does_not_flag_a_folder_holding_empty_folders(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "outer" / "inner").mkdir(parents=True)
        result = verdict(run_check({"folder_empty_means": "no_entries"}, tmp_path))
        # only the leaf is literally entry-less; asserted on the count
        # because "outer/" is a substring of "outer/inner/"
        assert "1 empty item(s): outer/inner/" in result["message"]

    def test_no_files_flags_the_whole_hollow_tree_at_its_top(self, tmp_path):
        """The reading that catches what's left after moving a tree's
        contents elsewhere: the parent still has children, so it looks
        occupied while containing nothing."""
        populated(tmp_path)
        (tmp_path / "outer" / "inner").mkdir(parents=True)
        result = verdict(run_check({"folder_empty_means": "no_files"}, tmp_path))
        assert "outer/" in result["message"]

    def test_no_files_respects_a_single_deep_file(self, tmp_path):
        populated(tmp_path)
        deep = tmp_path / "outer" / "inner"
        deep.mkdir(parents=True)
        (deep / "f.txt").write_text("x")
        assert verdict(run_check({"folder_empty_means": "no_files"}, tmp_path))["status"] == "ok"

    def test_rejects_an_unknown_meaning(self, tmp_path):
        assert run_check({"folder_empty_means": "sort_of"}, tmp_path).returncode != 0


class TestExclusions:

    def test_excluded_empty_file_is_not_reported(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "empty.log").write_text("")
        assert verdict(run_check({"exclude": ["*.log"]}, tmp_path))["status"] == "ok"

    def test_excluded_folder_is_not_reported(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "cache").mkdir()
        assert verdict(run_check({"exclude": ["cache"]}, tmp_path))["status"] == "ok"

    def test_exclusion_does_not_make_a_folder_count_as_empty(self, tmp_path):
        """`exclude` controls what's reported, not what counts as content -
        a folder holding only an excluded file still has a file in it."""
        populated(tmp_path)
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "ignored.log").write_text("x")
        assert verdict(run_check({"exclude": ["*.log"]}, tmp_path))["status"] == "ok"


class TestNotReported:

    def test_symlink_is_never_empty(self, tmp_path):
        """A symlink's own size is the length of the path it stores."""
        populated(tmp_path)
        target = tmp_path / "occupied.txt"
        (tmp_path / "link").symlink_to(target)
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_dangling_symlink_is_left_to_link_integrity(self, tmp_path):
        populated(tmp_path)
        (tmp_path / "dangling").symlink_to(tmp_path / "gone.txt")
        assert verdict(run_check({}, tmp_path))["status"] == "ok"

    def test_symlink_to_an_empty_dir_counts_as_content(self, tmp_path):
        """Something deliberately put a link there, so the folder holding
        it isn't empty."""
        populated(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "link").symlink_to(elsewhere)
        result = verdict(run_check({"folder_empty_means": "no_files", "exclude": ["elsewhere"]}, tmp_path))
        assert "sub/" not in result.get("message", "")


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({}, tmp_path, fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({}, tmp_path / "nope").returncode != 0

    def test_rejects_checking_nothing(self, tmp_path):
        """An attachment that can never report anything is a mistake in the
        standard, not a clean bill of health."""
        result = run_check({"check_files": False, "check_folders": False}, tmp_path)
        assert result.returncode != 0
        assert "never report" in result.stderr

    def test_rejects_non_list_exclude(self, tmp_path):
        assert run_check({"exclude": "*.log"}, tmp_path).returncode != 0

    def test_rejects_malformed_params(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
