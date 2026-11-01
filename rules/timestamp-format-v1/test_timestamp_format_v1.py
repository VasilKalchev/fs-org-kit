"""
test_timestamp_format_v1.py - tests for the timestamp-format-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Run from anywhere with: pytest test_timestamp_format_v1.py -v
Or, from the project root, all bundled rules' tests run via: pytest rules/
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "timestamp-format-v1-check.py"

ACCEPTED = ["%Y%m%d_%H%M%S-", "%Y-%m-%d-"]


def run_check(params: dict, path: Path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


class TestNotTimestamped:

    def test_plain_name_is_ok(self, tmp_path):
        (tmp_path / "report.txt").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_name_starting_with_non_date_digits_is_ok(self, tmp_path):
        """A leading digit run that ISN'T a real calendar date/datetime
        (month 13 doesn't exist) must not be treated as an attempt."""
        (tmp_path / "99999999-name.txt").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestCorrectlyFormatted:

    def test_full_datetime_with_underscore_is_ok(self, tmp_path):
        (tmp_path / "20251231_235959-name.ext").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_full_date_with_dashes_is_ok(self, tmp_path):
        (tmp_path / "2025-12-31-name.ext").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_format_with_no_trailing_literal_ignores_whatever_follows(self, tmp_path):
        (tmp_path / "2025-12-31name.ext").touch()
        result = run_check({"formats": ["%Y-%m-%d"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestMalformedTimestamp:

    def test_squashed_datetime_with_no_separator_is_violation(self, tmp_path):
        """20251231235959name - a real 14-digit datetime, but not in the
        accepted formats (which require a separator before the name)."""
        (tmp_path / "20251231235959name.ext").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "20251231235959" in payload["message"]

    def test_date_missing_required_separator_is_violation(self, tmp_path):
        """2025-12-31name - a real date, but the accepted formats
        require a trailing dash before the name that isn't here."""
        (tmp_path / "2025-12-31name.ext").touch()
        result = run_check({"formats": ACCEPTED}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "2025-12-31" in payload["message"]

    def test_underscore_datetime_with_wrong_shape_is_violation(self, tmp_path):
        (tmp_path / "20251231_235959-name.ext").touch()
        result = run_check({"formats": ["%Y-%m-%d-"]}, tmp_path)
        payload = json.loads(result.stdout)
        assert payload["status"] == "violation"
        assert "20251231_235959" in payload["message"]


class TestBoundary:

    def test_longer_digit_run_not_misread_as_shorter_date(self, tmp_path):
        """A 9-digit run starting with a valid 8-digit date must not be
        truncated and accepted as just the date - it's not timestamped
        at all by this rule's rules, since digit 9 doesn't fit anywhere."""
        (tmp_path / "202512311-name.ext").touch()
        result = run_check({"formats": ["%Y%m%d-"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestTargetAndRecursion:

    def test_target_files_ignores_folder_names(self, tmp_path):
        (tmp_path / "20251231235959name").mkdir()
        result = run_check({"formats": ACCEPTED, "target": "files"}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_target_folders_ignores_file_names(self, tmp_path):
        (tmp_path / "20251231235959name.txt").touch()
        result = run_check({"formats": ACCEPTED, "target": "folders"}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_recursive_finds_nested_violation(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "20251231235959name.ext").touch()
        result = run_check({"formats": ACCEPTED, "recursive": True}, tmp_path)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_non_recursive_ignores_nested(self, tmp_path):
        nested = tmp_path / "sub"
        nested.mkdir()
        (nested / "20251231235959name.ext").touch()
        result = run_check({"formats": ACCEPTED, "recursive": False}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestExclude:

    def test_excluded_item_is_ignored(self, tmp_path):
        (tmp_path / "20251231235959name.ext").touch()
        result = run_check({"formats": ACCEPTED, "exclude": ["2025*"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


class TestEdgeCases:

    def test_rejects_fix_flag(self, tmp_path):
        result = run_check({"formats": ACCEPTED}, tmp_path, fix=True)
        assert result.returncode != 0

    def test_empty_formats_is_broken(self, tmp_path):
        result = run_check({"formats": []}, tmp_path)
        assert result.returncode != 0

    def test_missing_formats_is_broken(self, tmp_path):
        result = run_check({}, tmp_path)
        assert result.returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        result = run_check({"formats": ACCEPTED}, tmp_path / "does-not-exist")
        assert result.returncode != 0


class TestExcludePrunes:

    def test_excluding_a_folder_prunes_its_contents(self, tmp_path):
        (tmp_path / "imported").mkdir()
        (tmp_path / "imported" / "20250105 photo.jpg").touch()
        result = run_check({"formats": ACCEPTED, "exclude": ["imported"]}, tmp_path)
        assert json.loads(result.stdout)["status"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
