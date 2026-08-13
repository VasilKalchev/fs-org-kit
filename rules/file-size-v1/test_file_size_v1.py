"""
Tests for file-size-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

Sizes are given in bare bytes so fixtures stay small; the unit parsing
(MiB/GiB/...) is covered separately.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "file-size-v1-check.py"


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params),
            "--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def write(path: Path, size: int) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    return path


class TestMaxSize:

    def test_file_under_the_limit_is_ok(self, tmp_path):
        write(tmp_path / "small.bin", 50)
        assert verdict(run_check({"max_size": 100}, tmp_path)) == {"status": "ok"}

    def test_file_over_the_limit_is_a_violation(self, tmp_path):
        write(tmp_path / "big.bin", 150)
        result = verdict(run_check({"max_size": 100}, tmp_path))
        assert result["status"] == "violation"
        assert "big.bin" in result["message"]

    def test_file_exactly_at_the_limit_is_ok(self, tmp_path):
        """The threshold is inclusive - `>` not `>=`."""
        write(tmp_path / "exact.bin", 100)
        assert verdict(run_check({"max_size": 100}, tmp_path)) == {"status": "ok"}

    def test_total_under_limit_still_flags_one_big_file(self, tmp_path):
        """The distinction from folder-structure-v1: this is per file."""
        write(tmp_path / "big.bin", 150)
        write(tmp_path / "tiny.bin", 1)
        assert verdict(run_check({"max_size": 100}, tmp_path))["status"] == "violation"

    def test_many_small_files_never_aggregate(self, tmp_path):
        """The other half of that distinction - 20x50B is not one 1000B file."""
        for i in range(20):
            write(tmp_path / f"f{i}.bin", 50)
        assert verdict(run_check({"max_size": 100}, tmp_path)) == {"status": "ok"}

    def test_message_reports_the_size(self, tmp_path):
        write(tmp_path / "big.bin", 2048)
        message = verdict(run_check({"max_size": 1024}, tmp_path))["message"]
        assert "2.0KiB" in message and "1.0KiB" in message

    def test_long_violation_list_is_truncated(self, tmp_path):
        for i in range(9):
            write(tmp_path / f"big{i}.bin", 150)
        message = verdict(run_check({"max_size": 100}, tmp_path))["message"]
        assert "9 file(s)" in message and "and 4 more" in message


class TestMinSize:

    def test_file_above_the_minimum_is_ok(self, tmp_path):
        write(tmp_path / "fine.bin", 150)
        assert verdict(run_check({"min_size": 100}, tmp_path)) == {"status": "ok"}

    def test_file_below_the_minimum_is_a_violation(self, tmp_path):
        write(tmp_path / "truncated.bin", 10)
        result = verdict(run_check({"min_size": 100}, tmp_path))
        assert result["status"] == "violation"
        assert "truncated.bin" in result["message"]

    def test_file_exactly_at_the_minimum_is_ok(self, tmp_path):
        write(tmp_path / "exact.bin", 100)
        assert verdict(run_check({"min_size": 100}, tmp_path)) == {"status": "ok"}

    def test_empty_file_violates_any_minimum(self, tmp_path):
        write(tmp_path / "empty.bin", 0)
        assert verdict(run_check({"min_size": 1}, tmp_path))["status"] == "violation"

    def test_both_thresholds_report_independently(self, tmp_path):
        write(tmp_path / "big.bin", 500)
        write(tmp_path / "small.bin", 5)
        write(tmp_path / "fine.bin", 100)
        message = verdict(run_check({"max_size": 200, "min_size": 50}, tmp_path))["message"]
        assert "big.bin" in message and "small.bin" in message
        assert "fine.bin" not in message


class TestSizeUnits:

    def test_binary_units_are_understood(self, tmp_path):
        write(tmp_path / "one-mib.bin", 1024 * 1024 + 1)
        assert verdict(run_check({"max_size": "1MiB"}, tmp_path))["status"] == "violation"
        assert verdict(run_check({"max_size": "2MiB"}, tmp_path)) == {"status": "ok"}

    def test_unit_case_and_spacing_are_flexible(self, tmp_path):
        write(tmp_path / "f.bin", 2048)
        for spelling in ("1kib", "1 KiB", "1KIB"):
            assert verdict(run_check({"max_size": spelling}, tmp_path))["status"] == "violation"

    def test_bare_number_is_bytes(self, tmp_path):
        write(tmp_path / "f.bin", 150)
        assert verdict(run_check({"max_size": "100"}, tmp_path))["status"] == "violation"


class TestFilters:

    def test_recursive_by_default(self, tmp_path):
        write(tmp_path / "sub" / "deep.bin", 150)
        assert verdict(run_check({"max_size": 100}, tmp_path))["status"] == "violation"

    def test_non_recursive_ignores_subfolders(self, tmp_path):
        write(tmp_path / "sub" / "deep.bin", 150)
        write(tmp_path / "top.bin", 10)
        assert verdict(run_check({"max_size": 100, "recursive": False}, tmp_path)) == {"status": "ok"}

    def test_extensions_narrow_the_check(self, tmp_path):
        write(tmp_path / "movie.mp4", 150)
        write(tmp_path / "notes.txt", 150)
        message = verdict(run_check({"max_size": 100, "extensions": ["mp4"]}, tmp_path))["message"]
        assert "movie.mp4" in message and "notes.txt" not in message

    def test_extensions_ignore_case_and_leading_dot(self, tmp_path):
        write(tmp_path / "MOVIE.MP4", 150)
        assert verdict(run_check({"max_size": 100, "extensions": [".mp4"]},
                                 tmp_path))["status"] == "violation"

    def test_exclude_by_name(self, tmp_path):
        write(tmp_path / "big.bin", 150)
        assert verdict(run_check({"max_size": 100, "exclude": ["big.bin"]},
                                 tmp_path)) == {"status": "ok"}

    def test_exclude_prunes_the_whole_subtree(self, tmp_path):
        write(tmp_path / "cache" / "nested" / "big.bin", 150)
        assert verdict(run_check({"max_size": 100, "exclude": ["cache"]},
                                 tmp_path)) == {"status": "ok"}

    def test_exclude_matches_relative_to_the_scanned_path(self, tmp_path):
        """A pattern that spells out the full path from --path (as the
        manifest documents) must match a nested file - and a pattern that
        only happens to match the *tail* of that path must not."""
        write(tmp_path / "a" / "b" / "big.bin", 150)
        assert verdict(run_check({"max_size": 100, "exclude": ["a/b/big.bin"]},
                                 tmp_path)) == {"status": "ok"}
        assert verdict(run_check({"max_size": 100, "exclude": ["b/big.bin"]},
                                 tmp_path))["status"] == "violation"


class TestNotReported:

    def test_symlinks_are_skipped(self, tmp_path):
        """A symlink's own size is its target path, and following it would
        measure a file outside the tree being checked."""
        outside = tmp_path.parent / "outside.bin"
        write(outside, 500)
        target = tmp_path / "linked.bin"
        target.symlink_to(outside)
        assert verdict(run_check({"max_size": 100}, tmp_path)) == {"status": "ok"}

    def test_folders_have_no_size_of_their_own(self, tmp_path):
        (tmp_path / "empty-folder").mkdir()
        assert verdict(run_check({"min_size": 1}, tmp_path)) == {"status": "ok"}


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({"max_size": 100}, tmp_path, fix=True).returncode != 0

    def test_no_threshold_at_all_is_broken(self, tmp_path):
        """Reporting ok would look like a passing check, not the mistake it is."""
        result = run_check({}, tmp_path)
        assert result.returncode != 0
        assert "max_size" in result.stderr

    def test_min_above_max_is_broken(self, tmp_path):
        result = run_check({"max_size": 100, "min_size": 200}, tmp_path)
        assert result.returncode != 0
        assert "no file could satisfy both" in result.stderr

    def test_unparseable_size_is_broken(self, tmp_path):
        assert run_check({"max_size": "500 bananas"}, tmp_path).returncode != 0

    def test_unknown_unit_is_broken(self, tmp_path):
        assert run_check({"max_size": "5PiB"}, tmp_path).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        assert run_check({"max_size": 100, "exclude": "big.bin"}, tmp_path).returncode != 0

    def test_non_list_extensions_is_broken(self, tmp_path):
        assert run_check({"max_size": 100, "extensions": "mp4"}, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"max_size": 100}, tmp_path / "nope").returncode != 0

    def test_invalid_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{oops"],
            capture_output=True, text=True)
        assert result.returncode != 0
