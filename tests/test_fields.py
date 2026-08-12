"""
tests/test_fields.py - unit tests for fs_org_kit.fields

parse_field_spec reads what one namespace says its entries may carry.
These tests are about the DECLARATION only - checking an entry's values
against a spec is the validator's job, and lives in test_validator.py.

Run with: python -m pytest tests/test_fields.py -v
"""

import tomllib

import pytest

from fs_org_kit.fields import CONTROL_FIELDS, DOC, GROUP, RULES, FieldSpec, parse_field_spec


def spec_for(toml_text: str, namespace: str = "paths"):
    return parse_field_spec(tomllib.loads(toml_text), namespace)


def locations(issues, level="error"):
    return [i.location for i in issues if i.level == level]


DECLARED = '''
[paths.doc]
names = ["purpose", "notes", "use_for"]
required = ["purpose"]

[paths.group]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle"]

[paths.rules]
allow_missing = false

[enums.group.lifecycle]
ongoing = "x"
archival = "x"

[enums.group.origin]
self = "x"
'''


class TestParsing:

    def test_the_three_tables_are_kept_apart(self):
        spec, issues = spec_for(DECLARED)
        assert issues == []
        assert spec.doc_names == ("purpose", "notes", "use_for")
        assert spec.group_names == ("lifecycle", "origin")
        assert spec.control_names == ("allow_missing", "outside_root")

    def test_declared_order_is_preserved(self):
        """The doc generator renders in this order, so it's the author's
        order, not alphabetical and not TOML-table-hash order."""
        spec, _ = spec_for('[paths.doc]\nnames = ["zulu", "alpha", "mike"]\n')
        assert spec.doc_names == ("zulu", "alpha", "mike")

    def test_required_is_read_per_table(self):
        spec, _ = spec_for(DECLARED)
        assert spec.required(DOC) == frozenset({"purpose"})
        assert spec.required(GROUP) == frozenset({"lifecycle"})

    def test_multi_is_read_from_the_declaration(self):
        spec, _ = spec_for(DECLARED)
        assert spec.is_multi("origin")
        assert not spec.is_multi("lifecycle")

    def test_a_control_default_comes_from_the_namespace_rules_table(self):
        """An entry's control fields live in its `rules` table, so the
        standard-wide default for one lives in the namespace's."""
        spec, _ = spec_for(DECLARED)
        assert spec.defaults[RULES] == {"allow_missing": False}

    def test_only_control_fields_are_taken_from_that_table(self):
        """[paths.rules] also holds the blanket attachments - those are
        not defaults for anything."""
        spec, _ = spec_for('''
[paths.rules]
allow_missing = true

[[paths.rules.rule-a-v1]]
reason = "r"
''')
        assert spec.defaults[RULES] == {"allow_missing": True}

    def test_an_empty_namespace_declares_nothing(self):
        spec, issues = spec_for("[paths]\n")
        assert issues == []
        assert not spec.is_declared()
        assert spec.doc_names == () and spec.group_names == ()


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
[paths.group]
names = ["lifecycle"]

[folders.group]
names = ["lifecycle"]

[enums.group.lifecycle]
ongoing = "x"
archival = "x"
'''
        paths_spec, paths_issues = spec_for(standard)
        folders_spec, folders_issues = spec_for(standard, namespace="folders")
        assert paths_issues == [] and folders_issues == []
        assert paths_spec.group_values["lifecycle"] == folders_spec.group_values["lifecycle"]

    def test_a_documentation_vocabulary_is_optional(self):
        """Prose by default; a standard may still close one field's value
        set without making it a grouping field."""
        spec, issues = spec_for('''
[paths.doc]
names = ["purpose", "review_cycle"]

[enums.doc.review_cycle]
annual = "x"
quarterly = "x"
''')
        assert issues == []
        assert spec.doc_values == {"review_cycle": frozenset({"annual", "quarterly"})}

    def test_a_grouping_field_with_no_vocabulary_warns_but_still_groups(self):
        spec, issues = spec_for('[paths.group]\nnames = ["lifecycle"]\n')
        assert "enums.group.lifecycle" in locations(issues, "warning")
        assert spec.group_names == ("lifecycle",)


class TestNamespacesAreIndependent:

    def test_folders_reads_its_own_field_lists(self):
        spec, issues = spec_for('''
[paths.doc]
names = ["purpose", "notes"]

[folders.doc]
names = ["purpose"]
''', namespace="folders")
        assert issues == []
        assert spec.doc_names == ("purpose",)

    def test_folders_has_no_control_fields(self):
        """A reserved NAME isn't one location, so neither control field has
        anything to apply to."""
        spec, _ = spec_for("[folders]\n", namespace="folders")
        assert spec.control_names == ()
        assert CONTROL_FIELDS["folders"] == ()


class TestDeclarationErrors:

    def test_names_must_be_a_list_of_strings(self):
        _, issues = spec_for('[paths.doc]\nnames = "purpose"\n')
        assert "paths.doc.names" in locations(issues)

    def test_required_must_name_a_declared_field(self):
        spec, issues = spec_for('''
[paths.doc]
names = ["purpose"]
required = ["notes"]
''')
        assert "paths.doc.required" in locations(issues)
        assert spec.required(DOC) == frozenset()

    def test_multi_must_name_a_declared_grouping_field(self):
        _, issues = spec_for('''
[paths.group]
names = ["lifecycle"]
multi = ["origin"]
''')
        assert "paths.group.multi" in locations(issues)

    def test_a_control_field_cant_be_redeclared_as_documentation(self):
        _, issues = spec_for('[paths.doc]\nnames = ["purpose", "allow_missing"]\n')
        assert "paths.doc.names" in locations(issues)

    def test_a_control_field_cant_be_used_for_grouping(self):
        _, issues = spec_for('[paths.group]\nnames = ["outside_root"]\n')
        assert "paths.group.names" in locations(issues)

    def test_a_field_cant_be_both_documentation_and_grouping(self):
        """The two are read differently - one free-form, one against a
        closed vocabulary - so a name has to pick one."""
        _, issues = spec_for('''
[paths.doc]
names = ["lifecycle"]

[paths.group]
names = ["lifecycle"]
''')
        assert "paths.group.names" in locations(issues)

    def test_a_name_listed_twice_is_an_error(self):
        _, issues = spec_for('[paths.doc]\nnames = ["purpose", "purpose"]\n')
        assert "paths.doc.names" in locations(issues)


class TestSpecHelpers:

    def test_an_undeclared_spec_is_usable_as_a_default(self):
        """The validator holds one of these before it has parsed anything."""
        spec = FieldSpec("paths")
        assert not spec.is_declared()
        assert spec.names(DOC) == () and spec.names(GROUP) == ()
        assert spec.defaults == {}


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
