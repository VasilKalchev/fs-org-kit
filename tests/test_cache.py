"""
test_cache.py - tests for fs_org_kit.cache, the core's ownership of
where rules keep state between runs.

Every test sets FS_ORG_KIT_CACHE_DIR (via monkeypatch) so nothing here
ever touches the real user cache directory.
"""

import sys

import pytest

from fs_org_kit.cache import (
    ENV_OVERRIDE,
    cache_root,
    clear,
    ensure_rule_cache_dir,
    list_caches,
    main,
    rule_cache_dir,
)


@pytest.fixture
def root(tmp_path, monkeypatch):
    monkeypatch.setenv(ENV_OVERRIDE, str(tmp_path / "cacheroot"))
    return tmp_path / "cacheroot"


class TestLocation:

    def test_env_override_wins(self, root):
        assert cache_root() == root

    def test_env_override_expands_user(self, monkeypatch):
        monkeypatch.setenv(ENV_OVERRIDE, "~/somewhere")
        assert "~" not in str(cache_root())

    def test_falls_back_to_xdg_cache_home(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path))
        assert cache_root() == tmp_path / "fs-org-kit"

    def test_falls_back_to_dot_cache_without_xdg(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        monkeypatch.delenv("XDG_CACHE_HOME", raising=False)
        monkeypatch.setattr(sys, "platform", "linux")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert cache_root() == tmp_path / ".cache" / "fs-org-kit"

    def test_macos_uses_library_caches(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        monkeypatch.setattr(sys, "platform", "darwin")
        monkeypatch.setattr("pathlib.Path.home", lambda: tmp_path)
        assert cache_root() == tmp_path / "Library" / "Caches" / "fs-org-kit"

    def test_windows_uses_localappdata(self, tmp_path, monkeypatch):
        monkeypatch.delenv(ENV_OVERRIDE, raising=False)
        monkeypatch.setattr(sys, "platform", "win32")
        monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
        assert cache_root() == tmp_path / "fs-org-kit"

    def test_each_rule_gets_its_own_subdirectory(self, root):
        a = rule_cache_dir("duplicate-files-v1")
        b = rule_cache_dir("other-rule-v1")
        assert a != b
        assert a.parent == b.parent == root / "rules"

    def test_rule_cache_dir_does_not_create_anything(self, root):
        rule_cache_dir("duplicate-files-v1")
        assert not root.exists()


class TestEnsure:

    def test_creates_the_directory(self, root):
        created = ensure_rule_cache_dir("duplicate-files-v1")
        assert created is not None
        assert created.is_dir()
        assert created == root / "rules" / "duplicate-files-v1"

    def test_is_idempotent(self, root):
        first = ensure_rule_cache_dir("duplicate-files-v1")
        second = ensure_rule_cache_dir("duplicate-files-v1")
        assert first == second

    def test_returns_none_when_it_cannot_create(self, tmp_path, monkeypatch):
        """An unwritable location means "run without caching", never an
        error - the caller degrades to slower, not to broken."""
        blocker = tmp_path / "blocker"
        blocker.write_text("i am a file, not a directory")
        monkeypatch.setenv(ENV_OVERRIDE, str(blocker))
        assert ensure_rule_cache_dir("duplicate-files-v1") is None


class TestListAndClear:

    def test_listing_an_absent_root_is_empty(self, root):
        assert list_caches() == []

    def test_lists_rules_with_sizes(self, root):
        d = ensure_rule_cache_dir("duplicate-files-v1")
        (d / "data.sqlite3").write_bytes(b"x" * 500)
        ensure_rule_cache_dir("other-rule-v1")

        found = list_caches()
        assert [name for name, _, _ in found] == ["duplicate-files-v1", "other-rule-v1"]
        assert dict((n, s) for n, _, s in found)["duplicate-files-v1"] == 500

    def test_size_counts_nested_files(self, root):
        d = ensure_rule_cache_dir("duplicate-files-v1")
        (d / "sub").mkdir()
        (d / "sub" / "a").write_bytes(b"x" * 100)
        (d / "b").write_bytes(b"x" * 100)
        assert list_caches()[0][2] == 200

    def test_clear_one_rule_leaves_the_others(self, root):
        ensure_rule_cache_dir("duplicate-files-v1")
        ensure_rule_cache_dir("other-rule-v1")

        assert clear("duplicate-files-v1") == ["duplicate-files-v1"]
        assert [name for name, _, _ in list_caches()] == ["other-rule-v1"]

    def test_clear_everything(self, root):
        ensure_rule_cache_dir("duplicate-files-v1")
        ensure_rule_cache_dir("other-rule-v1")

        removed = clear()
        assert sorted(removed) == ["duplicate-files-v1", "other-rule-v1"]
        assert list_caches() == []

    def test_clearing_something_absent_is_not_an_error(self, root):
        assert clear("never-ran-v1") == []
        assert clear() == []


class TestCLI:

    def test_path_prints_the_root(self, root, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fs-org-cache", "--path"])
        assert main() == 0
        assert capsys.readouterr().out.strip() == str(root)

    def test_list_reports_nothing_cached(self, root, capsys, monkeypatch):
        monkeypatch.setattr(sys, "argv", ["fs-org-cache", "--list"])
        assert main() == 0
        assert "(nothing cached)" in capsys.readouterr().out

    def test_list_shows_each_rule(self, root, capsys, monkeypatch):
        d = ensure_rule_cache_dir("duplicate-files-v1")
        (d / "data").write_bytes(b"x" * 2048)
        monkeypatch.setattr(sys, "argv", ["fs-org-cache", "--list"])
        assert main() == 0
        out = capsys.readouterr().out
        assert "duplicate-files-v1" in out
        assert "2.0 KB" in out

    def test_clear_named_rule_via_cli(self, root, capsys, monkeypatch):
        ensure_rule_cache_dir("duplicate-files-v1")
        monkeypatch.setattr(sys, "argv", ["fs-org-cache", "--clear", "duplicate-files-v1"])
        assert main() == 0
        assert "cleared duplicate-files-v1" in capsys.readouterr().out
        assert list_caches() == []

    def test_clear_all_via_cli(self, root, capsys, monkeypatch):
        ensure_rule_cache_dir("duplicate-files-v1")
        ensure_rule_cache_dir("other-rule-v1")
        monkeypatch.setattr(sys, "argv", ["fs-org-cache", "--clear"])
        assert main() == 0
        assert list_caches() == []
