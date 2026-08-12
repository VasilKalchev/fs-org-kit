"""
tests/test_fields.py - unit tests for fs_org_kit.fields

parse_field_spec reads what one namespace says its entries may carry.
These tests are about the DECLARATION only - checking an entry's values
against a spec is the validator's job, and lives in test_validator.py.

Run with: python -m pytest tests/test_fields.py -v
"""

import tomllib

import pytest

from fs_org_kit.fields import CONTROL_FIELDS, FieldSpec, parse_field_spec


def spec_for(toml_text: str, namespace: str = "paths"):
    return parse_field_spec(tomllib.loads(toml_text), namespace)


def locations(issues, level="error"):
    return [i.location for i in issues if i.level == level]


DECLARED = '''
[paths.attributes]
names = ["purpose", "notes", "use_for"]
required = ["purpose"]

[paths.grouping]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle"]

[enums.paths.lifecycle]
ongoing = "x"
archival = "x"

[enums.paths.origin]
self = "x"
'''


class TestParsing:

    def test_the_three_kinds_are_kept_apart(self):
        spec, issues = spec_for(DECLARED)
        assert issues == []
        assert spec.doc_names == ("purpose", "notes", "use_for")
        assert spec.grouping_names == ("lifecycle", "origin")
        assert spec.control_names == ("allow_missing", "outside_root")

    def test_declared_order_is_preserved(self):
        """The doc generator renders in this order, so it's the author's
        order, not alphabetical and not TOML-table-hash order."""
        spec, _ = spec_for('''
[paths.attributes]
names = ["zulu", "alpha", "mike"]
''')
        assert spec.doc_names == ("zulu", "alpha", "mike")

    def test_required_covers_both_kinds_documentation_first(self):
        spec, _ = spec_for(DECLARED)
        assert spec.required_names == ("purpose", "lifecycle")

    def test_multi_is_read_from_the_declaration(self):
        spec, _ = spec_for(DECLARED)
        assert spec.is_multi("origin")
        assert not spec.is_multi("lifecycle")

    def test_enum_values_come_from_the_matching_namespace(self):
        spec, _ = spec_for(DECLARED)
        assert spec.grouping_values["lifecycle"] == frozenset({"ongoing", "archival"})
        assert spec.enum_location("lifecycle") == "enums.paths.lifecycle"

    def test_an_empty_namespace_declares_nothing(self):
        spec, issues = spec_for("[paths]\n")
        assert issues == []
        assert not spec.is_declared()
        assert spec.known_names() == {"allow_missing", "outside_root"}


class TestNamespacesAreIndependent:

    def test_folders_reads_its_own_declarations_and_vocabularies(self):
        spec, issues = spec_for('''
[folders.attributes]
names = ["purpose"]

[folders.grouping]
names = ["visibility"]

[enums.folders.visibility]
shared = "x"
private = "x"

[enums.paths.lifecycle]
ongoing = "x"
''', namespace="folders")
        assert issues == []
        assert spec.grouping_values["visibility"] == frozenset({"shared", "private"})
        assert spec.doc_names == ("purpose",)

    def test_folders_has_no_control_fields(self):
        """A reserved NAME isn't one location, so neither control field has
        anything to apply to."""
        spec, _ = spec_for("[folders]\n", namespace="folders")
        assert spec.control_names == ()
        assert CONTROL_FIELDS["folders"] == ()

    def test_a_paths_vocabulary_does_not_reach_the_folders_namespace(self):
        spec, issues = spec_for('''
[folders.grouping]
names = ["lifecycle"]

[enums.paths.lifecycle]
ongoing = "x"
''', namespace="folders")
        assert spec.grouping_values["lifecycle"] == frozenset()
        assert "enums.folders.lifecycle" in locations(issues, "warning")


class TestDeclarationErrors:

    def test_names_must_be_a_list_of_strings(self):
        _, issues = spec_for('[paths.attributes]\nnames = "purpose"\n')
        assert "paths.attributes.names" in locations(issues)

    def test_required_must_name_a_declared_field(self):
        spec, issues = spec_for('''
[paths.attributes]
names = ["purpose"]
required = ["notes"]
''')
        assert "paths.attributes.required" in locations(issues)
        assert spec.required_names == ()

    def test_multi_must_name_a_declared_grouping_field(self):
        _, issues = spec_for('''
[paths.grouping]
names = ["lifecycle"]
multi = ["origin"]
''')
        assert "paths.grouping.multi" in locations(issues)

    def test_a_control_field_cant_be_redeclared_as_documentation(self):
        _, issues = spec_for('[paths.attributes]\nnames = ["purpose", "allow_missing"]\n')
        assert "paths.attributes.names" in locations(issues)

    def test_a_control_field_cant_be_used_for_grouping(self):
        _, issues = spec_for('[paths.grouping]\nnames = ["outside_root"]\n')
        assert "paths.grouping.names" in locations(issues)

    def test_a_field_cant_be_both_documentation_and_grouping(self):
        """The two kinds are read differently - one free-form, one against a
        closed vocabulary - so a name has to pick one."""
        _, issues = spec_for('''
[paths.attributes]
names = ["lifecycle"]

[paths.grouping]
names = ["lifecycle"]
''')
        assert "paths.grouping.names" in locations(issues)

    def test_a_name_listed_twice_is_an_error(self):
        _, issues = spec_for('[paths.attributes]\nnames = ["purpose", "purpose"]\n')
        assert "paths.attributes.names" in locations(issues)

    def test_a_grouping_field_with_no_vocabulary_warns_but_still_groups(self):
        spec, issues = spec_for('[paths.grouping]\nnames = ["lifecycle"]\n')
        assert "enums.paths.lifecycle" in locations(issues, "warning")
        assert spec.grouping_names == ("lifecycle",)


class TestSpecHelpers:

    def test_known_names_spans_all_three_kinds(self):
        spec, _ = spec_for(DECLARED)
        assert spec.known_names() == {
            "purpose", "notes", "use_for", "lifecycle", "origin", "allow_missing", "outside_root",
        }

    def test_an_undeclared_spec_is_usable_as_a_default(self):
        """The validator holds one of these before it has parsed anything."""
        spec = FieldSpec("paths")
        assert not spec.is_declared()
        assert spec.required_names == ()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
