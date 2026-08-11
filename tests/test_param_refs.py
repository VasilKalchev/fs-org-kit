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

    def test_table_ref_expands_to_sorted_keys(self):
        data = {"abbreviations": {"arch": "Archive", "bkup": "Backup"}}
        value, err = expand_param_value({"ref": "abbreviations"}, data)
        assert set(value) == {"arch", "bkup"}
        assert err is None

    def test_list_ref_expands_to_the_list_itself(self):
        data = {"some": {"nested": {"list": ["a", "b", "c"]}}}
        value, err = expand_param_value({"ref": "some.nested.list"}, data)
        assert value == ["a", "b", "c"]
        assert err is None

    def test_folders_reserved_excludes_the_prefix_meta_key(self):
        data = {
            "folders": {
                "reserved": {
                    "prefix": "_",
                    "_archive": {"purpose": "p", "lifecycle": "archival", "origin": ["self"]},
                    "_inbox": {"purpose": "p", "lifecycle": "transient", "origin": ["self"]},
                }
            }
        }
        value, err = expand_param_value({"ref": "folders.reserved"}, data)
        assert set(value) == {"_archive", "_inbox"}
        assert "prefix" not in value
        assert err is None

    def test_unresolvable_path_is_an_error(self):
        value, err = expand_param_value({"ref": "no.such.path"}, {})
        assert err is not None
        assert "no.such.path" in err

    def test_ref_to_a_scalar_is_an_error(self):
        data = {"root": "~/usr/"}
        value, err = expand_param_value({"ref": "root"}, data)
        assert err is not None
        assert "not a table or list" in err

    def test_partial_path_missing_is_an_error(self):
        data = {"abbreviations": {"arch": "Archive"}}
        value, err = expand_param_value({"ref": "abbreviations.nonexistent.deeper"}, data)
        assert err is not None


class TestExpandParams:

    def test_mixes_literal_and_ref_values(self):
        data = {"abbreviations": {"arch": "Archive"}}
        params = {"abbreviations": {"ref": "abbreviations"}, "language": ["en"]}
        expanded, errors = expand_params(params, data)
        assert expanded["abbreviations"] == ["arch"]
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
