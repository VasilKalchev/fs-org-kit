"""
test_spelling_abbreviations_v1.py - tests for the spelling-abbreviations-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

This rule is the one bundled rule with a third-party dependency, so
everything except the missing-dependency test itself is skipped when
pyspellchecker isn't installed.

Run from anywhere with: pytest test_spelling_abbreviations_v1.py -v
Or, from the project root, every bundled rule's tests run via: pytest rules/
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "spelling-abbreviations-v1-check.py"

# Words used throughout, verified against the real dictionaries:
#   "report", "notes", "archive" - known English
#   "reprot", "invoces"          - misspellings
#   "cfg", "img", "misc"         - abbreviations no dictionary knows
#   "rechnungen"                 - known German, unknown English
#   "xq"                         - unknown, and short enough to test min_word_length


def run_check(params: dict, path: Path, fix: bool = False, env: dict | None = None) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--path", str(path), "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def status(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["status"]


def message(result: subprocess.CompletedProcess) -> str:
    return json.loads(result.stdout)["message"]


class TestMissingDependency:
    """Runs whether or not pyspellchecker is installed."""

    def test_absent_package_reports_the_install_command(self, tmp_path):
        """Shadows the real package with an importable module that has no
        SpellChecker in it, which is the same ImportError an uninstalled
        package raises - so this holds on a machine that does have it."""
        stub_dir = tmp_path / "stub"
        stub_dir.mkdir()
        (stub_dir / "spellchecker.py").write_text("")
        scanned = tmp_path / "tree"
        scanned.mkdir()

        result = run_check(
            {"abbreviations": []}, scanned,
            env={**os.environ, "PYTHONPATH": str(stub_dir)},
        )
        assert result.returncode != 0
        assert "pip install pyspellchecker" in result.stderr


pytest.importorskip("spellchecker", reason="spelling-abbreviations-v1 requires pyspellchecker")


class TestSpelling:

    def test_correctly_spelled_names_are_ok(self, tmp_path):
        (tmp_path / "report").mkdir()
        (tmp_path / "notes.txt").touch()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"

    def test_a_misspelling_is_a_violation(self, tmp_path):
        (tmp_path / "reprot.txt").touch()
        payload = json.loads(run_check({"abbreviations": []}, tmp_path).stdout)
        assert payload["status"] == "violation"
        assert "reprot.txt" in payload["message"]
        assert "(reprot)" in payload["message"]

    def test_only_the_offending_word_is_named(self, tmp_path):
        """The name is reported whole, but the parenthesized list holds
        just the words that weren't recognized."""
        (tmp_path / "monthly-invoces-archive").mkdir()
        text = message(run_check({"abbreviations": []}, tmp_path))
        assert text.endswith("monthly-invoces-archive (invoces)")

    def test_several_bad_words_in_one_name(self, tmp_path):
        (tmp_path / "reprot-invoces").mkdir()
        text = message(run_check({"abbreviations": []}, tmp_path))
        assert "invoces" in text and "reprot" in text

    def test_empty_directory_is_ok(self, tmp_path):
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"


class TestWordSplitting:

    @pytest.mark.parametrize("name", ["monthly-reprot", "monthly_reprot", "monthly reprot"])
    def test_names_split_on_dash_underscore_and_space(self, tmp_path, name):
        (tmp_path / name).mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "violation"

    def test_a_files_extension_is_not_spell_checked(self, tmp_path):
        """Files are checked on their stem - file-extensions-v1 is the
        rule about which extensions are acceptable."""
        (tmp_path / "report.zzqx").touch()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"

    def test_a_folders_whole_name_is_checked(self, tmp_path):
        (tmp_path / "report.zzqx").mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "violation"

    def test_matching_is_case_insensitive(self, tmp_path):
        (tmp_path / "REPORT").mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"


class TestAbbreviationsAndIgnore:

    def test_a_declared_abbreviation_is_accepted(self, tmp_path):
        (tmp_path / "cfg").mkdir()
        assert status(run_check({"abbreviations": ["cfg"]}, tmp_path)) == "ok"

    def test_an_undeclared_abbreviation_is_a_violation(self, tmp_path):
        (tmp_path / "cfg").mkdir()
        assert status(run_check({"abbreviations": ["img"]}, tmp_path)) == "violation"

    def test_abbreviations_match_case_insensitively(self, tmp_path):
        (tmp_path / "CFG").mkdir()
        assert status(run_check({"abbreviations": ["cfg"]}, tmp_path)) == "ok"

    def test_ignore_accepts_a_word_that_is_no_abbreviation(self, tmp_path):
        """Proper nouns, brand names, codenames - correctly spelled in no
        dictionary, but not shorthand for anything either."""
        (tmp_path / "kalchev-archive").mkdir()
        assert status(run_check({"abbreviations": [], "ignore": ["kalchev"]}, tmp_path)) == "ok"

    def test_the_two_lists_are_interchangeable_to_the_checker(self, tmp_path):
        (tmp_path / "cfg").mkdir()
        assert status(run_check({"abbreviations": [], "ignore": ["cfg"]}, tmp_path)) == "ok"

    def test_a_missing_abbreviations_param_checks_everything(self, tmp_path):
        """`abbreviations` has no manifest default on purpose; an absent
        one means "no shorthand is sanctioned", not "skip the check"."""
        (tmp_path / "cfg").mkdir()
        assert status(run_check({}, tmp_path)) == "violation"


class TestLanguages:

    def test_english_only_flags_a_german_word(self, tmp_path):
        (tmp_path / "rechnungen").mkdir()
        assert status(run_check({"abbreviations": [], "languages": ["en"]}, tmp_path)) == "violation"

    def test_a_word_known_in_any_listed_language_is_accepted(self, tmp_path):
        (tmp_path / "rechnungen").mkdir()
        params = {"abbreviations": [], "languages": ["en", "de"]}
        assert status(run_check(params, tmp_path)) == "ok"

    def test_a_word_in_no_listed_language_is_still_a_violation(self, tmp_path):
        (tmp_path / "reprot").mkdir()
        params = {"abbreviations": [], "languages": ["en", "de"]}
        assert status(run_check(params, tmp_path)) == "violation"

    def test_an_unknown_language_code_is_broken(self, tmp_path):
        result = run_check({"abbreviations": [], "languages": ["xx"]}, tmp_path)
        assert result.returncode != 0
        assert "spell checker" in result.stderr

    def test_an_empty_language_list_is_broken(self, tmp_path):
        assert run_check({"abbreviations": [], "languages": []}, tmp_path).returncode != 0

    def test_a_non_list_language_is_broken(self, tmp_path):
        assert run_check({"abbreviations": [], "languages": "en"}, tmp_path).returncode != 0


class TestWordFilters:

    def test_short_words_are_skipped_by_default(self, tmp_path):
        (tmp_path / "xq-archive").mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"

    def test_lowering_min_word_length_catches_them(self, tmp_path):
        (tmp_path / "xq-archive").mkdir()
        assert status(run_check({"abbreviations": [], "min_word_length": 2}, tmp_path)) == "violation"

    def test_raising_min_word_length_lets_a_misspelling_through(self, tmp_path):
        (tmp_path / "reprot").mkdir()
        assert status(run_check({"abbreviations": [], "min_word_length": 20}, tmp_path)) == "ok"

    def test_a_purely_numeric_name_is_accepted(self, tmp_path):
        (tmp_path / "2026").mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "ok"

    def test_a_numeric_name_is_accepted_with_numbers_ok_off_too(self, tmp_path):
        """`numbers_ok` skips a purely-numeric word before it reaches the
        dictionary; the dictionary happens to accept digit runs anyway, so
        turning the flag off changes nothing here. It exists so the rule
        doesn't depend on that."""
        (tmp_path / "2026").mkdir()
        assert status(run_check({"abbreviations": [], "numbers_ok": False}, tmp_path)) == "ok"

    def test_a_word_with_digits_in_it_is_not_numeric(self, tmp_path):
        (tmp_path / "photo2026").mkdir()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "violation"


class TestTargetAndTraversal:

    def test_target_files_ignores_folder_names(self, tmp_path):
        (tmp_path / "reprot").mkdir()
        assert status(run_check({"abbreviations": [], "target": "files"}, tmp_path)) == "ok"

    def test_target_folders_ignores_file_names(self, tmp_path):
        (tmp_path / "reprot.txt").touch()
        assert status(run_check({"abbreviations": [], "target": "folders"}, tmp_path)) == "ok"

    def test_recursive_by_default(self, tmp_path):
        nested = tmp_path / "archive"
        nested.mkdir()
        (nested / "reprot.txt").touch()
        assert status(run_check({"abbreviations": []}, tmp_path)) == "violation"

    def test_recursive_false_stays_at_the_top(self, tmp_path):
        nested = tmp_path / "archive"
        nested.mkdir()
        (nested / "reprot.txt").touch()
        assert status(run_check({"abbreviations": [], "recursive": False}, tmp_path)) == "ok"

    def test_a_nested_item_is_named_by_its_relative_path(self, tmp_path):
        nested = tmp_path / "archive"
        nested.mkdir()
        (nested / "reprot.txt").touch()
        assert "archive/reprot.txt" in message(run_check({"abbreviations": []}, tmp_path))

    def test_exclude_by_bare_name(self, tmp_path):
        (tmp_path / "reprot.txt").touch()
        assert status(run_check({"abbreviations": [], "exclude": ["reprot.txt"]}, tmp_path)) == "ok"

    def test_exclude_glob_matches_a_nested_path(self, tmp_path):
        nested = tmp_path / "vendor"
        nested.mkdir()
        (nested / "reprot.txt").touch()
        params = {"abbreviations": [], "exclude": ["vendor/*"]}
        assert status(run_check(params, tmp_path)) == "ok"


class TestMessage:

    def test_truncates_past_ten_with_a_count(self, tmp_path):
        for i in range(13):
            (tmp_path / f"reprot{i:02d}").mkdir()
        text = message(run_check({"abbreviations": [], "min_word_length": 3}, tmp_path))
        assert text.startswith("13 item(s)")
        assert "and 3 more" in text


class TestArguments:

    def test_rejects_fix_flag(self, tmp_path):
        """This rule has no fixer - --fix must be refused, not silently ignored."""
        assert run_check({"abbreviations": []}, tmp_path, fix=True).returncode != 0

    def test_unknown_target_is_broken(self, tmp_path):
        assert run_check({"abbreviations": [], "target": "links"}, tmp_path).returncode != 0

    def test_non_list_exclude_is_broken(self, tmp_path):
        assert run_check({"abbreviations": [], "exclude": "a.txt"}, tmp_path).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"abbreviations": []}, tmp_path / "nope").returncode != 0

    def test_malformed_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
