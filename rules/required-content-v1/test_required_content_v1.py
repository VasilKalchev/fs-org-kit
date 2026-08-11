"""
Tests for required-content-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "required-content-v1-check.py"


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params), "--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def make_project(tmp_path: Path, *, readme=True, git=True) -> Path:
    project = tmp_path / "project"
    project.mkdir()
    (project / "src").mkdir()
    (project / "src" / "main.py").write_text("x")
    if readme:
        (project / "README.md").write_text("# Project")
    if git:
        (project / ".git").mkdir()
    return project


PROJECT_POLICY = {"required": ["README.md"], "suggested": [".git/"]}


class TestRequired:

    def test_present_required_entry_is_ok(self, tmp_path):
        assert verdict(run_check(PROJECT_POLICY, make_project(tmp_path)))["status"] == "ok"

    def test_missing_required_entry_is_reported(self, tmp_path):
        project = make_project(tmp_path, readme=False)
        result = verdict(run_check(PROJECT_POLICY, project))
        assert result["status"] == "violation"
        assert "missing required: README.md" in result["message"]

    def test_glob_satisfies_a_requirement(self, tmp_path):
        project = make_project(tmp_path, readme=False)
        (project / "README.rst").write_text("x")
        assert verdict(run_check({"required": ["README.*"]}, project))["status"] == "ok"

    def test_requirement_can_name_a_nested_path(self, tmp_path):
        project = make_project(tmp_path)
        assert verdict(run_check({"required": ["src/main.py"]}, project))["status"] == "ok"

    def test_nested_requirement_that_is_absent_is_reported(self, tmp_path):
        project = make_project(tmp_path)
        assert verdict(run_check({"required": ["src/setup.py"]}, project))["status"] == "violation"


class TestSuggested:

    def test_missing_suggestion_is_reported_separately(self, tmp_path):
        project = make_project(tmp_path, git=False)
        result = verdict(run_check(PROJECT_POLICY, project))
        assert result["status"] == "violation"
        assert "missing suggested: .git/" in result["message"]
        assert "missing required" not in result["message"]

    def test_both_tiers_appear_in_one_message(self, tmp_path):
        project = make_project(tmp_path, readme=False, git=False)
        result = verdict(run_check(PROJECT_POLICY, project))
        assert "missing required: README.md" in result["message"]
        assert "missing suggested: .git/" in result["message"]

    def test_report_suggested_false_silences_only_that_tier(self, tmp_path):
        project = make_project(tmp_path, readme=False, git=False)
        params = dict(PROJECT_POLICY, report_suggested=False)
        result = verdict(run_check(params, project))
        assert "missing required" in result["message"]
        assert "suggested" not in result["message"]


class TestForbidden:

    def test_forbidden_entry_is_reported(self, tmp_path):
        project = make_project(tmp_path)
        (project / "src" / "main.pyc").write_text("x")
        result = verdict(run_check({"forbidden": ["*.pyc"]}, project))
        assert result["status"] == "violation"
        assert "src/main.pyc" in result["message"]

    def test_bare_name_glob_matches_at_any_depth(self, tmp_path):
        """"*.pyc" catches one anywhere without needing a "**/" prefix."""
        project = make_project(tmp_path)
        deep = project / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "x.pyc").write_text("x")
        assert verdict(run_check({"forbidden": ["*.pyc"]}, project))["status"] == "violation"

    def test_absent_forbidden_entry_is_ok(self, tmp_path):
        assert verdict(run_check({"forbidden": ["*.pyc"]}, make_project(tmp_path)))["status"] == "ok"

    def test_forbidden_directory_is_reported(self, tmp_path):
        project = make_project(tmp_path)
        (project / "node_modules").mkdir()
        result = verdict(run_check({"forbidden": ["node_modules/"]}, project))
        assert "node_modules/" in result["message"]

    def test_duplicate_hits_are_reported_once(self, tmp_path):
        project = make_project(tmp_path)
        (project / "junk.pyc").write_text("x")
        result = verdict(run_check({"forbidden": ["*.pyc", "junk.*"]}, project))
        assert result["message"].count("junk.pyc") == 1


class TestTrailingSlashMeansDirectory:

    def test_a_file_does_not_satisfy_a_directory_requirement(self, tmp_path):
        """A project with a FILE called `build` where a folder belongs is
        exactly the case worth catching."""
        project = make_project(tmp_path)
        (project / "build").write_text("not a folder")
        result = verdict(run_check({"required": ["build/"]}, project))
        assert result["status"] == "violation"

    def test_a_directory_satisfies_a_directory_requirement(self, tmp_path):
        project = make_project(tmp_path)
        (project / "build").mkdir()
        assert verdict(run_check({"required": ["build/"]}, project))["status"] == "ok"

    def test_without_a_slash_either_kind_satisfies_it(self, tmp_path):
        project = make_project(tmp_path)
        (project / "build").write_text("a file")
        assert verdict(run_check({"required": ["build"]}, project))["status"] == "ok"

    def test_a_symlink_to_a_directory_does_not_satisfy_a_directory_requirement(self, tmp_path):
        project = make_project(tmp_path)
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (project / "build").symlink_to(elsewhere)
        assert verdict(run_check({"required": ["build/"]}, project))["status"] == "violation"


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({"required": ["x"]}, make_project(tmp_path), fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"required": ["x"]}, tmp_path / "nope").returncode != 0

    def test_rejects_an_attachment_that_asserts_nothing(self, tmp_path):
        result = run_check({}, make_project(tmp_path))
        assert result.returncode != 0
        assert "asserts nothing" in result.stderr

    def test_rejects_a_non_list_tier(self, tmp_path):
        assert run_check({"required": "README.md"}, make_project(tmp_path)).returncode != 0

    def test_rejects_a_tier_holding_non_strings(self, tmp_path):
        assert run_check({"required": [1, 2]}, make_project(tmp_path)).returncode != 0

    def test_rejects_malformed_params(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{nope"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0
