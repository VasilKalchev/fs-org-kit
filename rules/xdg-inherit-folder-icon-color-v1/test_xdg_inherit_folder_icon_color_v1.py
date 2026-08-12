"""
Tests for xdg-inherit-folder-icon-color-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "xdg-inherit-folder-icon-color-v1-check.py"
FIX_SCRIPT = RULE_DIR / "xdg-inherit-folder-icon-color-v1-fix.py"


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
    for line in (folder / ".directory").read_text().splitlines():
        if line.startswith("Icon="):
            return line.split("=", 1)[1]
    return ""


def yellow_parent(tmp_path: Path) -> Path:
    return set_icon(tmp_path / "area", "folder-yellow-public")


class TestChecker:

    def test_matching_child_is_ok(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-yellow-documents")
        assert verdict(run_check({}, parent))["status"] == "ok"

    def test_child_with_a_different_color_is_reported(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-red-documents")
        result = verdict(run_check({}, parent))
        assert result["status"] == "violation"
        assert "folder-red-documents -> folder-yellow-documents" in result["message"]

    def test_child_with_no_icon_is_reported(self, tmp_path):
        parent = yellow_parent(tmp_path)
        (parent / "child").mkdir()
        result = verdict(run_check({}, parent))
        assert "no icon -> folder-yellow" in result["message"]

    def test_skip_unset_leaves_undecorated_folders_alone(self, tmp_path):
        parent = yellow_parent(tmp_path)
        (parent / "child").mkdir()
        assert verdict(run_check({"skip_unset": True}, parent))["status"] == "ok"

    def test_explicit_color_param_overrides_the_parents_own(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-green-documents")
        assert verdict(run_check({"color": "green"}, parent))["status"] == "ok"

    def test_parent_with_no_color_is_reported_not_silently_passed(self, tmp_path):
        """An attachment asking children to match a color the parent
        doesn't have is a gap in the standard, not a clean result."""
        parent = tmp_path / "area"
        parent.mkdir()
        (parent / "child").mkdir()
        result = verdict(run_check({}, parent))
        assert result["status"] == "violation"
        assert "no color to inherit" in result["message"]

    def test_not_recursive_by_default(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-yellow")
        set_icon(parent / "child" / "grandchild", "folder-red")
        assert verdict(run_check({}, parent))["status"] == "ok"

    def test_recursive_reaches_grandchildren(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-yellow")
        set_icon(parent / "child" / "grandchild", "folder-red")
        result = verdict(run_check({"recursive": True}, parent))
        assert "child/grandchild" in result["message"]

    def test_excluded_folders_are_skipped(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-red")
        assert verdict(run_check({"exclude": ["child"]}, parent))["status"] == "ok"

    def test_symlinked_folders_are_not_followed(self, tmp_path):
        """Writing a .directory into a link's target would change a folder
        outside the tree being governed."""
        parent = yellow_parent(tmp_path)
        elsewhere = set_icon(tmp_path / "elsewhere", "folder-red")
        (parent / "link").symlink_to(elsewhere)
        assert verdict(run_check({}, parent))["status"] == "ok"


class TestVariantIsKept:

    def test_variant_survives_a_recolor(self, tmp_path):
        """A child keeps saying what it is while taking on its parent's
        color - that split is the whole point."""
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red-public")
        verdict(run_fix({}, parent))
        assert icon_of(child) == "folder-yellow-public"

    def test_multi_segment_variant_survives(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red-open-documents")
        verdict(run_fix({}, parent))
        assert icon_of(child) == "folder-yellow-open-documents"

    def test_a_child_with_no_variant_gets_a_bare_colored_icon(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red")
        verdict(run_fix({}, parent))
        assert icon_of(child) == "folder-yellow"

    def test_an_uncolored_icon_keeps_its_variant(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-git")
        verdict(run_fix({}, parent))
        assert icon_of(child) == "folder-yellow-git"


class TestOnDifferentColor:

    def test_change_recolors(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red-public")
        assert verdict(run_fix({"on_different_color": "change"}, parent))["status"] == "fixed"
        assert icon_of(child) == "folder-yellow-public"

    def test_warn_reports_but_never_writes(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red-public")
        result = verdict(run_fix({"on_different_color": "warn"}, parent))
        assert result["status"] == "violation"
        assert icon_of(child) == "folder-red-public"

    def test_ignore_reports_nothing(self, tmp_path):
        parent = yellow_parent(tmp_path)
        set_icon(parent / "child", "folder-red-public")
        assert verdict(run_check({"on_different_color": "ignore"}, parent))["status"] == "ok"

    def test_warn_still_sets_unset_children(self, tmp_path):
        """"warn" is about not overriding a deliberate choice, not about
        declining to act at all."""
        parent = yellow_parent(tmp_path)
        bare = parent / "bare"
        bare.mkdir()
        set_icon(parent / "colored", "folder-red")
        result = verdict(run_fix({"on_different_color": "warn"}, parent))
        assert result["status"] == "violation"
        assert icon_of(bare) == "folder-yellow"


class TestCustomIcons:

    def test_a_custom_icon_is_reported_but_never_rewritten(self, tmp_path):
        """Recoloring it would compose a name from a variant that was never
        a variant, throwing away whatever was deliberately set."""
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "/home/me/custom-icon.png")
        result = verdict(run_fix({}, parent))
        assert result["status"] == "violation"
        assert icon_of(child) == "/home/me/custom-icon.png"
        assert "custom icon" in result["message"]

    def test_a_custom_named_icon_is_also_left_alone(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "applications-graphics")
        verdict(run_fix({}, parent))
        assert icon_of(child) == "applications-graphics"


class TestDirectoryFileHandling:

    def test_other_keys_are_preserved(self, tmp_path):
        """A .directory often carries sort order, view mode and a custom
        name that have nothing to do with icons."""
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red", extra="Name=My Folder\nSortOrder=2\n")
        verdict(run_fix({}, parent))
        text = (child / ".directory").read_text()
        assert "Name=My Folder" in text
        assert "SortOrder=2" in text
        assert "Icon=folder-yellow" in text

    def test_other_groups_are_preserved(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = parent / "child"
        child.mkdir()
        (child / ".directory").write_text(
            "[Desktop Entry]\nIcon=folder-red\n\n[Settings]\nShowPreview=true\n"
        )
        verdict(run_fix({}, parent))
        text = (child / ".directory").read_text()
        assert "[Settings]" in text
        assert "ShowPreview=true" in text
        assert "Icon=folder-yellow" in text

    def test_a_directory_file_is_created_when_absent(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = parent / "child"
        child.mkdir()
        verdict(run_fix({}, parent))
        assert (child / ".directory").read_text().startswith("[Desktop Entry]")
        assert icon_of(child) == "folder-yellow"

    def test_icon_is_added_to_an_existing_group_without_one(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = parent / "child"
        child.mkdir()
        (child / ".directory").write_text("[Desktop Entry]\nName=Existing\n")
        verdict(run_fix({}, parent))
        text = (child / ".directory").read_text()
        assert "Name=Existing" in text
        assert icon_of(child) == "folder-yellow"

    def test_nothing_to_do_leaves_files_untouched(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-yellow")
        before = (child / ".directory").read_text()
        assert verdict(run_fix({}, parent))["status"] == "ok"
        assert (child / ".directory").read_text() == before


class TestArgumentHandling:

    def test_checker_rejects_fix(self, tmp_path):
        assert run_check({}, yellow_parent(tmp_path), fix=True).returncode != 0

    def test_fixer_refuses_to_run_without_fix(self, tmp_path):
        parent = yellow_parent(tmp_path)
        child = set_icon(parent / "child", "folder-red")
        assert run_fix({}, parent, fix=False).returncode != 0
        assert icon_of(child) == "folder-red"

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({}, tmp_path / "nope").returncode != 0

    def test_rejects_a_color_not_in_colors(self, tmp_path):
        result = run_check({"color": "chartreuse"}, yellow_parent(tmp_path))
        assert result.returncode != 0
        assert "chartreuse" in result.stderr

    def test_rejects_unknown_on_different_color(self, tmp_path):
        assert run_check({"on_different_color": "maybe"}, yellow_parent(tmp_path)).returncode != 0

    def test_rejects_empty_colors(self, tmp_path):
        assert run_check({"colors": []}, yellow_parent(tmp_path)).returncode != 0

    def test_rejects_empty_icon_prefix(self, tmp_path):
        assert run_check({"icon_prefix": ""}, yellow_parent(tmp_path)).returncode != 0

    def test_custom_prefix_and_colors_work(self, tmp_path):
        """The rule only needs to know which token IS the color, so another
        icon theme's vocabulary can be described per attachment."""
        parent = set_icon(tmp_path / "area", "dir-teal-notes")
        child = set_icon(parent / "child", "dir-coral-notes")
        params = {"icon_prefix": "dir", "colors": ["teal", "coral"]}
        assert verdict(run_check(params, parent))["status"] == "violation"
        verdict(run_fix(params, parent))
        assert icon_of(child) == "dir-teal-notes"
