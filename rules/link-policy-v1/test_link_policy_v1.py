"""
Tests for link-policy-v1.

Scripts are invoked via subprocess exactly as the runner does - never by
importing their internals. That subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "link-policy-v1-check.py"


def run_check(params: dict, path, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
    argv += ["--path", str(path)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def make_index_folder(tmp_path: Path) -> Path:
    """The arrangement the rule exists for: subfolders, links, no files."""
    (tmp_path / "section").mkdir()
    (tmp_path / "elsewhere.txt").write_text("content")
    (tmp_path / "link-to-content").symlink_to(tmp_path / "elsewhere.txt")
    return tmp_path


class TestForbidden:

    def test_forbidden_files_reported(self, tmp_path):
        (tmp_path / "stored.txt").write_text("x")
        result = verdict(run_check({"files": "forbidden"}, tmp_path))
        assert result["status"] == "violation"
        assert "stored.txt" in result["message"]

    def test_forbidden_files_satisfied_by_a_folder_of_links(self, tmp_path):
        make_index_folder(tmp_path)
        result = verdict(run_check({"files": "forbidden", "exclude": ["elsewhere.txt"]}, tmp_path))
        assert result["status"] == "ok"

    def test_forbidden_folders_reported(self, tmp_path):
        (tmp_path / "sub").mkdir()
        assert verdict(run_check({"folders": "forbidden"}, tmp_path))["status"] == "violation"

    def test_forbidden_links_reported(self, tmp_path):
        (tmp_path / "target.txt").write_text("x")
        (tmp_path / "link").symlink_to(tmp_path / "target.txt")
        result = verdict(run_check({"links": "forbidden"}, tmp_path))
        assert result["status"] == "violation"
        assert "link" in result["message"]

    def test_empty_folder_satisfies_every_forbidden_policy(self, tmp_path):
        params = {"files": "forbidden", "folders": "forbidden", "links": "forbidden"}
        assert verdict(run_check(params, tmp_path))["status"] == "ok"


class TestRequired:

    def test_required_links_missing_is_reported(self, tmp_path):
        (tmp_path / "sub").mkdir()
        result = verdict(run_check({"links": "required"}, tmp_path))
        assert result["status"] == "violation"
        assert "required" in result["message"]

    def test_required_links_present_is_ok(self, tmp_path):
        make_index_folder(tmp_path)
        assert verdict(run_check({"links": "required"}, tmp_path))["status"] == "ok"

    def test_required_is_satisfied_anywhere_in_scope(self, tmp_path):
        """"required" asks whether the scope contains one at all - a
        per-folder reading would fail on every leaf directory."""
        (tmp_path / "target.txt").write_text("x")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "link").symlink_to(tmp_path / "target.txt")
        assert verdict(run_check({"links": "required", "recursive": True}, tmp_path))["status"] == "ok"

    def test_required_not_satisfied_out_of_scope(self, tmp_path):
        (tmp_path / "target.txt").write_text("x")
        deep = tmp_path / "a" / "b"
        deep.mkdir(parents=True)
        (deep / "link").symlink_to(tmp_path / "target.txt")
        assert verdict(run_check({"links": "required", "recursive": False}, tmp_path))["status"] == "violation"


class TestTheWholeArrangement:

    def test_index_folder_passes_all_three_policies(self, tmp_path):
        content = tmp_path / "content"
        content.mkdir()
        (content / "real.txt").write_text("x")
        index = tmp_path / "index"
        index.mkdir()
        (index / "section").mkdir()
        (index / "shortcut").symlink_to(content / "real.txt")

        params = {"files": "forbidden", "folders": "allowed", "links": "required", "recursive": True}
        assert verdict(run_check(params, index))["status"] == "ok"

    def test_one_real_file_breaks_it(self, tmp_path):
        index = tmp_path / "index"
        (index / "section").mkdir(parents=True)
        (index / "section" / "snuck-in.txt").write_text("x")
        (index / "link").symlink_to(tmp_path)

        params = {"files": "forbidden", "links": "required", "recursive": True}
        result = verdict(run_check(params, index))
        assert result["status"] == "violation"
        assert "snuck-in.txt" in result["message"]


class TestClassification:

    def test_desktop_entry_counts_as_a_link_not_a_file(self, tmp_path):
        """Otherwise "files = forbidden, links = allowed" would forbid the
        links too, and the arrangement would be unsayable."""
        (tmp_path / "launcher.desktop").write_text("[Desktop Entry]\nType=Link\nURL=file:///tmp\n")
        assert verdict(run_check({"files": "forbidden"}, tmp_path))["status"] == "ok"
        assert verdict(run_check({"links": "forbidden"}, tmp_path))["status"] == "violation"

    def test_narrowing_link_kinds_makes_a_desktop_entry_a_file_again(self, tmp_path):
        """The right answer for a folder that stores launchers as content."""
        (tmp_path / "launcher.desktop").write_text("[Desktop Entry]\nType=Link\nURL=file:///tmp\n")
        params = {"files": "forbidden", "link_kinds": ["symlink"]}
        assert verdict(run_check(params, tmp_path))["status"] == "violation"

    def test_symlink_to_a_directory_is_a_link_not_a_folder(self, tmp_path):
        (tmp_path / "real").mkdir()
        (tmp_path / "link").symlink_to(tmp_path / "real")
        result = verdict(run_check({"folders": "forbidden", "exclude": ["real"]}, tmp_path))
        assert result["status"] == "ok"

    def test_windows_and_mac_link_files_count_as_links(self, tmp_path):
        for name in ("a.lnk", "b.url", "c.webloc"):
            (tmp_path / name).write_bytes(b"whatever")
        assert verdict(run_check({"files": "forbidden"}, tmp_path))["status"] == "ok"
        result = verdict(run_check({"links": "forbidden"}, tmp_path))
        assert result["status"] == "violation"

    def test_a_broken_link_still_counts_as_a_link(self, tmp_path):
        """Whether a link works is link-integrity-v1's question."""
        (tmp_path / "dangling").symlink_to(tmp_path / "gone")
        assert verdict(run_check({"links": "required"}, tmp_path))["status"] == "ok"


class TestTraversal:

    def test_not_recursive_by_default(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "buried.txt").write_text("x")
        assert verdict(run_check({"files": "forbidden"}, tmp_path))["status"] == "ok"

    def test_recursive_finds_buried_entries(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "buried.txt").write_text("x")
        result = verdict(run_check({"files": "forbidden", "recursive": True}, tmp_path))
        assert result["status"] == "violation"
        assert "sub/buried.txt" in result["message"]

    def test_excluded_entries_are_not_judged(self, tmp_path):
        (tmp_path / "notes.md").write_text("x")
        assert verdict(run_check({"files": "forbidden", "exclude": ["*.md"]}, tmp_path))["status"] == "ok"

    def test_a_link_to_an_ancestor_does_not_loop(self, tmp_path):
        sub = tmp_path / "sub"
        sub.mkdir()
        (sub / "up").symlink_to(tmp_path)
        result = run_check({"links": "forbidden", "recursive": True}, tmp_path)
        assert result.returncode == 0
        assert json.loads(result.stdout)["status"] == "violation"


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path):
        assert run_check({"files": "forbidden"}, tmp_path, fix=True).returncode != 0

    def test_nonexistent_path_is_broken(self, tmp_path):
        assert run_check({"files": "forbidden"}, tmp_path / "nope").returncode != 0

    def test_rejects_an_attachment_that_constrains_nothing(self, tmp_path):
        result = run_check({}, tmp_path)
        assert result.returncode != 0
        assert "constrains nothing" in result.stderr

    def test_rejects_an_unknown_policy(self, tmp_path):
        assert run_check({"files": "discouraged"}, tmp_path).returncode != 0

    def test_rejects_an_unknown_link_kind(self, tmp_path):
        assert run_check({"files": "forbidden", "link_kinds": ["hardlink"]}, tmp_path).returncode != 0

    def test_rejects_a_link_policy_with_no_link_kinds(self, tmp_path):
        result = run_check({"links": "forbidden", "link_kinds": []}, tmp_path)
        assert result.returncode != 0
        assert "nothing would ever count" in result.stderr

    def test_rejects_non_list_exclude(self, tmp_path):
        assert run_check({"files": "forbidden", "exclude": "*.md"}, tmp_path).returncode != 0
