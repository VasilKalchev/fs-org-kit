"""
tests/test_inherit.py - unit tests for fs_org_kit.inherit

An entry is three tables (doc / group / rules) and each inherits from its
own source, so these drive `resolve_entries` with entries in exactly the
shape the parsed TOML produces.

Run with: python -m pytest tests/test_inherit.py -v
"""

import pytest

from fs_org_kit.inherit import resolve_entries

CONTROL = ("allow_missing", "outside_root")
NO_DEFAULTS: dict[str, dict] = {}
ALLOW_MISSING_FALSE = {"rules": {"allow_missing": False}}


class TestBasicInheritance:
    """Field inheritance with per-field override, and standard-wide defaults."""

    def test_full_inherit_with_override_and_defaults(self):
        raw = {
            "active/project-x/": {
                "doc": {"purpose": "Project X, active"},
                "group": {"lifecycle": "ongoing", "origin": ["self"]},
                "rules": {"staleness-v1": [{"reason": "flag if stale"}]},
            },
            "archive/project-x/": {
                "inherit": {
                    "doc": "active/project-x/",
                    "group": "active/project-x/",
                    "rules": "active/project-x/",
                },
                "group": {"lifecycle": "archival"},   # overridden
                "rules": {"allow_missing": True},
            },
        }
        resolved, issues = resolve_entries(raw, ALLOW_MISSING_FALSE, "paths", CONTROL)
        assert issues == []

        child = resolved["archive/project-x/"]
        assert child.doc["purpose"] == "Project X, active"     # inherited
        assert child.group["lifecycle"] == "archival"          # overridden
        assert child.group["origin"] == ["self"]               # inherited
        assert child.control["allow_missing"] is True          # own explicit value
        assert "staleness-v1" in child.rules
        assert child.rules["staleness-v1"][0].origin_key == "active/project-x/"

        parent = resolved["active/project-x/"]
        assert parent.control["allow_missing"] is False        # standard-wide default applied

    def test_each_table_inherits_only_from_its_own_source(self):
        """`doc` and `group` are separate keys, so inheriting one brings
        nothing of the other."""
        raw = {
            "source/": {
                "doc": {"purpose": "P"},
                "group": {"lifecycle": "ongoing"},
            },
            "child/": {"inherit": {"doc": "source/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        assert resolved["child/"].doc["purpose"] == "P"
        assert resolved["child/"].group == {}

    def test_explicit_false_overrides_inherited_true(self):
        """A boolean False must be treated as an explicit override, not as unset -
        this is the trickiest edge case in the whole module."""
        raw = {
            "a/": {"doc": {"purpose": "A"}, "rules": {"allow_missing": True}},
            "b/": {"inherit": {"rules": "a/"}, "rules": {"allow_missing": False}},
        }
        resolved, issues = resolve_entries(raw, ALLOW_MISSING_FALSE, "paths", CONTROL)
        assert issues == []
        assert resolved["b/"].control["allow_missing"] is False

    def test_purely_inherited_entry_has_no_own_fields(self):
        raw = {
            "source/": {"doc": {"purpose": "The real one"}, "group": {"lifecycle": "ongoing"}},
            "pure/": {"inherit": {"doc": "source/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        assert resolved["pure/"].doc["purpose"] == "The real one"


class TestRuleInheritance:
    """inherit.rules, exclude_rules, and rule-stacking semantics."""

    def test_control_fields_are_not_mistaken_for_attachments(self):
        """A control field shares the `rules` table with the attachments,
        and must never reach the resolved rule set."""
        raw = {"a/": {"rules": {"allow_missing": True, "rule-a-v1": [{"reason": "a"}]}}}
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        assert set(resolved["a/"].rules) == {"rule-a-v1"}
        assert resolved["a/"].control == {"allow_missing": True}

    def test_exclude_rules_drops_one_keeps_rest_stacks_own(self):
        raw = {
            "parent/": {
                "doc": {"purpose": "P"},
                "rules": {
                    "rule-a-v1": [{"reason": "a"}],
                    "rule-b-v1": [{"reason": "b"}],
                    "rule-c-v1": [{"reason": "c"}],
                },
            },
            "child/": {
                "inherit": {"rules": "parent/", "exclude_rules": ["rule-b-v1"]},
                "rules": {"rule-d-v1": [{"reason": "d"}]},
            },
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        assert set(resolved["child/"].rules.keys()) == {"rule-a-v1", "rule-c-v1", "rule-d-v1"}

    def test_same_rule_inherited_and_declared_both_stack(self):
        raw = {
            "parent/": {"doc": {"purpose": "P"}, "rules": {"rule-a-v1": [{"reason": "from parent"}]}},
            "child/": {"inherit": {"rules": "parent/"}, "rules": {"rule-a-v1": [{"reason": "from child"}]}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        instances = resolved["child/"].rules["rule-a-v1"]
        assert len(instances) == 2
        assert {i.instance["reason"] for i in instances} == {"from parent", "from child"}

    def test_fields_and_rules_can_inherit_from_different_sources(self):
        raw = {
            "doc-source/": {"doc": {"purpose": "P"}},
            "rules-source/": {"doc": {"purpose": "Q"}, "rules": {"rule-x-v1": [{"reason": "x"}]}},
            "child/": {"inherit": {"doc": "doc-source/", "rules": "rules-source/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert issues == []
        assert resolved["child/"].doc["purpose"] == "P"
        assert "rule-x-v1" in resolved["child/"].rules


class TestErrorsAndCycles:

    def test_undefined_doc_reference(self):
        raw = {"a/": {"inherit": {"doc": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert "unknown paths key" in issues[0].message

    def test_undefined_rules_reference(self):
        raw = {"a/": {"inherit": {"rules": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert any("unknown paths key" in i.message for i in issues)

    def test_undefined_group_reference(self):
        raw = {"a/": {"inherit": {"group": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert any("unknown paths key" in i.message for i in issues)

    def test_two_level_cycle_detected(self):
        raw = {
            "a/": {"inherit": {"doc": "b/"}},
            "b/": {"inherit": {"doc": "a/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        cycle_issues = [i for i in issues if "cycle" in i.message]
        assert len(cycle_issues) >= 1

    def test_three_level_cycle_detected(self):
        raw = {
            "a/": {"inherit": {"doc": "b/"}},
            "b/": {"inherit": {"doc": "c/"}},
            "c/": {"inherit": {"doc": "a/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        cycle_issues = [i for i in issues if "cycle" in i.message]
        assert len(cycle_issues) >= 1

    def test_a_cycle_in_one_table_doesnt_stop_the_others(self):
        raw = {
            "a/": {"doc": {"purpose": "A"}, "inherit": {"group": "b/"}},
            "b/": {"inherit": {"group": "a/"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert any("cycle" in i.message for i in issues)
        assert resolved["a/"].doc["purpose"] == "A"

    def test_broken_reference_isolated_to_one_entry(self):
        """A bad inherit reference on one entry must not prevent every
        other entry from resolving normally."""
        raw = {
            "broken/": {"group": {"lifecycle": "ongoing"}, "inherit": {"doc": "nonexistent/"}},
            "fine/": {"doc": {"purpose": "Fine"}, "group": {"lifecycle": "ongoing"}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert "fine/" in resolved
        assert resolved["fine/"].doc["purpose"] == "Fine"
        assert any(i.key == "broken/" for i in issues)

    def test_exclude_rules_without_inherit_rules_is_error(self):
        raw = {"a/": {"inherit": {"exclude_rules": ["x-v1"]}}}
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        assert any("nothing to exclude from" in i.message for i in issues)

    def test_exclude_rules_referencing_non_inherited_rule_is_warning(self):
        raw = {
            "parent/": {"doc": {"purpose": "P"}, "rules": {"rule-a-v1": [{"reason": "a"}]}},
            "child/": {"inherit": {"rules": "parent/", "exclude_rules": ["rule-nonexistent-v1"]}},
        }
        resolved, issues = resolve_entries(raw, NO_DEFAULTS, "paths", CONTROL)
        warnings = [i for i in issues if i.level == "warning"]
        assert len(warnings) == 1
        assert "no effect" in warnings[0].message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
