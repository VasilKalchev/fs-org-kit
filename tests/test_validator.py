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
[paths.attributes.group]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle", "origin"]

[enums.group.lifecycle]
ongoing = "x"
archival = "x"

[enums.group.origin]
self = "x"

[tags]
[abbreviations]
[folders.attributes]
names = []
[folders.reserved]
'''

BOILERPLATE_HEAD = '''root = "~/usr/"

[meta]
schema_version = "2.0"
standard_version = "2.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"
'''


class TestValidatorBaseline:
    """Baseline: valid standard with one rule attachment."""

    def test_valid_standard(self, tmp_path):
        """A valid standard with one rule attachment should produce no errors."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "notes", "use_for", "not_for", "see_also"]
required = ["purpose"]

[paths."media/img/"]
purpose = "Personal photos"
notes = ""
use_for = ["photos"]
not_for = [""]
see_also = ""

[paths."media/img/".group]
lifecycle = "ongoing"
origin = ["self"]

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
names = ["purpose"]
required = ["purpose"]

[paths."test/"]
purpose = "Test path"

[paths."test/".group]
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
names = ["purpose"]
required = ["purpose"]

[[paths.cross]]
paths = ["a/", "b/"]

[[paths.cross.rules.file-extensions-v1]]
reason = "testing scope mismatch"

[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."b/"]
purpose = "B"

[paths."b/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."test/"]
purpose = "Test"

[paths."test/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."test/"]
purpose = "Test"

[paths."test/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "One client's workspace"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], f"Expected no errors, got: {errors}"

    def test_pattern_overlapping_literal_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "One client's workspace"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically"

[paths."clients/acme/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "Client workspace"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."vendors/*/"]
purpose = "Vendor workspace"

[paths."vendors/*/".group]
lifecycle = "ongoing"
origin = ["self"]
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert errors == []

    def test_literal_overriding_pattern_via_inherit_is_sanctioned(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "A client's workspace"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically"

[paths."clients/acme/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/".inherit]
doc = "clients/*/"
group = "clients/*/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert errors == []

    def test_literal_overlapping_pattern_without_inherit_is_still_error(self, tmp_path):
        """Merely overlapping isn't enough to be sanctioned - the literal
        must explicitly reference the pattern via inherit."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "A client's workspace"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/acme/"]
purpose = "Acme specifically, no inherit link"

[paths."clients/acme/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."clients/*/"]
purpose = "A"

[paths."clients/*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/a*/"]
purpose = "B"

[paths."clients/a*/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."clients/a*/".inherit]
doc = "clients/*/"
group = "clients/*/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "overlap" in i.message.lower()]
        assert len(errors) == 1

    def test_two_distinct_literals_never_flagged(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."b/"]
purpose = "B"

[paths."b/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."active/x/"]
purpose = "Active"

[paths."active/x/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."archive/x/".group]
lifecycle = "archival"


[paths."archive/x/".inherit]
doc = "active/x/"
group = "active/x/"
''' + BOILERPLATE_TAIL

        issues, validator = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert errors == [], errors
        assert validator.resolved_paths["archive/x/"].doc["purpose"] == "Active"

    def test_undefined_inherit_reference_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."x/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."x/".inherit]
doc = "nonexistent/"
group = "nonexistent/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error" and "unknown paths key" in i.message]
        assert errors

    def test_inherit_cycle_is_error(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."a/".inherit]
doc = "b/"
group = "b/"

[paths."b/".inherit]
doc = "a/"
group = "a/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        cycle_errors = [i for i in issues if "cycle" in i.message]
        assert len(cycle_errors) >= 1

    def test_exclude_rules_actually_removes_rule_from_validation(self, tmp_path):
        """If a rule id is excluded, it shouldn't be validated (or required)
        on the inheriting entry at all."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths."parent/"]
purpose = "P"

[paths."parent/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."parent/".rules.file-extensions-v1]]
reason = "r"

[paths."parent/".rules.file-extensions-v1.params]
allowed = ["jpg"]

[paths."child/"]
purpose = "C"

[paths."child/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."source/"]
purpose = "Source"

[paths."source/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."pure/".inherit]
doc = "source/"
group = "source/"
''' + BOILERPLATE_TAIL

        issues, _ = validate(standard_toml, tmp_path)
        orphan_errors = [i for i in issues if "isn't declared" in i.message]
        assert orphan_errors == []


class TestValidatorEntryFields:
    """An entry is checked against what its namespace declared - see
    fs_org_kit.fields. Nothing here is checked by name; every fixture
    declares the names it uses."""

    def _std(self, entry: str, declarations: str = '''
[paths.attributes]
names = ["purpose", "notes"]
required = ["purpose"]
''') -> str:
        return BOILERPLATE_HEAD + declarations + entry + BOILERPLATE_TAIL

    def test_a_documentation_field_may_be_a_string_or_a_list(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"
notes = ["one", "two"]

[paths."x/".group]
lifecycle = "ongoing"
origin = ["self"]
'''), tmp_path)
        assert [i for i in issues if i.level == "error"] == []

    def test_a_documentation_field_of_another_type_is_an_error(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"
notes = 42

[paths."x/".group]
lifecycle = "ongoing"
origin = ["self"]
'''), tmp_path)
        errors = [i for i in issues if i.level == "error" and i.location == 'paths."x/".notes']
        assert len(errors) == 1

    def test_a_required_field_left_empty_is_an_error(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = ""

[paths."x/".group]
lifecycle = "ongoing"
origin = ["self"]
'''), tmp_path)
        assert 'paths."x/".purpose' in [i.location for i in issues if i.level == "error"]

    def test_a_field_the_namespace_never_declared_is_flagged(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"
invented = "who is this for?"

[paths."x/".group]
lifecycle = "ongoing"
origin = ["self"]
'''), tmp_path)
        warnings = [i for i in issues if i.level == "warning" and i.location == 'paths."x/".invented']
        assert len(warnings) == 1
        assert warnings[0].code == "unknown-path-field"

    def test_a_grouping_value_outside_its_vocabulary_is_an_error(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"

[paths."x/".group]
lifecycle = "made-up"
origin = ["self"]
'''), tmp_path)
        errors = [i for i in issues if i.level == "error" and i.location == 'paths."x/".group.lifecycle']
        assert len(errors) == 1
        assert "enums.group.lifecycle" in errors[0].message

    def test_a_single_valued_grouping_field_given_a_list_is_an_error(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"

[paths."x/".group]
lifecycle = ["ongoing", "archival"]
origin = ["self"]
'''), tmp_path)
        errors = [i for i in issues if i.level == "error" and i.location == 'paths."x/".group.lifecycle']
        assert len(errors) == 1
        assert "group.multi" in errors[0].message

    def test_a_multi_valued_grouping_field_given_a_scalar_is_an_error(self, tmp_path):
        issues, _ = validate(self._std('''
[paths."x/"]
purpose = "X"

[paths."x/".group]
lifecycle = "ongoing"
origin = "self"
[folders]
'''), tmp_path)
        errors = [i for i in issues if i.level == "error" and i.location == 'paths."x/".group.origin']
        assert len(errors) == 1

    def test_a_grouping_field_with_no_vocabulary_warns_once_and_accepts_anything(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths.attributes.group]
names = ["stage"]

[paths."x/"]
purpose = "X"

[paths."x/".group]
stage = "anything at all"

[enums.group.lifecycle]
ongoing = "x"
[tags]
[abbreviations]
[folders]
'''
        issues, _ = validate(standard_toml, tmp_path)
        assert [i for i in issues if i.level == "error"] == []
        warnings = [i for i in issues if i.code == "missing-grouping-enum"]
        assert [w.location for w in warnings] == ["enums.group.stage"]


class TestValidatorFolders:
    """folders.doc / folders.group / folders.reserved.* - the same two
    declarations as paths, read independently."""

    def test_folders_declares_its_own_fields(self, tmp_path):
        """A name that's fine on a path is unknown on a reserved folder
        unless the folders namespace declared it too - the field lists are
        per namespace, even though the vocabularies aren't."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = ["purpose", "notes"]

[folders.attributes]
names = ["purpose"]

[folders.reserved."_archive"]
purpose = "Archive"
notes = "declared for paths, not for folders"

[enums.group.lifecycle]
ongoing = "x"
[enums.group.origin]
self = "x"
[tags]
[abbreviations]
'''
        issues, _ = validate(standard_toml, tmp_path)
        warnings = [i for i in issues if i.location == 'folders.reserved."_archive".notes']
        assert len(warnings) == 1

    def test_reserved_entries_with_no_declaration_at_all_are_flagged(self, tmp_path):
        """Undeclared means both unchecked and unrendered - the generated
        docs would show these entries as names alone."""
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[folders.reserved."_archive"]
purpose = "Archive"

[enums.group.lifecycle]
ongoing = "x"
[tags]
[abbreviations]
[folders]
'''
        issues, _ = validate(standard_toml, tmp_path)
        warnings = [i for i in issues if i.location == "folders.attributes.names"]
        assert len(warnings) == 1

    def test_folders_groups_against_the_shared_vocabulary(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[folders.attributes]
names = ["purpose"]

[folders.attributes.group]
names = ["visibility"]
required = ["visibility"]

[folders.reserved."_archive"]
purpose = "Archive"

[folders.reserved."_archive".group]
visibility = "shared"

[folders.reserved."_secret"]
purpose = "Secret"

[folders.reserved."_secret".group]
visibility = "unlisted"

[enums.group.visibility]
shared = "x"
private = "x"
[tags]
[abbreviations]
'''
        issues, _ = validate(standard_toml, tmp_path)
        errors = [i for i in issues if i.level == "error"]
        assert [e.location for e in errors] == ['folders.reserved."_secret".group.visibility']
        assert "enums.group.visibility" in errors[0].message

    def test_unknown_field_on_reserved_folder(self, tmp_path):
        standard_toml = BOILERPLATE_HEAD + '''
[paths.attributes]
names = []

[folders.attributes]
names = ["purpose"]
required = ["purpose"]

[folders.reserved."_archive"]
purpose = "Archive"
not_a_real_field = "oops"

[enums.group.lifecycle]
archival = "x"
[enums.group.origin]
self = "x"
[tags]
[abbreviations]
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
names = ["purpose"]
required = ["purpose"]

[folders.reserved]
prefix = "_"

[folders.reserved."_archive"]
purpose = "Archive"

[[folders.rules.uncataloged-reserved-v1]]
reason = "catch stray reserved-looking folders"

[folders.rules.uncataloged-reserved-v1.params]
cataloged = { ref = "folders.reserved" }

[enums.group.lifecycle]
archival = "x"
[enums.group.origin]
self = "x"
[tags]
[abbreviations]
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

[paths."notes/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."notes/".rules.spelling-abbreviations-v1]]
reason = "catch typos"

[paths."notes/".rules.spelling-abbreviations-v1.params]
abbreviations = { ref = "abbreviations" }

[enums.group.lifecycle]
ongoing = "x"
[enums.group.origin]
self = "x"
[tags]

[abbreviations]
arch = "Archive"

[folders]
purpose = "x"
names = []
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

[paths."notes/".group]
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

[paths."x/".group]
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
names = ["purpose"]
required = ["purpose"]

[paths."x/"]
purpose = "X"

[paths."x/".group]
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
