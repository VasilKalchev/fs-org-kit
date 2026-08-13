"""
tests/test_discovery.py - unit tests for fs_org_kit.discovery

Run with: python -m pytest tests/test_discovery.py -v
Or simply: python -m pytest tests/
"""

import tempfile
from pathlib import Path

import pytest

from fs_org_kit.discovery import DiscoveryIssue, IssueLevel, Tier, discover_rules


class TestDiscoveryBaseline:
    """Baseline: discover bundled rules only, no own/external directories."""

    def test_bundled_only(self):
        """With empty own/external dirs, discover should find only bundled rules."""
        with tempfile.TemporaryDirectory() as td:
            std_dir = Path(td)
            catalog, issues = discover_rules(std_dir, include_external=False)

            assert "file-extensions-v1" in catalog
            assert catalog["file-extensions-v1"].tier == Tier.BUNDLED
            assert not catalog["file-extensions-v1"].has_fixer
            assert issues == []


class TestDiscoveryCollisions:
    """Test tier precedence and collision handling."""

    def test_own_collides_with_bundled_no_override_flag(self, tmp_path):
        """Own rule with same name as bundled, no overrides_bundled flag -> bundled wins, warning."""
        # Create own rules.own/
        own_dir = tmp_path / "rules.own" / "file-extensions-v1"
        own_dir.mkdir(parents=True)

        # Write a manifest without overrides_bundled
        (own_dir / "file-extensions-v1.toml").write_text(
            'version = "1.0"\npurpose = "own version without override"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "file-extensions-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path, include_external=False)

        # Bundled should win
        assert catalog["file-extensions-v1"].tier == Tier.BUNDLED
        # Warning about collision should be present
        collision_warnings = [i for i in issues if i.rule_id == "file-extensions-v1" and i.tier == Tier.OWN]
        assert len(collision_warnings) == 1
        assert "same name as a bundled rule" in collision_warnings[0].message

    def test_own_overrides_bundled_with_flag(self, tmp_path):
        """Own rule with overrides_bundled = true -> own wins, no warning."""
        own_dir = tmp_path / "rules.own" / "file-extensions-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "file-extensions-v1.toml").write_text(
            'version = "1.0"\npurpose = "own version WITH override"\noverrides_bundled = true\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "file-extensions-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path, include_external=False)

        # Own should win
        assert catalog["file-extensions-v1"].tier == Tier.OWN
        assert catalog["file-extensions-v1"].purpose == "own version WITH override"
        # No collision warning should exist
        collision_warnings = [i for i in issues if i.rule_id == "file-extensions-v1" and i.tier == Tier.OWN]
        assert collision_warnings == []

    def test_external_never_overrides(self, tmp_path):
        """External rule with same name as bundled, claiming overrides_bundled -> bundled wins, warnings for both."""
        ext_dir = tmp_path / "rules.external" / "file-extensions-v1"
        ext_dir.mkdir(parents=True)

        (ext_dir / "file-extensions-v1.toml").write_text(
            'version = "1.0"\npurpose = "external with false override claim"\noverrides_bundled = true\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (ext_dir / "file-extensions-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path, include_external=True)

        # Bundled should win
        assert catalog["file-extensions-v1"].tier == Tier.BUNDLED
        # Two warnings: one about the false override claim, one about the collision
        ext_issues = [i for i in issues if i.tier == Tier.EXTERNAL and i.rule_id == "file-extensions-v1"]
        assert len(ext_issues) == 2
        assert any("overrides_bundled" in i.message for i in ext_issues)
        assert any("never override" in i.message for i in ext_issues)

    def test_include_external_false_skips_scanning(self, tmp_path):
        """include_external=False should not even scan the tier, zero issues from it."""
        ext_dir = tmp_path / "rules.external" / "only-external-v1"
        ext_dir.mkdir(parents=True)

        (ext_dir / "only-external-v1.toml").write_text(
            'version = "1.0"\npurpose = "legit external rule"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (ext_dir / "only-external-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path, include_external=False)

        assert "only-external-v1" not in catalog
        external_issues = [i for i in issues if i.tier == Tier.EXTERNAL]
        assert external_issues == []


class TestDiscoveryErrors:
    """Test validation of rule structure."""

    def test_broken_toml_manifest(self, tmp_path):
        """Invalid TOML in manifest -> error, rule excluded."""
        own_dir = tmp_path / "rules.own" / "broken-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "broken-v1.toml").write_text("this is [[ not = = valid toml")
        (own_dir / "broken-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "broken-v1" not in catalog
        errors = [i for i in issues if i.level == IssueLevel.ERROR and i.rule_id == "broken-v1"]
        assert len(errors) == 1
        assert "not valid TOML" in errors[0].message

    def test_missing_checker_script(self, tmp_path):
        """Manifest present but no checker script -> error, excluded."""
        own_dir = tmp_path / "rules.own" / "no-checker-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "no-checker-v1.toml").write_text(
            'version = "1.0"\npurpose = "missing checker"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        # No -check.py file

        catalog, issues = discover_rules(tmp_path)

        assert "no-checker-v1" not in catalog
        errors = [i for i in issues if i.rule_id == "no-checker-v1"]
        assert len(errors) == 1
        assert "no checker script" in errors[0].message

    def test_directory_name_mismatch(self, tmp_path):
        """Directory name doesn't match <name>-v<major> -> warning, skipped."""
        own_dir = tmp_path / "rules.own" / "bad-format"
        own_dir.mkdir(parents=True)

        (own_dir / "bad-format.toml").write_text('version = "1.0"')

        catalog, issues = discover_rules(tmp_path)

        assert "bad-format" not in catalog
        warnings = [i for i in issues if i.level == IssueLevel.WARNING and "bad-format" in str(i)]
        assert len(warnings) == 1
        assert "doesn't match <name>-v<major>" in warnings[0].message

    def test_version_major_mismatch(self, tmp_path):
        """Manifest version major doesn't match directory suffix -> error."""
        own_dir = tmp_path / "rules.own" / "mismatch-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "mismatch-v1.toml").write_text(
            'version = "2.0"\npurpose = "version major is 2, dir says v1"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "mismatch-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "mismatch-v1" not in catalog
        errors = [i for i in issues if i.rule_id == "mismatch-v1"]
        assert len(errors) == 1
        assert "doesn't match" in errors[0].message and "2" in errors[0].message

    def test_unsupported_protocol_major_excluded_not_blocking(self, tmp_path):
        """protocol_version major with no adapter -> warning (not error), rule
        excluded from the catalog, but a sibling rule still loads fine - unlike
        a broken manifest, this doesn't block anything else."""
        own_dir = tmp_path / "rules.own" / "future-protocol-v1"
        own_dir.mkdir(parents=True)
        (own_dir / "future-protocol-v1.toml").write_text(
            'version = "1.0"\npurpose = "speaks a protocol this runner doesn\'t know"\n'
            'scope = "single"\nprotocol_version = "99.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "future-protocol-v1-check.py").write_text('print("stub")')

        sibling_dir = tmp_path / "rules.own" / "fine-v1"
        sibling_dir.mkdir(parents=True)
        (sibling_dir / "fine-v1.toml").write_text(
            'version = "1.0"\npurpose = "ordinary rule"\n'
            'scope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (sibling_dir / "fine-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "future-protocol-v1" not in catalog
        assert "fine-v1" in catalog
        matching = [i for i in issues if i.rule_id == "future-protocol-v1"]
        assert len(matching) == 1
        assert matching[0].level == IssueLevel.WARNING
        assert "protocol_version" in matching[0].message and "99" in matching[0].message

    def test_malformed_protocol_version(self, tmp_path):
        """protocol_version that isn't major.minor shaped -> error, like version."""
        own_dir = tmp_path / "rules.own" / "bad-protocol-v1"
        own_dir.mkdir(parents=True)
        (own_dir / "bad-protocol-v1.toml").write_text(
            'version = "1.0"\npurpose = "malformed protocol_version"\n'
            'scope = "single"\nprotocol_version = "nope"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "bad-protocol-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "bad-protocol-v1" not in catalog
        errors = [i for i in issues if i.rule_id == "bad-protocol-v1"]
        assert len(errors) == 1
        assert errors[0].level == IssueLevel.ERROR
        assert "protocol_version" in errors[0].message and "malformed" in errors[0].message

    def test_unknown_manifest_field(self, tmp_path):
        """A field nothing reads is a typo doing nothing -> warning, rule still loads."""
        own_dir = tmp_path / "rules.own" / "typo-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "typo-v1.toml").write_text(
            'version = "1.0"\npurpose = "has a made-up field"\nfixable = true\n[params]\nnames = []\n'
        )
        (own_dir / "typo-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "typo-v1" in catalog
        warnings = [i for i in issues if i.rule_id == "typo-v1"]
        assert len(warnings) == 1
        assert warnings[0].level == IssueLevel.WARNING
        assert "fixable" in warnings[0].message

    def test_invalid_severity(self, tmp_path):
        """Severity value not one of discovery.SEVERITY -> error."""
        own_dir = tmp_path / "rules.own" / "bad-severity-v1"
        own_dir.mkdir(parents=True)

        (own_dir / "bad-severity-v1.toml").write_text(
            'version = "1.0"\npurpose = "bad severity"\nseverity = "catastrophic"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (own_dir / "bad-severity-v1-check.py").write_text('print("stub")')

        catalog, issues = discover_rules(tmp_path)

        assert "bad-severity-v1" not in catalog
        errors = [i for i in issues if i.rule_id == "bad-severity-v1"]
        assert len(errors) == 1
        assert "catastrophic" in errors[0].message and "not one of" in errors[0].message


class TestDisabledRules:
    """A leading underscore takes a directory out of the catalog entirely."""

    def _write_rule(self, directory: Path) -> None:
        directory.mkdir(parents=True)
        rule_id = directory.name
        (directory / f"{rule_id}.toml").write_text(
            'version = "1.0"\npurpose = "disabled"\n[params]\nnames = []\n'
        )
        (directory / f"{rule_id}-check.py").write_text('print("stub")')

    def test_underscore_prefixed_rule_is_skipped_silently(self, tmp_path):
        """Not loaded, and not complained about either - being skipped is
        the whole point of the prefix, so a warning would be noise."""
        self._write_rule(tmp_path / "rules.own" / "_draft-v1")

        catalog, issues = discover_rules(tmp_path)

        assert "_draft-v1" not in catalog
        assert [i for i in issues if "_draft" in str(i)] == []

    def test_a_disabled_rule_is_never_checked(self, tmp_path):
        """Even a rule that would be a discovery ERROR stays silent."""
        broken = tmp_path / "rules.own" / "_broken-v1"
        broken.mkdir(parents=True)
        (broken / "_broken-v1.toml").write_text("this is [[ not = = valid toml")

        catalog, issues = discover_rules(tmp_path)

        assert issues == []

    def test_the_bundled_templates_are_not_in_the_catalog(self, tmp_path):
        """rules/_template-*-v1/ are complete, valid rules on disk - only
        the prefix keeps them from running against a real filesystem."""
        catalog, _ = discover_rules(tmp_path)

        assert not [rule_id for rule_id in catalog if rule_id.startswith("_")]


class TestDiscoveryMetadata:
    """Test that RuleEntry fields are populated correctly."""

    def test_rule_entry_fields(self):
        """RuleEntry should have all manifest fields typed and accessible."""
        with tempfile.TemporaryDirectory() as td:
            catalog, issues = discover_rules(Path(td), include_external=False)

            assert "file-extensions-v1" in catalog
            entry = catalog["file-extensions-v1"]

            # Check all RuleEntry fields
            assert entry.rule_id == "file-extensions-v1"
            assert entry.tier == Tier.BUNDLED
            assert entry.version == "1.0"
            assert entry.purpose != ""
            assert entry.severity in ("none", "info", "warn", "error")
            assert entry.scope in ("single", "cross", "both")
            assert entry.protocol_version == "1.0"
            assert isinstance(entry.params_names, list)
            assert isinstance(entry.params_defaults, dict)
            assert entry.has_fixer is False  # file-extensions-v1 has no fixer


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
