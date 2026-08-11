"""
test_duplicate_files_v1.py - tests for the duplicate-files-v1 rule.

Lives inside this rule's own directory, not in the project's top-level
tests/ - a rule's tests travel with it regardless of which tier it's in
(bundled, rules.own/, rules.external/), and a third-party rule author
publishing outside this repo has no access to fs-org-kit's own tests/
anyway. This file is self-contained (no imports from anywhere outside
the standard library) so it can be copied as a template.

Every run here passes --cache-dir explicitly, pointed at a temp
directory, so no test ever reads or writes the real user cache. That
flag is exactly what the runner supplies to a rule declaring
uses_cache = true; this rule never resolves a location itself.

Run from anywhere with: pytest test_duplicate_files_v1.py -v
Or, from the project root, all bundled rules' tests run via: pytest rules/
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

CHECK_SCRIPT = Path(__file__).resolve().parent / "duplicate-files-v1-check.py"


def run_check(params: dict, path=None, paths=None, fix: bool = False, *, cache_dir):
    argv = [sys.executable, str(CHECK_SCRIPT), "--params", json.dumps(params)]
    if path is not None:
        argv += ["--path", str(path)]
    for p in paths or []:
        argv += ["--paths", str(p)]
    if cache_dir is not None:
        argv += ["--cache-dir", str(cache_dir)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


@pytest.fixture
def cache(tmp_path_factory):
    """An isolated cache directory, so a test never touches the real one."""
    return tmp_path_factory.mktemp("dupcache")


def write(path: Path, content: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    return path


class TestSingleScope:

    def test_no_duplicates_is_ok(self, tmp_path, cache):
        write(tmp_path / "a.txt", "alpha")
        write(tmp_path / "b.txt", "beta")
        result = run_check({}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_identical_content_is_violation(self, tmp_path, cache):
        write(tmp_path / "a.txt", "same bytes")
        write(tmp_path / "copy.txt", "same bytes")
        payload = json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)
        assert payload["status"] == "violation"
        assert "a.txt" in payload["message"]
        assert "copy.txt" in payload["message"]

    def test_same_size_different_content_is_ok(self, tmp_path, cache):
        """Size grouping is only a prefilter - it must not be the verdict."""
        write(tmp_path / "a.txt", "aaaaa")
        write(tmp_path / "b.txt", "bbbbb")
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"

    def test_duplicate_in_subfolder_found_when_recursive(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "sub" / "b.txt", "dup")
        payload = json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)
        assert payload["status"] == "violation"
        assert "sub/b.txt" in payload["message"]

    def test_non_recursive_ignores_subfolders(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "sub" / "b.txt", "dup")
        result = run_check({"recursive": False}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_three_copies_are_one_group(self, tmp_path, cache):
        for name in ("a.txt", "b.txt", "c.txt"):
            write(tmp_path / name, "same")
        payload = json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)
        assert payload["message"].startswith("1 group(s)")


class TestFilters:

    def test_empty_files_ignored_by_default(self, tmp_path, cache):
        write(tmp_path / "a.txt", "")
        write(tmp_path / "b.txt", "")
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"

    def test_min_size_zero_includes_empty_files(self, tmp_path, cache):
        write(tmp_path / "a.txt", "")
        write(tmp_path / "b.txt", "")
        result = run_check({"min_size": 0}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_min_size_skips_small_duplicates(self, tmp_path, cache):
        write(tmp_path / "a.txt", "tiny")
        write(tmp_path / "b.txt", "tiny")
        result = run_check({"min_size": 1024}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_extensions_narrows_what_is_compared(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        result = run_check({"extensions": ["jpg"]}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_extensions_is_dot_and_case_insensitive(self, tmp_path, cache):
        write(tmp_path / "a.JPG", "dup")
        write(tmp_path / "b.jpg", "dup")
        result = run_check({"extensions": [".Jpg"]}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_exclude_glob_removes_a_file_from_comparison(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.tmp", "dup")
        result = run_check({"exclude": ["*.tmp"]}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    def test_exclude_glob_matches_relative_path(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "cache" / "b.txt", "dup")
        result = run_check({"exclude": ["cache/*"]}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "ok"

    @pytest.mark.skipif(sys.platform == "win32", reason="symlink creation needs privileges on Windows")
    def test_symlinks_are_not_duplicates(self, tmp_path, cache):
        target = write(tmp_path / "a.txt", "content")
        (tmp_path / "link.txt").symlink_to(target)
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"

    @pytest.mark.skipif(sys.platform == "win32", reason="hardlink semantics differ on Windows")
    def test_hardlinks_are_not_duplicates(self, tmp_path, cache):
        target = write(tmp_path / "a.txt", "content")
        os.link(target, tmp_path / "same.txt")
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"


class TestCrossScope:

    def test_duplicate_across_roots_is_violation(self, tmp_path, cache):
        a, b = tmp_path / "a", tmp_path / "b"
        write(a / "photo.jpg", "same")
        write(b / "photo.jpg", "same")
        payload = json.loads(run_check({}, paths=[a, b], cache_dir=cache).stdout)
        assert payload["status"] == "violation"
        assert "spanning 2+" in payload["message"]

    def test_duplicate_inside_one_root_only_is_ignored(self, tmp_path, cache):
        """The whole point of cross scope: copies that never leave one
        root are a different question, and this attachment didn't ask it."""
        a, b = tmp_path / "a", tmp_path / "b"
        write(a / "one.txt", "same")
        write(a / "two.txt", "same")
        write(b / "other.txt", "unrelated")
        assert json.loads(run_check({}, paths=[a, b], cache_dir=cache).stdout)["status"] == "ok"

    def test_same_content_flagged_by_single_but_not_cross(self, tmp_path, cache):
        """The same tree, the same files, two attachments, two answers."""
        a, b = tmp_path / "a", tmp_path / "b"
        write(a / "one.txt", "same")
        write(a / "two.txt", "same")
        b.mkdir()
        assert json.loads(run_check({}, path=a, cache_dir=cache).stdout)["status"] == "violation"
        assert json.loads(run_check({}, paths=[a, b], cache_dir=cache).stdout)["status"] == "ok"

    def test_three_roots_group_spanning_two_of_them(self, tmp_path, cache):
        a, b, c = tmp_path / "a", tmp_path / "b", tmp_path / "c"
        write(a / "x.txt", "same")
        write(c / "y.txt", "same")
        b.mkdir()
        payload = json.loads(run_check({}, paths=[a, b, c], cache_dir=cache).stdout)
        assert payload["status"] == "violation"

    def test_cross_message_shows_full_paths(self, tmp_path, cache):
        a, b = tmp_path / "a", tmp_path / "b"
        write(a / "photo.jpg", "same")
        write(b / "photo.jpg", "same")
        message = json.loads(run_check({}, paths=[a, b], cache_dir=cache).stdout)["message"]
        assert str(a / "photo.jpg") in message
        assert str(b / "photo.jpg") in message


class TestCache:

    def test_cache_file_is_created_in_the_given_directory(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({}, path=tmp_path, cache_dir=cache)
        assert (cache / "duplicate-files-v1.sqlite3").exists()

    def test_without_cache_dir_nothing_is_cached_anywhere(self, tmp_path, cache):
        """Invoked standalone, the rule must work uncached rather than
        fall back to a location of its own choosing - the core owns
        where caches live."""
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        result = run_check({}, path=tmp_path, cache_dir=None)
        assert json.loads(result.stdout)["status"] == "violation"
        assert list(cache.iterdir()) == []

    def test_second_run_reuses_cached_digests(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        first = json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)
        second = json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)
        assert first == second

    def test_cache_is_invalidated_when_content_changes(self, tmp_path, cache):
        """A cached digest must not survive its file changing - otherwise
        the second run would still report the (now stale) duplicate."""
        a = write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "violation"

        a.write_text("now different")
        os.utime(a, (1_000_000, 1_000_000))  # a deliberately different mtime
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"

    def test_size_change_alone_invalidates(self, tmp_path, cache):
        """Same mtime, different size - the size half of the check is
        what has to catch this one."""
        a = write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({}, path=tmp_path, cache_dir=cache)

        original = a.stat()
        a.write_text("dup with more bytes")
        os.utime(a, ns=(original.st_atime_ns, original.st_mtime_ns))
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "ok"

    def test_cache_disabled_still_produces_the_right_answer(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        result = run_check({"cache": False}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "violation"
        assert not (cache / "duplicate-files-v1.sqlite3").exists()

    def test_switching_algorithm_still_works(self, tmp_path, cache):
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        assert json.loads(run_check({}, path=tmp_path, cache_dir=cache).stdout)["status"] == "violation"
        result = run_check({"algorithm": "sha256"}, path=tmp_path, cache_dir=cache)
        assert json.loads(result.stdout)["status"] == "violation"

    def test_expired_entries_are_pruned(self, tmp_path, cache):
        import sqlite3
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({}, path=tmp_path, cache_dir=cache)

        db = cache / "duplicate-files-v1.sqlite3"
        conn = sqlite3.connect(db)
        conn.execute("UPDATE hashes SET seen_at = 0")  # far in the past
        conn.commit()
        conn.close()

        # A run over an unrelated empty folder still performs the sweep.
        (tmp_path / "empty").mkdir()
        run_check({"cache_ttl_days": 1}, path=tmp_path / "empty", cache_dir=cache)

        conn = sqlite3.connect(db)
        remaining = conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]
        conn.close()
        assert remaining == 0

    def test_ttl_zero_disables_the_sweep(self, tmp_path, cache):
        import sqlite3
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({}, path=tmp_path, cache_dir=cache)

        db = cache / "duplicate-files-v1.sqlite3"
        conn = sqlite3.connect(db)
        conn.execute("UPDATE hashes SET seen_at = 0")
        conn.commit()
        conn.close()

        (tmp_path / "empty").mkdir()
        run_check({"cache_ttl_days": 0}, path=tmp_path / "empty", cache_dir=cache)

        conn = sqlite3.connect(db)
        remaining = conn.execute("SELECT COUNT(*) FROM hashes").fetchone()[0]
        conn.close()
        assert remaining == 2

    def test_refreshing_a_hit_leaves_other_algorithms_alone(self, tmp_path, cache):
        """seen_at is keyed by (path, algorithm) like the primary key -
        hashing under blake2b must not keep the sha256 row alive too."""
        import sqlite3
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({"algorithm": "blake2b"}, path=tmp_path, cache_dir=cache)
        run_check({"algorithm": "sha256"}, path=tmp_path, cache_dir=cache)

        db = cache / "duplicate-files-v1.sqlite3"
        conn = sqlite3.connect(db)
        conn.execute("UPDATE hashes SET seen_at = 0")
        conn.commit()
        conn.close()

        # ttl 0 so the sweep doesn't run - this is about the refresh only.
        run_check({"algorithm": "blake2b", "cache_ttl_days": 0}, path=tmp_path, cache_dir=cache)

        conn = sqlite3.connect(db)
        refreshed = dict(conn.execute(
            "SELECT algorithm, MAX(seen_at) FROM hashes GROUP BY algorithm"))
        conn.close()
        assert refreshed["blake2b"] > 0    # hit, refreshed
        assert refreshed["sha256"] == 0    # untouched by the other algorithm's run

    def test_sweeping_reclaims_disk_space(self, tmp_path, cache):
        """A DELETE alone leaves the file the same size on disk - only
        the VACUUM afterwards actually returns the pages."""
        import sqlite3
        write(tmp_path / "a.txt", "dup")
        write(tmp_path / "b.txt", "dup")
        run_check({}, path=tmp_path, cache_dir=cache)

        db = cache / "duplicate-files-v1.sqlite3"
        conn = sqlite3.connect(db)
        conn.executemany(
            "INSERT OR REPLACE INTO hashes"
            " (path, algorithm, size, mtime_ns, digest, seen_at)"
            " VALUES (?, ?, ?, ?, ?, 0)",
            [(f"/some/long/orphaned/path/number/{i:06d}/" + "x" * 180, "blake2b", i, i, "d" * 128)
             for i in range(5000)],
        )
        conn.commit()
        conn.close()

        bloated = db.stat().st_size
        assert bloated > 512 * 1024  # the fixture actually grew the file

        (tmp_path / "empty").mkdir()
        run_check({"cache_ttl_days": 1}, path=tmp_path / "empty", cache_dir=cache)

        assert db.stat().st_size < bloated / 2


class TestArgumentHandling:

    def test_rejects_fix(self, tmp_path, cache):
        result = run_check({}, path=tmp_path, fix=True, cache_dir=cache)
        assert result.returncode != 0
        assert "no fixer" in result.stderr

    def test_rejects_both_path_and_paths(self, tmp_path, cache):
        result = run_check({}, path=tmp_path, paths=[tmp_path, tmp_path], cache_dir=cache)
        assert result.returncode != 0
        assert "not both" in result.stderr

    def test_rejects_neither_path_nor_paths(self, cache):
        result = run_check({}, cache_dir=cache)
        assert result.returncode != 0

    def test_rejects_single_value_paths(self, tmp_path, cache):
        result = run_check({}, paths=[tmp_path], cache_dir=cache)
        assert result.returncode != 0
        assert "2 or more" in result.stderr

    def test_rejects_nonexistent_path(self, tmp_path, cache):
        result = run_check({}, path=tmp_path / "nope", cache_dir=cache)
        assert result.returncode != 0
        assert "not a directory" in result.stderr

    def test_rejects_unknown_algorithm(self, tmp_path, cache):
        result = run_check({"algorithm": "not-a-hash"}, path=tmp_path, cache_dir=cache)
        assert result.returncode != 0
        assert "unknown hash algorithm" in result.stderr

    def test_rejects_negative_min_size(self, tmp_path, cache):
        result = run_check({"min_size": -1}, path=tmp_path, cache_dir=cache)
        assert result.returncode != 0

    def test_rejects_non_list_exclude(self, tmp_path, cache):
        result = run_check({"exclude": "*.tmp"}, path=tmp_path, cache_dir=cache)
        assert result.returncode != 0
