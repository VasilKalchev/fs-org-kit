"""
tests/test_param_refs.py - unit tests for fs_org_kit.param_refs

Run with: python -m pytest tests/test_param_refs.py -v
Or simply: python -m pytest tests/
"""

from fs_org_kit.param_refs import expand_param_value, expand_params, is_ref


class TestIsRef:

    def test_ref_table_is_a_ref(self):
        assert is_ref({"ref": "abbreviations"}) is True

    def test_plain_string_is_not_a_ref(self):
        assert is_ref("abbreviations") is False

    def test_plain_list_is_not_a_ref(self):
        assert is_ref(["a", "b"]) is False

    def test_extra_key_alongside_ref_is_not_a_ref(self):
        assert is_ref({"ref": "abbreviations", "extra": 1}) is False

    def test_non_string_ref_value_is_not_a_ref(self):
        assert is_ref({"ref": 123}) is False


class TestExpandParamValue:

    def test_non_ref_value_passes_through_unchanged(self):
        value, err = expand_param_value(["jpg", "png"], {})
        assert value == ["jpg", "png"]
        assert err is None

    def test_table_ref_expands_to_the_whole_table(self):
        """Substitution, not projection - the keys AND the values. The
        rule receiving it decides which half it wants."""
        data = {"abbreviations": {"arch": "Archive", "bkup": "Backup"}}
        value, err = expand_param_value({"ref": "abbreviations"}, data)
        assert value == {"arch": "Archive", "bkup": "Backup"}
        assert err is None

    def test_list_ref_expands_to_the_list_itself(self):
        data = {"some": {"nested": {"list": ["a", "b", "c"]}}}
        value, err = expand_param_value({"ref": "some.nested.list"}, data)
        assert value == ["a", "b", "c"]
        assert err is None

    def test_nested_table_ref_keeps_its_own_structure(self):
        """A tag namespace is the case this matters for: its vocabulary,
        its cardinality and its prose arrive as one object."""
        data = {"tags": {"state": {"multi": False, "values": {"complete": "done"}}}}
        value, err = expand_param_value({"ref": "tags.state"}, data)
        assert value == {"multi": False, "values": {"complete": "done"}}
        assert err is None

    def test_meta_keys_are_not_stripped_out(self):
        """[folders.reserved]'s `prefix` sits beside the entries and is
        passed straight through - deciding it isn't an entry is knowledge
        about that table, which belongs to the rule reading it, not here."""
        data = {
            "folders": {
                "reserved": {
                    "prefix": "_",
                    "_archive": {"purpose": "p", "lifecycle": "archival", "origin": ["self"]},
                }
            }
        }
        value, err = expand_param_value({"ref": "folders.reserved"}, data)
        assert value == data["folders"]["reserved"]
        assert "prefix" in value
        assert err is None

    def test_unresolvable_path_is_an_error(self):
        value, err = expand_param_value({"ref": "no.such.path"}, {})
        assert err is not None
        assert "no.such.path" in err

    def test_ref_to_a_scalar_resolves_to_that_scalar(self):
        for stored in ("~/usr/", 3, True):
            value, err = expand_param_value({"ref": "some_key"}, {"some_key": stored})
            assert value == stored
            assert err is None

    def test_partial_path_missing_is_an_error(self):
        data = {"abbreviations": {"arch": "Archive"}}
        value, err = expand_param_value({"ref": "abbreviations.nonexistent.deeper"}, data)
        assert err is not None


class TestExpandParams:

    def test_mixes_literal_and_ref_values(self):
        data = {"abbreviations": {"arch": "Archive"}}
        params = {"abbreviations": {"ref": "abbreviations"}, "language": ["en"]}
        expanded, errors = expand_params(params, data)
        assert expanded["abbreviations"] == {"arch": "Archive"}
        assert expanded["language"] == ["en"]
        assert errors == []

    def test_error_names_the_offending_param(self):
        params = {"cataloged": {"ref": "no.such.path"}}
        expanded, errors = expand_params(params, {})
        assert len(errors) == 1
        assert "`cataloged`" in errors[0]

    def test_empty_params_is_fine(self):
        expanded, errors = expand_params({}, {"abbreviations": {}})
        assert expanded == {}
        assert errors == []
