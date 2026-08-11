"""
tests/test_validator.py - unit tests for fs_org_kit.validator

Run with: python -m pytest tests/test_validator.py -v
Or simply: python -m pytest tests/
"""

import tempfile
import tomllib
from pathlib import Path

import pytest

from fs_org_kit.validator import Validator, _index_source


def validate(standard_toml: str, tmp_path: Path, **validator_kwargs):
    """Write standard_toml to tmp_path, parse it, and run the validator.
    Returns (issues, validator). Shared by every test below so each test
    body is just the fixture TOML plus assertions."""
    std_path = tmp_path / "test.toml"
    std_path.write_text(standard_toml)
    data = tomllib.loads(standard_toml)
    header_occurrences, key_lines = _index_source(standard_toml)
    validator = Validator(data, tmp_path, header_occurrences, key_lines, **validator_kwargs)
    return validator.run(), validator


BOILERPLATE_TAIL = '''
[enums.paths.lifecycle]
ongoing = "x"
archival = "x"

[enums.paths.origin]
self = "x"

[tags]
[abbreviations]
[folders]
purpose = "x"
[folders.attributes]
names = []
[folders.attributes.defaults]
[folders.reserved]
'''

BOILERPLATE_HEAD = '''root = "~/usr/"

[meta]
schema_version = "1.0"
standard_version = "1.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"
'''


class TestValidatorBaseline:
    """Baseline: valid standard with one rule attachment."""

    def test_valid_standard(self, tmp_path):
        """A valid standard with one rule attachment should produce no errors."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "notes", "use_for", "not_for", "lifecycle", "origin", "see_also"]

[paths."media/img/"]
purpose = "Personal photos"
notes = ""
use_for = ["photos"]
not_for = [""]
lifecycle = "ongoing"
origin = ["self"]
see_also = ""

[[paths."media/img/".rules.file-extensions-v1]]
reason = "keep images to known formats"

[paths."media/img/".rules.file-extensions-v1.params]
allowed = ["jpg", "png", "gif"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

        warnings = [i for i in issues if i.level == "warning"]
        assert len(warnings) >= 1
        assert any("empty" in w.message for w in warnings)


class TestValidatorRuleAttachmentErrors:
    """Rule attachment validation: unknown rule, scope mismatch, missing reason, unknown param."""

    def test_unknown_rule(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."test/"]
purpose = "Test path"
lifecycle = "ongoing"
origin = ["self"]

[[paths."test/".rules.nonexistent-rule-v1]]
reason = "testing unknown rule"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "nonexistent" in i.message]
        assert len(errors) == 1
        assert "not found" in errors[0].message

    def test_scope_mismatch(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[[paths.cross]]
paths = ["a/", "b/"]

[[paths.cross.rules.file-extensions-v1]]
reason = "testing scope mismatch"

[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]

[paths."b/"]
purpose = "B"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "scope" in i.message]
        assert len(errors) == 1
        assert "single" in errors[0].message
        assert "paths.cross" in errors[0].message

    def test_missing_reason(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."test/"]
purpose = "Test"
lifecycle = "ongoing"
origin = ["self"]

[[paths."test/".rules.file-extensions-v1]]
reason = ""
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "reason" in i.message]
        assert len(errors) == 1

    def test_unknown_param(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."test/"]
purpose = "Test"
lifecycle = "ongoing"
origin = ["self"]

[[paths."test/".rules.file-extensions-v1]]
reason = "test unknown param"

[paths."test/".rules.file-extensions-v1.params]
allowed = ["jpg"]
typo_param = "this doesn't exist"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        warnings = [i for i in issues if i.level == "warning" and i.code == "unknown-param"]
        assert len(warnings) == 1
        assert "typo_param" in warnings[0].message


class TestValidatorPatternKeys:
    """Glob-style [paths."..."] keys (fs_org_kit.path_patterns) - the
    overlap check is a pure string comparison, no filesystem access."""

    def test_pattern_key_alone_is_fine(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "One client's workspace"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_pattern_overlapping_literal_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "One client's workspace"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert len(errors) == 1
        assert 'clients/*/' in errors[0].location or 'clients/*/' in errors[0].message

    def test_two_non_overlapping_patterns_are_fine(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "Client workspace"
lifecycle = "ongoing"
origin = ["self"]

[paths."vendors/*/"]
purpose = "Vendor workspace"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert errors == []

    def test_literal_overriding_pattern_via_inherit_is_sanctioned(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "A client's workspace"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/".inherit]
attributes = "clients/*/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert errors == []

    def test_literal_overlapping_pattern_without_inherit_is_still_error(self, tmp_path):
        """Merely overlapping isn't enough to be sanctioned - the literal
        must explicitly reference the pattern via inherit."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "A client's workspace"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically, no inherit link"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert len(errors) == 1

    def test_two_overlapping_patterns_never_sanctioned(self, tmp_path):
        """Two patterns have no override mechanism, inherit or otherwise -
        always an error."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."clients/*/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/a*/"]
purpose = "B"
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/a*/".inherit]
attributes = "clients/*/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert len(errors) == 1

    def test_two_distinct_literals_never_flagged(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]

[paths."b/"]
purpose = "B"
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert errors == []


class TestValidatorInheritance:
    """Path/folder inheritance integration - resolve_entries wired into the validator."""

    def test_inherited_attributes_satisfy_required_fields(self, tmp_path):
        """A field only present via inheritance must NOT be flagged missing."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin", "allow_missing"]
[paths.attributes.defaults]
allow_missing = false

[paths."active/x/"]
purpose = "Active"
lifecycle = "ongoing"
origin = ["self"]

[paths."archive/x/"]
lifecycle = "archival"
allow_missing = true

[paths."archive/x/".inherit]
attributes = "active/x/"
''' + BOILERPLATE_TAIL

        issues, validator = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], errors
        assert validator.resolved_paths["archive/x/"].attributes["purpose"] == "Active"

    def test_undefined_inherit_reference_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."x/"]
lifecycle = "ongoing"
origin = ["self"]

[paths."x/".inherit]
attributes = "nonexistent/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "unknown paths key" in i.message]
        assert len(errors) == 1

    def test_inherit_cycle_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."a/".inherit]
attributes = "b/"

[paths."b/".inherit]
attributes = "a/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        cycle_errors = [i for i in issues if "cycle" in i.message]
        assert len(cycle_errors) >= 1

    def test_exclude_rules_actually_removes_rule_from_validation(self, tmp_path):
        """If a rule id is excluded, it shouldn't be validated (or required)
        on the inheriting entry at all."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."parent/"]
purpose = "P"
lifecycle = "ongoing"
origin = ["self"]

[[paths."parent/".rules.file-extensions-v1]]
reason = "r"

[paths."parent/".rules.file-extensions-v1.params]
allowed = ["jpg"]

[paths."child/"]
purpose = "C"
lifecycle = "ongoing"
origin = ["self"]

[paths."child/".inherit]
rules = "parent/"
exclude_rules = ["file-extensions-v1"]
''' + BOILERPLATE_TAIL

        issues, validator = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], errors
        assert validator.resolved_paths["child/"].rules == {}

    def test_purely_inherited_entry_not_flagged_as_orphaned(self, tmp_path):
        """A [paths."x/".inherit] entry with no other own fields is legitimate,
        not the 'rule attached to an undeclared path' mistake."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."source/"]
purpose = "Source"
lifecycle = "ongoing"
origin = ["self"]

[paths."pure/".inherit]
attributes = "source/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        orphan_errors = [i for i in issues if "isn't declared" in i.message]
        assert orphan_errors == []

    def test_allow_missing_must_be_boolean(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin", "allow_missing"]

[paths."x/"]
purpose = "X"
lifecycle = "ongoing"
origin = ["self"]
allow_missing = "yes"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "allow_missing" in i.location]
        assert len(errors) == 1
        assert "boolean" in errors[0].message


class TestValidatorFoldersAttributes:
    """folders.attributes / folders.reserved.* - mirrors paths, minus allow_missing."""

    def test_unknown_field_on_reserved_folder(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[folders.attributes]
names = ["purpose", "lifecycle", "origin"]

[folders.reserved."_archive"]
purpose = "Archive"
lifecycle = "archival"
origin = ["self"]
not_a_real_field = "oops"

[enums.paths.lifecycle]
archival = "x"
[enums.paths.origin]
self = "x"
[tags]
[abbreviations]
[folders]
purpose = "x"
'''
        issues, _ = validate(standard_toml, tmp_path)
        warnings = [i for i in issues if i.level == "warning" and "not_a_real_field" in i.location]
        assert len(warnings) == 1


class TestValidatorParamRefs:
    """{ref = "dotted.path"} param values (fs_org_kit.param_refs), wired
    into rule-instance validation."""

    def test_ref_to_folders_reserved_resolves_with_no_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[folders.attributes]
names = ["purpose", "lifecycle", "origin"]

[folders.reserved]
prefix = "_"

[folders.reserved."_archive"]
purpose = "Archive"
lifecycle = "archival"
origin = ["self"]

[[folders.rules.uncataloged-reserved-v1]]
reason = "catch stray reserved-looking folders"

[folders.rules.uncataloged-reserved-v1.params]
cataloged = { ref = "folders.reserved" }

[enums.paths.lifecycle]
archival = "x"
[enums.paths.origin]
self = "x"
[tags]
[abbreviations]
[folders]
purpose = "x"
'''
        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_ref_to_abbreviations_resolves_with_no_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[paths."notes/"]
purpose = "Notes"
lifecycle = "ongoing"
origin = ["self"]

[[paths."notes/".rules.spelling-abbreviations-v1]]
reason = "catch typos"

[paths."notes/".rules.spelling-abbreviations-v1.params]
abbreviations = { ref = "abbreviations" }

[enums.paths.lifecycle]
ongoing = "x"
[enums.paths.origin]
self = "x"
[tags]

[abbreviations]
arch = "Archive"

[folders]
purpose = "x"
[folders.attributes]
names = []
[folders.attributes.defaults]
[folders.reserved]
'''
        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_broken_ref_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[paths."notes/"]
purpose = "Notes"
lifecycle = "ongoing"
origin = ["self"]

[[paths."notes/".rules.spelling-abbreviations-v1]]
reason = "catch typos"

[paths."notes/".rules.spelling-abbreviations-v1.params]
abbreviations = { ref = "no.such.table" }
''' + BOILERPLATE_TAIL
        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "no.such.table" in i.message]
        assert len(errors) == 1

    def test_ref_satisfies_required_param_with_no_default(self, tmp_path):
        """`cataloged` has no default in uncataloged-reserved-v1's manifest -
        a {ref: ...} value must count as "supplied", same as a literal."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[paths."x/"]
purpose = "X"
lifecycle = "ongoing"
origin = ["self"]

[[paths."x/".rules.uncataloged-reserved-v1]]
reason = "test"

[paths."x/".rules.uncataloged-reserved-v1.params]
cataloged = { ref = "folders.reserved" }
''' + BOILERPLATE_TAIL
        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "missing required param" in i.message]
        assert errors == []


class TestValidatorDiscoveryOptions:
    """include_external / bundled_rules_dir threaded through to discover_rules."""

    def test_include_external_makes_external_rule_attachable(self, tmp_path):
        ext_dir = tmp_path / "rules.external" / "only-external-v1"
        ext_dir.mkdir(parents=True)
        (ext_dir / "only-external-v1.toml").write_text(
            'version = "1.0"\npurpose = "p"\nscope = "single"\nprotocol_version = "1.0"\n[params]\nnames = []\n[params.defaults]\n'
        )
        (ext_dir / "only-external-v1-check.py").write_text('print("stub")')

        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "lifecycle", "origin"]

[paths."x/"]
purpose = "X"
lifecycle = "ongoing"
origin = ["self"]

[[paths."x/".rules.only-external-v1]]
reason = "r"
''' + BOILERPLATE_TAIL

        issues_without, _ = validate(standard_toml, tmp_path, include_external=False)
        assert any("not found in any rules tier" in i.message for i in issues_without if i.level == "error")

        issues_with, _ = validate(standard_toml, tmp_path, include_external=True)
        assert not any("not found in any rules tier" in i.message for i in issues_with if i.level == "error")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
