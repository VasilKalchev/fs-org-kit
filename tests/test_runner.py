"""
tests/test_runner.py - unit tests for fs_org_kit.runner

Run with: python -m pytest tests/test_runner.py -v
"""

import os
import tempfile
import time
from pathlib import Path

import pytest

from fs_org_kit.discovery import discover_rules
from fs_org_kit.inherit import resolve_entries
from fs_org_kit.runner import (
    Invocation,
    _resolve_active_targets,
    collect_invocations,
    invoke_script,
    main,
    run_invocation,
)


@pytest.fixture
def catalog():
    """Real discovered catalog from the project's own bundled rules/."""
    with tempfile.TemporaryDirectory() as td:
        cat, issues = discover_rules(Path(td))
        assert issues == []
        return cat


class TestResolveActiveTargets:

    def test_existing_path_is_active(self, tmp_path):
        real_dir = tmp_path / "exists"
        real_dir.mkdir()
        resolved, _ = resolve_entries(
            {"exists/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]}}, {}, "paths"
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert [k for k, _ in active] == ["exists/"]
        assert missing == []

    def test_missing_with_allow_missing_is_silently_skipped(self, tmp_path):
        resolved, _ = resolve_entries(
            {"gone/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"], "allow_missing": True}},
            {}, "paths",
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert active == []
        assert missing == []  # not reported - that's the whole point of allow_missing

    def test_missing_without_allow_missing_is_reported(self, tmp_path):
        resolved, _ = resolve_entries(
            {"gone/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]}}, {}, "paths"
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert active == []
        assert missing == ["gone/"]

    def test_pattern_key_expands_to_every_real_match(self, tmp_path):
        (tmp_path / "clients" / "acme").mkdir(parents=True)
        (tmp_path / "clients" / "globex").mkdir(parents=True)
        resolved, _ = resolve_entries(
            {"clients/*/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]}}, {}, "paths"
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert sorted(p.name for _, p in active) == ["acme", "globex"]
        assert all(k == "clients/*/" for k, _ in active)
        assert missing == []

    def test_pattern_key_zero_matches_with_allow_missing_is_silently_skipped(self, tmp_path):
        resolved, _ = resolve_entries(
            {"clients/*/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"], "allow_missing": True}},
            {}, "paths",
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert active == []
        assert missing == []

    def test_pattern_key_zero_matches_without_allow_missing_is_reported(self, tmp_path):
        resolved, _ = resolve_entries(
            {"clients/*/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]}}, {}, "paths"
        )
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert active == []
        assert missing == ["clients/*/"]

    def test_literal_override_excluded_from_patterns_own_expansion(self, tmp_path):
        """clients/acme/ has its own explicit catalog entry - the
        pattern's expansion must not ALSO produce a separate
        (pattern-key, acme-path) target, or acme would be invoked twice."""
        (tmp_path / "clients" / "acme").mkdir(parents=True)
        (tmp_path / "clients" / "globex").mkdir(parents=True)
        raw = {
            "clients/*/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]},
            "clients/acme/": {
                "purpose": "Acme", "lifecycle": "ongoing", "origin": ["self"],
                "inherit": {"attributes": "clients/*/"},
            },
        }
        resolved, _ = resolve_entries(raw, {}, "paths")
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert sorted(active) == sorted([
            ("clients/*/", (tmp_path / "clients" / "globex").resolve()),
            ("clients/acme/", (tmp_path / "clients" / "acme").resolve()),
        ])
        assert missing == []

    def test_pattern_fully_overridden_by_literals_is_not_missing(self, tmp_path):
        """Every real match is claimed by its own literal entry - the
        pattern itself contributes zero targets, but that's not
        "missing": the folders exist, just cataloged elsewhere."""
        (tmp_path / "clients" / "acme").mkdir(parents=True)
        raw = {
            "clients/*/": {"purpose": "P", "lifecycle": "ongoing", "origin": ["self"]},
            "clients/acme/": {
                "purpose": "Acme", "lifecycle": "ongoing", "origin": ["self"],
                "inherit": {"attributes": "clients/*/"},
            },
        }
        resolved, _ = resolve_entries(raw, {}, "paths")
        active, missing = _resolve_active_targets(resolved, tmp_path)
        assert active == [("clients/acme/", (tmp_path / "clients" / "acme").resolve())]
        assert missing == []


class TestCollectInvocations:

    def test_per_path_attachment(self, tmp_path, catalog):
        (tmp_path / "media").mkdir()
        data = {
            "paths": {
                "media/": {
                    "purpose": "M", "lifecycle": "ongoing", "origin": ["self"],
                    "rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": ["jpg"]}}]},
                }
            }
        }
        resolved, _ = resolve_entries(data["paths"], {}, "paths")
        invocations, missing = collect_invocations(data, tmp_path, catalog, resolved)
        assert len(invocations) == 1
        assert invocations[0].rule_id == "file-extensions-v1"
        assert missing == []

    def test_paths_rules_blanket_applies_to_every_cataloged_path(self, tmp_path, catalog):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        paths = {
            "a/": {"purpose": "A", "lifecycle": "ongoing", "origin": ["self"]},
            "b/": {"purpose": "B", "lifecycle": "ongoing", "origin": ["self"]},
            "rules": {"file-extensions-v1": [{"reason": "blanket", "params": {"allowed": ["jpg"]}}]},
        }
        data = {"paths": paths}
        resolved, _ = resolve_entries({k: v for k, v in paths.items() if k != "rules"}, {}, "paths")
        invocations, _ = collect_invocations(data, tmp_path, catalog, resolved)
        assert len(invocations) == 2  # one per cataloged path

    def test_pattern_key_produces_one_invocation_per_real_match(self, tmp_path, catalog):
        (tmp_path / "clients" / "acme").mkdir(parents=True)
        (tmp_path / "clients" / "globex").mkdir(parents=True)
        paths = {
            "clients/*/": {
                "purpose": "P", "lifecycle": "ongoing", "origin": ["self"],
                "rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": ["jpg"]}}]},
            }
        }
        data = {"paths": paths}
        resolved, _ = resolve_entries(paths, {}, "paths")
        invocations, missing = collect_invocations(data, tmp_path, catalog, resolved)
        assert len(invocations) == 2  # one per real match, sharing the same rule attachment
        assert {inv.target_path.name for inv in invocations} == {"acme", "globex"}
        assert all(inv.rule_id == "file-extensions-v1" for inv in invocations)
        assert missing == []

    def test_paths_cross(self, tmp_path, catalog):
        (tmp_path / "a").mkdir()
        (tmp_path / "b").mkdir()
        data = {
            "paths": {
                "a/": {"purpose": "A", "lifecycle": "ongoing", "origin": ["self"]},
                "b/": {"purpose": "B", "lifecycle": "ongoing", "origin": ["self"]},
                "cross": [{"paths": ["a/", "b/"], "rules": {"basename-sync-v1": [{"reason": "r", "params": {"mode": "shared"}}]}}],
            }
        }
        resolved, _ = resolve_entries(
            {k: v for k, v in data["paths"].items() if k not in ("cross",)}, {}, "paths"
        )
        invocations, _ = collect_invocations(data, tmp_path, catalog, resolved)
        assert len(invocations) == 1
        assert invocations[0].target_paths is not None
        assert len(invocations[0].target_paths) == 2

    def test_folders_rules_blanket_targets_root(self, tmp_path, catalog):
        data = {"paths": {}, "folders": {"rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": ["jpg"]}}]}}}
        invocations, _ = collect_invocations(data, tmp_path, catalog, {})
        assert len(invocations) == 1
        assert invocations[0].target_path == tmp_path

    def test_param_ref_expanded_to_table_keys(self, tmp_path, catalog):
        """{ref = "folders.reserved"} in a rule's params must reach the
        invocation as the actual list of reserved-folder names, not the
        raw ref table - and the `prefix` meta key must not leak in."""
        data = {
            "paths": {},
            "folders": {
                "rules": {
                    "uncataloged-reserved-v1": [
                        {"reason": "r", "params": {"cataloged": {"ref": "folders.reserved"}}}
                    ]
                },
                "reserved": {
                    "prefix": "_",
                    "_archive": {"purpose": "p", "lifecycle": "archival", "origin": ["self"]},
                },
            },
        }
        invocations, _ = collect_invocations(data, tmp_path, catalog, {})
        assert len(invocations) == 1
        assert invocations[0].params["cataloged"] == ["_archive"]

    def test_param_ref_to_list_expanded_verbatim(self, tmp_path, catalog):
        data = {
            "paths": {},
            "tags": {"media": {"paths": ["a/", "b/"]}},
            "folders": {"rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": {"ref": "tags.media.paths"}}}]}},
        }
        invocations, _ = collect_invocations(data, tmp_path, catalog, {})
        assert invocations[0].params["allowed"] == ["a/", "b/"]

    def test_missing_path_excluded_from_invocations(self, tmp_path, catalog):
        # path is cataloged but doesn't exist on disk, and isn't allow_missing
        data = {
            "paths": {
                "gone/": {
                    "purpose": "G", "lifecycle": "ongoing", "origin": ["self"],
                    "rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": ["jpg"]}}]},
                }
            }
        }
        resolved, _ = resolve_entries(data["paths"], {}, "paths")
        invocations, missing = collect_invocations(data, tmp_path, catalog, resolved)
        assert invocations == []
        assert missing == ["gone/"]


class TestReservedFolderInvocations:
    """[folders.reserved."_x".rules] targets every folder NAMED _x on
    disk - a reserved entry is a name, not a location."""

    RESERVED = {
        "prefix": "_",
        "_arch": {
            "purpose": "P", "lifecycle": "archival", "origin": ["self"],
            "rules": {"file-extensions-v1": [{"reason": "r", "params": {"allowed": ["jpg"]}}]},
        },
    }

    def _collect(self, tmp_path, catalog, reserved=None):
        reserved = self.RESERVED if reserved is None else reserved
        data = {"paths": {}, "folders": {"reserved": reserved}}
        entries = {k: v for k, v in reserved.items() if k != "prefix"}
        resolved_folders, _ = resolve_entries(entries, {}, "folders.reserved")
        return collect_invocations(data, tmp_path, catalog, {}, resolved_folders)[0]

    def test_one_invocation_per_matching_folder(self, tmp_path, catalog):
        (tmp_path / "prj" / "_arch").mkdir(parents=True)
        (tmp_path / "task" / "_arch").mkdir(parents=True)
        (tmp_path / "prj" / "live").mkdir()
        invocations = self._collect(tmp_path, catalog)
        assert len(invocations) == 2
        assert {inv.target_path.parent.name for inv in invocations} == {"prj", "task"}
        assert all(inv.location.startswith('folders.reserved."_arch"') for inv in invocations)

    def test_name_matching_nothing_contributes_no_invocations(self, tmp_path, catalog):
        (tmp_path / "prj").mkdir()
        assert self._collect(tmp_path, catalog) == []

    def test_nested_match_is_not_pruned(self, tmp_path, catalog):
        (tmp_path / "_arch" / "_arch").mkdir(parents=True)
        assert len(self._collect(tmp_path, catalog)) == 2

    def test_entry_without_rules_is_skipped(self, tmp_path, catalog):
        (tmp_path / "_arch").mkdir()
        reserved = {"prefix": "_", "_arch": {"purpose": "P", "lifecycle": "archival", "origin": ["self"]}}
        assert self._collect(tmp_path, catalog, reserved) == []

    def test_coexists_with_a_path_entry_for_the_same_folder(self, tmp_path, catalog):
        """prj/_arch/ is both a cataloged path and a reserved name; the two
        answer different questions, so both sets of rules apply."""
        (tmp_path / "prj" / "_arch").mkdir(parents=True)
        paths = {
            "prj/_arch/": {
                "purpose": "P", "lifecycle": "archival", "origin": ["self"],
                "rules": {"empty-v1": [{"reason": "r", "params": {}}]},
            }
        }
        data = {"paths": paths, "folders": {"reserved": self.RESERVED}}
        resolved_paths, _ = resolve_entries(paths, {}, "paths")
        entries = {k: v for k, v in self.RESERVED.items() if k != "prefix"}
        resolved_folders, _ = resolve_entries(entries, {}, "folders.reserved")
        invocations, _ = collect_invocations(data, tmp_path, catalog, resolved_paths, resolved_folders)
        assert {inv.rule_id for inv in invocations} == {"empty-v1", "file-extensions-v1"}
        assert {inv.target_path for inv in invocations} == {tmp_path / "prj" / "_arch"}

    def test_inherited_rules_are_carried(self, tmp_path, catalog):
        (tmp_path / "_old").mkdir()
        reserved = {
            "prefix": "_",
            "_arch": self.RESERVED["_arch"],
            "_old": {
                "purpose": "P", "lifecycle": "archival", "origin": ["self"],
                "inherit": {"rules": "_arch"},
            },
        }
        invocations = self._collect(tmp_path, catalog, reserved)
        assert len(invocations) == 1
        assert invocations[0].rule_id == "file-extensions-v1"
        assert "inherited from" in invocations[0].location


class TestInvokeScript:

    def test_ok_status(self, tmp_path, catalog):
        (tmp_path / "clean").mkdir()
        (tmp_path / "clean" / "a.jpg").touch()
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=tmp_path / "clean")
        result = invoke_script(entry.check_script, inv, is_fix=False)
        assert result.status == "ok"

    def test_violation_status(self, tmp_path, catalog):
        (tmp_path / "dirty").mkdir()
        (tmp_path / "dirty" / "a.pdf").touch()
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=tmp_path / "dirty")
        result = invoke_script(entry.check_script, inv, is_fix=False)
        assert result.status == "violation"
        assert "a.pdf" in result.message

    def test_broken_status_on_bad_target(self, tmp_path, catalog):
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=tmp_path / "does-not-exist")
        result = invoke_script(entry.check_script, inv, is_fix=False)
        assert result.status == "broken"

    def test_run_invocation_uses_checker_when_no_fixer(self, tmp_path, catalog):
        # file-extensions-v1 has no fixer - even with fix_requested=True it
        # should fall back to running the checker normally
        (tmp_path / "clean").mkdir()
        entry = catalog["file-extensions-v1"]
        assert entry.has_fixer is False
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=tmp_path / "clean")
        result = run_invocation(inv, fix_requested=True)
        assert result.status == "ok"


class TestStalePlanIsSkipped:
    """Targets are expanded once, up front, so a fixer can move or delete
    a folder a later invocation was already planned against. That's the
    fixer working, so it must not surface as `broken` - the signal
    reserved for a rule that's genuinely misconfigured."""

    def test_vanished_target_is_skipped(self, tmp_path, catalog):
        gone = tmp_path / "gone"
        gone.mkdir()
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=gone)
        gone.rmdir()   # as if a fixer earlier in the same pass moved it
        result = run_invocation(inv, fix_requested=False)
        assert result.status == "skipped"
        assert "no longer exists" in result.message

    def test_target_replaced_by_a_file_is_skipped(self, tmp_path, catalog):
        target = tmp_path / "swapped"
        target.mkdir()
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=target)
        target.rmdir()
        target.touch()
        result = run_invocation(inv, fix_requested=False)
        assert result.status == "skipped"
        assert "no longer a directory" in result.message

    def test_one_vanished_target_skips_a_cross_invocation(self, tmp_path, catalog):
        a, b = tmp_path / "a", tmp_path / "b"
        a.mkdir()
        b.mkdir()
        entry = catalog["basename-sync-v1"]
        inv = Invocation("basename-sync-v1", entry, "loc", "reason", {}, target_paths=[a, b])
        b.rmdir()
        result = run_invocation(inv, fix_requested=False)
        assert result.status == "skipped"
        assert str(b) in result.message

    def test_target_absent_when_planned_is_still_broken(self, tmp_path, capsys):
        """A path that was never there is a misconfigured attachment, not
        a fixer's doing - it must still reach the script. paths.cross
        resolves its references directly instead of through the
        exists-on-disk filter, so this is the shape that can produce one."""
        real = tmp_path / "real"
        real.mkdir()
        (real / "a.jpg").touch()
        std_path = tmp_path / "fs-org-std.toml"
        std_path.write_text(f'''root = "{tmp_path}/"

[meta]
schema_version = "1.0"
standard_version = "1.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"

[paths.attributes]
names = ["purpose", "lifecycle", "origin", "allow_missing"]
[paths.attributes.defaults]
allow_missing = false

[paths."real/"]
purpose = "Real"
lifecycle = "ongoing"
origin = ["self"]

[[paths.cross]]
paths = ["real/", "never-existed/"]

[[paths.cross.rules.basename-sync-v1]]
reason = "r"

[paths.cross.rules.basename-sync-v1.params]
mode = "shared"

[enums.paths.lifecycle]
ongoing = "x"
archival = "x"
[enums.paths.origin]
self = "x"
[tags]
[abbreviations]
[folders]
[folders.attributes]
names = []
[folders.attributes.defaults]
[folders.reserved]
''')
        exit_code = main([str(std_path), "--no-color"])
        out = capsys.readouterr().out
        assert "BROKEN" in out
        assert "SKIPPED" not in out
        assert exit_code == 1

    def test_invoke_script_still_reports_broken(self, tmp_path, catalog):
        # The guard belongs to run_invocation (should this run at all?),
        # not invoke_script (run it) - handed a bad path directly, the
        # script is still what reports the problem.
        entry = catalog["file-extensions-v1"]
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=tmp_path / "nope")
        assert invoke_script(entry.check_script, inv, is_fix=False).status == "broken"


class TestCacheDirWiring:
    """The core owns where a rule caches - the rule is handed a
    ready-made directory, it never resolves one itself."""

    def test_caching_rule_receives_a_cache_dir(self, tmp_path, catalog, monkeypatch):
        from fs_org_kit.cache import ENV_OVERRIDE
        monkeypatch.setenv(ENV_OVERRIDE, str(tmp_path / "cacheroot"))

        target = tmp_path / "tree"
        target.mkdir()
        (target / "a.txt").write_text("dup")
        (target / "b.txt").write_text("dup")

        entry = catalog["duplicate-files-v1"]
        assert entry.uses_cache is True
        inv = Invocation("duplicate-files-v1", entry, "loc", "reason", {}, target_path=target)
        result = invoke_script(entry.check_script, inv, is_fix=False)

        assert result.status == "violation"
        expected = tmp_path / "cacheroot" / "rules" / "duplicate-files-v1"
        assert (expected / "duplicate-files-v1.sqlite3").exists()

    def test_non_caching_rule_gets_no_cache_dir(self, tmp_path, catalog, monkeypatch):
        """A rule that doesn't declare uses_cache must never see the
        flag - otherwise every existing rule's argparse would reject it."""
        from fs_org_kit.cache import ENV_OVERRIDE
        monkeypatch.setenv(ENV_OVERRIDE, str(tmp_path / "cacheroot"))

        target = tmp_path / "clean"
        target.mkdir()
        entry = catalog["file-extensions-v1"]
        assert entry.uses_cache is False
        inv = Invocation("file-extensions-v1", entry, "loc", "reason", {"allowed": ["jpg"]}, target_path=target)
        result = invoke_script(entry.check_script, inv, is_fix=False)

        assert result.status == "ok"
        assert not (tmp_path / "cacheroot").exists()

    def test_unusable_cache_location_does_not_break_the_run(self, tmp_path, catalog, monkeypatch):
        """A cache that can't be created costs speed, not correctness."""
        from fs_org_kit.cache import ENV_OVERRIDE
        blocker = tmp_path / "blocker"
        blocker.write_text("a file where a directory should go")
        monkeypatch.setenv(ENV_OVERRIDE, str(blocker))

        target = tmp_path / "tree"
        target.mkdir()
        (target / "a.txt").write_text("dup")
        (target / "b.txt").write_text("dup")

        entry = catalog["duplicate-files-v1"]
        inv = Invocation("duplicate-files-v1", entry, "loc", "reason", {}, target_path=target)
        result = invoke_script(entry.check_script, inv, is_fix=False)
        assert result.status == "violation"


class TestMainIntegration:
    """End-to-end through main(), against real files."""

    def _write_standard(self, tmp_path: Path, extra_toml: str) -> Path:
        std_path = tmp_path / "fs-org-std.toml"
        std_path.write_text(f'''root = "{tmp_path}/"

[meta]
schema_version = "1.0"
standard_version = "1.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"

[paths.attributes]
names = ["purpose", "lifecycle", "origin", "allow_missing"]

[paths.attributes.defaults]
allow_missing = false

{extra_toml}

[enums.paths.lifecycle]
ongoing = "x"
archival = "x"
[enums.paths.origin]
self = "x"
[tags]
[abbreviations]
[folders]
[folders.attributes]
names = []
[folders.attributes.defaults]
[folders.reserved]
''')
        return std_path

    def test_clean_run_exits_zero(self, tmp_path):
        (tmp_path / "clean").mkdir()
        (tmp_path / "clean" / "a.jpg").touch()
        std_path = self._write_standard(tmp_path, '''
[paths."clean/"]
purpose = "Clean"
lifecycle = "ongoing"
origin = ["self"]

[[paths."clean/".rules.file-extensions-v1]]
reason = "r"

[paths."clean/".rules.file-extensions-v1.params]
allowed = ["jpg"]
''')
        exit_code = main([str(std_path), "--no-color"])
        assert exit_code == 0

    def test_violation_exits_one(self, tmp_path):
        (tmp_path / "dirty").mkdir()
        (tmp_path / "dirty" / "a.pdf").touch()
        std_path = self._write_standard(tmp_path, '''
[paths."dirty/"]
purpose = "Dirty"
lifecycle = "ongoing"
origin = ["self"]

[[paths."dirty/".rules.file-extensions-v1]]
reason = "r"

[paths."dirty/".rules.file-extensions-v1.params]
allowed = ["jpg"]
''')
        exit_code = main([str(std_path), "--no-color"])
        assert exit_code == 1

    def test_missing_path_without_allow_missing_exits_one(self, tmp_path):
        std_path = self._write_standard(tmp_path, '''
[paths."gone/"]
purpose = "Gone"
lifecycle = "ongoing"
origin = ["self"]
''')
        exit_code = main([str(std_path), "--no-color"])
        assert exit_code == 1

    def test_missing_path_with_allow_missing_exits_zero(self, tmp_path):
        std_path = self._write_standard(tmp_path, '''
[paths."gone/"]
purpose = "Gone"
lifecycle = "ongoing"
origin = ["self"]
allow_missing = true
''')
        exit_code = main([str(std_path), "--no-color"])
        assert exit_code == 0

    def test_invalid_standard_exits_two(self, tmp_path):
        std_path = tmp_path / "fs-org-std.toml"
        std_path.write_text("this is not a valid standard at all")
        exit_code = main([str(std_path), "--no-color"])
        assert exit_code == 2

    def test_inheritance_follows_a_real_filesystem_move(self, tmp_path):
        """The core PARA scenario: moving the real folder needs zero
        standard edits, as long as both sides are allow_missing."""
        (tmp_path / "active" / "proj").mkdir(parents=True)
        (tmp_path / "active" / "proj" / "a.jpg").touch()

        std_path = self._write_standard(tmp_path, '''
[paths."active/proj/"]
purpose = "Active"
lifecycle = "ongoing"
origin = ["self"]
allow_missing = true

[[paths."active/proj/".rules.file-extensions-v1]]
reason = "r"

[paths."active/proj/".rules.file-extensions-v1.params]
allowed = ["jpg"]

[paths."archive/proj/"]
lifecycle = "archival"
allow_missing = true

[paths."archive/proj/".inherit]
attributes = "active/proj/"
rules = "active/proj/"
''')
        assert main([str(std_path), "--no-color"]) == 0

        # simulate archiving - move the real folder, no TOML edit
        (tmp_path / "archive").mkdir()
        (tmp_path / "active" / "proj").rename(tmp_path / "archive" / "proj")

        assert main([str(std_path), "--no-color"]) == 0

    def test_fixer_moving_a_folder_skips_its_own_later_invocation(self, tmp_path, capsys):
        """The scenario from examples/para: staleness-v1 archives a
        project, and the per-project check already planned against its
        old location reports skipped, not broken."""
        (tmp_path / "projects" / "old").mkdir(parents=True)
        (tmp_path / "projects" / "old" / "a.jpg").touch()
        (tmp_path / "archive").mkdir()

        stale = time.time() - 200 * 86400
        os.utime(tmp_path / "projects" / "old" / "a.jpg", (stale, stale))

        std_path = self._write_standard(tmp_path, '''
[paths."projects/"]
purpose = "Projects"
lifecycle = "ongoing"
origin = ["self"]

[[paths."projects/".rules.staleness-v1]]
reason = "r"

[paths."projects/".rules.staleness-v1.params]
mode = "stale"
threshold = "90d"
destination = "archive"

[paths."projects/*/"]
purpose = "One project"
lifecycle = "ongoing"
origin = ["self"]
allow_missing = true

[[paths."projects/*/".rules.file-extensions-v1]]
reason = "r"

[paths."projects/*/".rules.file-extensions-v1.params]
allowed = ["jpg"]
''')
        exit_code = main([str(std_path), "--fix", "--no-color"])
        out = capsys.readouterr().out

        assert (tmp_path / "archive" / "old").is_dir()   # the fixer did move it
        assert "SKIPPED" in out
        assert "BROKEN" not in out
        assert exit_code == 0                            # skipped is not a failure


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
