"""
tests/test_fields.py - unit tests for fs_org_kit.fields

parse_field_spec reads what one namespace says its entries may carry.
These tests are about the DECLARATION only - checking an entry's values
against a spec is the validator's job, and lives in test_validator.py.

Run with: python -m pytest tests/test_fields.py -v
"""

import tomllib

import pytest

from fs_org_kit.fields import ATTRIBUTES, GROUP, FieldSpec, parse_field_spec


def spec_for(toml_text: str, namespace: str = "paths"):
    return parse_field_spec(tomllib.loads(toml_text), namespace)


def locations(issues, level="error"):
    return [i.location for i in issues if i.level == level]


DECLARED = '''
[paths.attributes]
names = ["purpose", "notes", "use_for"]
required = ["purpose"]

[paths.attributes.group]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle"]

[enums.group.lifecycle]
ongoing = "x"
archival = "x"

[enums.group.origin]
self = "x"
'''


class TestParsing:

    def test_the_two_kinds_are_kept_apart(self):
        spec, issues = spec_for(DECLARED)
        assert issues == []
        assert spec.attribute_names == ("purpose", "notes", "use_for")
        assert spec.group_names == ("lifecycle", "origin")

    def test_declared_order_is_preserved(self):
        """The doc generator renders in this order, so it's the author's
        order, not alphabetical and not TOML-table-hash order."""
        spec, _ = spec_for('[paths.attributes]\nnames = ["zulu", "alpha", "mike"]\n')
        assert spec.attribute_names == ("zulu", "alpha", "mike")

    def test_required_is_read_per_table(self):
        spec, _ = spec_for(DECLARED)
        assert spec.required(ATTRIBUTES) == frozenset({"purpose"})
        assert spec.required(GROUP) == frozenset({"lifecycle"})

    def test_multi_is_read_from_the_declaration(self):
        spec, _ = spec_for(DECLARED)
        assert spec.is_multi("origin")
        assert not spec.is_multi("lifecycle")

    def test_an_empty_namespace_declares_nothing(self):
        spec, issues = spec_for("[paths]\n")
        assert issues == []
        assert not spec.is_declared()
        assert spec.attribute_names == () and spec.group_names == ()


class TestVocabularies:

    def test_a_grouping_vocabulary_is_read_from_its_kind(self):
        spec, _ = spec_for(DECLARED)
        assert spec.group_values["lifecycle"] == frozenset({"ongoing", "archival"})
        assert spec.enum_location(GROUP, "lifecycle") == "enums.group.lifecycle"

    def test_both_namespaces_share_one_vocabulary(self):
        """A value set describes the field, not who carries it - so
        `folders` grouping by `lifecycle` reads the same table `paths`
        does, with nothing to redeclare."""
        standard = '''
[paths.attributes.group]
names = ["lifecycle"]

[folders.attributes.group]
names = ["lifecycle"]

[enums.group.lifecycle]
ongoing = "x"
archival = "x"
'''
        paths_spec, paths_issues = spec_for(standard)
        folders_spec, folders_issues = spec_for(standard, namespace="folders")
        assert paths_issues == [] and folders_issues == []
        assert paths_spec.group_values["lifecycle"] == folders_spec.group_values["lifecycle"]

    def test_an_attribute_vocabulary_is_optional(self):
        """Prose by default; a standard may still close one field's value
        set without making it a grouping field."""
        spec, issues = spec_for('''
[paths.attributes]
names = ["purpose", "review_cycle"]

[enums.attributes.review_cycle]
annual = "x"
quarterly = "x"
''')
        assert issues == []
        assert spec.attribute_values == {"review_cycle": frozenset({"annual", "quarterly"})}

    def test_a_grouping_field_with_no_vocabulary_warns_but_still_groups(self):
        spec, issues = spec_for('[paths.attributes.group]\nnames = ["lifecycle"]\n')
        assert "enums.group.lifecycle" in locations(issues, "warning")
        assert spec.group_names == ("lifecycle",)


class TestNamespacesAreIndependent:

    def test_folders_reads_its_own_field_lists(self):
        spec, issues = spec_for('''
[paths.attributes]
names = ["purpose", "notes"]

[folders.attributes]
names = ["purpose"]
''', namespace="folders")
        assert issues == []
        assert spec.attribute_names == ("purpose",)


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
        assert spec.required(ATTRIBUTES) == frozenset()

    def test_multi_must_name_a_declared_grouping_field(self):
        _, issues = spec_for('''
[paths.attributes.group]
names = ["lifecycle"]
multi = ["origin"]
''')
        assert "paths.attributes.group.multi" in locations(issues)

    def test_a_field_cant_be_named_after_a_structural_key(self):
        """`group`, `rules` and `inherit` are how an entry is put
        together - a documentation field of the same name would be
        indistinguishable from one."""
        for reserved in ("group", "rules", "inherit"):
            _, issues = spec_for(f'[paths.attributes]\nnames = ["purpose", "{reserved}"]\n')
            assert "paths.attributes.names" in locations(issues), reserved

    def test_a_field_cant_be_both_documentation_and_grouping(self):
        """The two are read differently - one free-form, one against a
        closed vocabulary - so a name has to pick one."""
        _, issues = spec_for('''
[paths.attributes]
names = ["lifecycle"]

[paths.attributes.group]
names = ["lifecycle"]
''')
        assert "paths.attributes.group.names" in locations(issues)

    def test_a_name_listed_twice_is_an_error(self):
        _, issues = spec_for('[paths.attributes]\nnames = ["purpose", "purpose"]\n')
        assert "paths.attributes.names" in locations(issues)


class TestSpecHelpers:

    def test_an_undeclared_spec_is_usable_as_a_default(self):
        """The validator holds one of these before it has parsed anything."""
        spec = FieldSpec("paths")
        assert not spec.is_declared()
        assert spec.names(ATTRIBUTES) == () and spec.names(GROUP) == ()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
