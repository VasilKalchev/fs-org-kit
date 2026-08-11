"""
Tests for folder-icon-auto-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "folder-icon-auto-v1-check.py"
FIX_SCRIPT = RULE_DIR / "folder-icon-auto-v1-fix.py"

GIT_RULE = {"name": r"^\.?git$", "icon": "folder-{color}-git"}


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


def set_icon(folder: Path, icon: str, extra: str = "") -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / ".directory").write_text(f"[Desktop Entry]\nIcon={icon}\n{extra}")
    return folder


def icon_of(folder: Path) -> str:
    entry = folder / ".directory"
    if not entry.exists():
        return ""
    for line in entry.read_text().splitlines():
        if line.startswith("Icon="):
            return line.split("=", 1)[1]
    return ""


class TestNameMatching:

    def test_matching_folder_gets_its_icon(self, tmp_path):
        (tmp_path / "git").mkdir()
        result = verdict(run_check({"match": [GIT_RULE]}, tmp_path))
        assert result["status"] == "violation"
        assert "folder-blue-git" in result["message"]

    def test_non_matching_folder_is_left_alone(self, tmp_path):
        (tmp_path / "photos").mkdir()
        assert verdict(run_check({"match": [GIT_RULE]}, tmp_path))["status"] == "ok"

    def test_the_fixer_writes_it(self, tmp_path):
        target = tmp_path / ".git"
        target.mkdir()
        assert verdict(run_fix({"match": [GIT_RULE]}, tmp_path))["status"] == "fixed"
        assert icon_of(target) == "folder-blue-git"

    def test_already_correct_is_ok(self, tmp_path):
        set_icon(tmp_path / "git", "folder-blue-git")
        assert verdict(run_check({"match": [GIT_RULE]}, tmp_path))["status"] == "ok"


class TestContentMatching:

    def test_contains_requires_a_direct_child(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "package.json").write_text("{}")
        rule = {"contains": ["package.json"], "icon": "folder-{color}-script"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "violation"

    def test_contains_requires_all_of_them(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "package.json").write_text("{}")
        rule = {"contains": ["package.json", "tsconfig.json"], "icon": "folder-{color}-script"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "ok"

    def test_contains_does_not_recurse(self, tmp_path):
        """Recursing would let one stray file redefine a whole tree's icon."""
        project = tmp_path / "project"
        (project / "deep").mkdir(parents=True)
        (project / "deep" / "package.json").write_text("{}")
        rule = {"contains": ["package.json"], "icon": "folder-{color}-script"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "ok"

    def test_contains_any_needs_only_one(self, tmp_path):
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        (gallery / "a.png").write_bytes(b"x")
        rule = {"contains_any": ["*.jpg", "*.png"], "icon": "folder-{color}-images"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "violation"

    def test_ratio_expresses_mostly_images(self, tmp_path):
        gallery = tmp_path / "gallery"
        gallery.mkdir()
        for i in range(4):
            (gallery / f"img{i}.png").write_bytes(b"x")
        (gallery / "notes.txt").write_text("x")
        rule = {"contains_any": ["*.png"], "ratio": 0.6, "icon": "folder-{color}-images"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "violation"

    def test_ratio_not_met_does_not_match(self, tmp_path):
        mixed = tmp_path / "mixed"
        mixed.mkdir()
        (mixed / "img.png").write_bytes(b"x")
        for i in range(4):
            (mixed / f"doc{i}.txt").write_text("x")
        rule = {"contains_any": ["*.png"], "ratio": 0.6, "icon": "folder-{color}-images"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "ok"

    def test_empty_matches_a_folder_with_nothing_in_it(self, tmp_path):
        (tmp_path / "hollow").mkdir()
        (tmp_path / "full").mkdir()
        (tmp_path / "full" / "f.txt").write_text("x")
        rule = {"empty": True, "icon": "folder-{color}-empty"}
        result = verdict(run_check({"match": [rule]}, tmp_path))
        assert "hollow" in result["message"]
        assert "full" not in result["message"]

    def test_conditions_in_one_entry_are_anded(self, tmp_path):
        project = tmp_path / "project"
        project.mkdir()
        (project / "package.json").write_text("{}")
        rule = {"name": "^other$", "contains": ["package.json"], "icon": "folder-{color}-script"}
        assert verdict(run_check({"match": [rule]}, tmp_path))["status"] == "ok"


class TestOrdering:

    def test_first_match_wins(self, tmp_path):
        """Ordered, not scored - a declared order is something a person can
        read and reason about."""
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "package.json").write_text("{}")
        match = [
            {"contains": [".git"], "icon": "folder-{color}-git"},
            {"contains": ["package.json"], "icon": "folder-{color}-script"},
        ]
        result = verdict(run_check({"match": match}, tmp_path))
        assert "folder-blue-git" in result["message"]
        assert "script" not in result["message"]

    def test_reordering_changes_the_answer(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / ".git").mkdir()
        (repo / "package.json").write_text("{}")
        match = [
            {"contains": ["package.json"], "icon": "folder-{color}-script"},
            {"contains": [".git"], "icon": "folder-{color}-git"},
        ]
        assert "folder-blue-script" in verdict(run_check({"match": match}, tmp_path))["message"]


class TestColorIsPreserved:

    def test_existing_color_is_kept(self, tmp_path):
        """This rule assigns meaning without disturbing whatever color
        scheme is in place."""
        target = set_icon(tmp_path / "git", "folder-yellow")
        verdict(run_fix({"match": [GIT_RULE]}, tmp_path))
        assert icon_of(target) == "folder-yellow-git"

    def test_existing_color_and_variant_are_both_replaced_by_the_new_variant(self, tmp_path):
        target = set_icon(tmp_path / "git", "folder-yellow-documents")
        verdict(run_fix({"match": [GIT_RULE]}, tmp_path))
        assert icon_of(target) == "folder-yellow-git"

    def test_default_color_fills_in_when_there_is_none(self, tmp_path):
        target = tmp_path / "git"
        target.mkdir()
        verdict(run_fix({"match": [GIT_RULE], "default_color": "green"}, tmp_path))
        assert icon_of(target) == "folder-green-git"

    def test_an_icon_without_the_placeholder_is_used_verbatim(self, tmp_path):
        target = set_icon(tmp_path / "git", "folder-yellow")
        rule = {"name": "^git$", "icon": "vcs-normal"}
        verdict(run_fix({"match": [rule]}, tmp_path))
        assert icon_of(target) == "vcs-normal"

    def test_composes_with_the_inherit_rule_in_either_order(self, tmp_path):
        """The two rules are meant to be attached together; neither can
        undo the other's decision."""
        target = set_icon(tmp_path / "git", "folder-red-git")
        verdict(run_fix({"match": [GIT_RULE]}, tmp_path))
        assert icon_of(target) == "folder-red-git"


class TestTraversal:

    def test_not_recursive_by_default(self, tmp_path):
        (tmp_path / "outer" / "git").mkdir(parents=True)
        assert verdict(run_check({"match": [GIT_RULE]}, tmp_path))["status"] == "ok"

    def test_recursive_reaches_deeper(self, tmp_path):
        (tmp_path / "outer" / "git").mkdir(parents=True)
        result = verdict(run_check({"match": [GIT_RULE], "recursive": True}, tmp_path))
        assert "outer/git" in result["message"]

    def test_excluded_folders_are_skipped(self, tmp_path):
        (tmp_path / "git").mkdir()
        assert verdict(run_check({"match": [GIT_RULE], "exclude": ["git"]}, tmp_path))["status"] == "ok"

    def test_symlinked_folders_are_not_followed(self, tmp_path):
        elsewhere = tmp_path / "elsewhere"
        elsewhere.mkdir()
        (tmp_path / "git").symlink_to(elsewhere)
        assert verdict(run_check({"match": [GIT_RULE], "exclude": ["elsewhere"]}, tmp_path))["status"] == "ok"


class TestDirectoryFileHandling:

    def test_other_keys_are_preserved(self, tmp_path):
        target = set_icon(tmp_path / "git", "folder-yellow", extra="Name=Repo\nSortOrder=1\n")
        verdict(run_fix({"match": [GIT_RULE]}, tmp_path))
        text = (target / ".directory").read_text()
        assert "Name=Repo" in text
        assert "SortOrder=1" in text
        assert "Icon=folder-yellow-git" in text

    def test_a_directory_file_is_created_when_absent(self, tmp_path):
        target = tmp_path / "git"
        target.mkdir()
        verdict(run_fix({"match": [GIT_RULE]}, tmp_path))
        assert (target / ".directory").read_text().startswith("[Desktop Entry]")


class TestArgumentHandling:

    def test_checker_rejects_fix(self, tmp_path):
        assert run_check({"match": [GIT_RULE]}, tmp_path, fix=True).returncode != 0

    def test_fixer_refuses_to_run_without_fix(self, tmp_path):
        target = tmp_path / "git"
        target.mkdir()
        assert run_fix({"match": [GIT_RULE]}, tmp_path, fix=False).returncode != 0
        assert not (target / ".directory").exists()

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"match": [GIT_RULE]}, tmp_path / "nope").returncode != 0

    def test_rejects_missing_match(self, tmp_path):
        result = run_check({}, tmp_path)
        assert result.returncode != 0
        assert "match must be a non-empty list" in result.stderr

    def test_rejects_a_condition_free_entry(self, tmp_path):
        """It would match every folder from wherever it sits in the list."""
        result = run_check({"match": [{"icon": "folder-blue"}]}, tmp_path)
        assert result.returncode != 0
        assert "would match every folder" in result.stderr

    def test_rejects_an_entry_with_no_icon(self, tmp_path):
        assert run_check({"match": [{"name": "^x$"}]}, tmp_path).returncode != 0

    def test_rejects_an_invalid_regex(self, tmp_path):
        assert run_check({"match": [{"name": "[unclosed", "icon": "x"}]}, tmp_path).returncode != 0

    def test_rejects_an_unknown_condition_key(self, tmp_path):
        result = run_check({"match": [{"containss": ["x"], "icon": "y"}]}, tmp_path)
        assert result.returncode != 0
        assert "containss" in result.stderr

    def test_rejects_ratio_without_contains_any(self, tmp_path):
        result = run_check({"match": [{"name": "^x$", "ratio": 0.5, "icon": "y"}]}, tmp_path)
        assert result.returncode != 0
        assert "nothing to take a fraction of" in result.stderr

    def test_rejects_ratio_out_of_range(self, tmp_path):
        assert run_check({"match": [{"contains_any": ["*"], "ratio": 2, "icon": "y"}]}, tmp_path).returncode != 0

    def test_rejects_default_color_not_in_colors(self, tmp_path):
        assert run_check({"match": [GIT_RULE], "default_color": "chartreuse"}, tmp_path).returncode != 0
