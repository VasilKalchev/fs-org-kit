"""
tests/test_inherit.py - unit tests for fs_org_kit.inherit

An entry is its attributes plus a `group` and a `rules` table, and each
part inherits from its own source, so these drive
`resolve_entries` with entries in exactly the shape the parsed TOML
produces.

Run with: python -m pytest tests/test_inherit.py -v
"""

import pytest

from fs_org_kit.inherit import resolve_entries


class TestBasicInheritance:
    """Field inheritance, with per-field override."""

    def test_full_inherit_with_override(self):
        raw = {
            "active/project-x/": {
                "purpose": "Project X, active",
                "group": {"lifecycle": "ongoing", "origin": ["self"]},
                "rules": {"staleness-v1": [{"reason": "flag if stale"}]},
            },
            "archive/project-x/": {
                "inherit": {
                    "attributes": "active/project-x/",
                    "group": "active/project-x/",
                    "rules": "active/project-x/",
                },
                "group": {"lifecycle": "archival"},   # overridden
            },
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []

        child = resolved["archive/project-x/"]
        assert child.attributes["purpose"] == "Project X, active"     # inherited
        assert child.group["lifecycle"] == "archival"          # overridden
        assert child.group["origin"] == ["self"]               # inherited
        assert "staleness-v1" in child.rules
        assert child.rules["staleness-v1"][0].origin_key == "active/project-x/"

    def test_each_part_inherits_only_from_its_own_source(self):
        """`attributes` and `group` are separate keys, so inheriting one
        brings nothing of the other."""
        raw = {
            "source/": {
                "purpose": "P",
                "group": {"lifecycle": "ongoing"},
            },
            "child/": {"inherit": {"attributes": "source/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        assert resolved["child/"].attributes["purpose"] == "P"
        assert resolved["child/"].group == {}

    def test_explicit_false_overrides_inherited_true(self):
        """A boolean False must be treated as an explicit override, not as unset -
        this is the trickiest edge case in the whole module."""
        raw = {
            "a/": {"purpose": "A", "group": {"flagged": True}},
            "b/": {"inherit": {"group": "a/"}, "group": {"flagged": False}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        assert resolved["b/"].group["flagged"] is False

    def test_purely_inherited_entry_has_no_own_fields(self):
        raw = {
            "source/": {"purpose": "The real one", "group": {"lifecycle": "ongoing"}},
            "pure/": {"inherit": {"attributes": "source/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        assert resolved["pure/"].attributes["purpose"] == "The real one"


class TestRuleInheritance:
    """inherit.rules, exclude_rules, and rule-stacking semantics."""

    def test_exclude_rules_drops_one_keeps_rest_stacks_own(self):
        raw = {
            "parent/": {
                "purpose": "P",
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
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        assert set(resolved["child/"].rules.keys()) == {"rule-a-v1", "rule-c-v1", "rule-d-v1"}

    def test_same_rule_inherited_and_declared_both_stack(self):
        raw = {
            "parent/": {"purpose": "P", "rules": {"rule-a-v1": [{"reason": "from parent"}]}},
            "child/": {"inherit": {"rules": "parent/"}, "rules": {"rule-a-v1": [{"reason": "from child"}]}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        instances = resolved["child/"].rules["rule-a-v1"]
        assert len(instances) == 2
        assert {i.instance["reason"] for i in instances} == {"from parent", "from child"}

    def test_fields_and_rules_can_inherit_from_different_sources(self):
        raw = {
            "attrs-source/": {"purpose": "P"},
            "rules-source/": {"purpose": "Q", "rules": {"rule-x-v1": [{"reason": "x"}]}},
            "child/": {"inherit": {"attributes": "attrs-source/", "rules": "rules-source/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert issues == []
        assert resolved["child/"].attributes["purpose"] == "P"
        assert "rule-x-v1" in resolved["child/"].rules


class TestErrorsAndCycles:

    def test_undefined_attributes_reference(self):
        raw = {"a/": {"inherit": {"attributes": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, "paths")
        assert len(issues) == 1
        assert issues[0].level == "error"
        assert "unknown paths key" in issues[0].message

    def test_undefined_rules_reference(self):
        raw = {"a/": {"inherit": {"rules": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, "paths")
        assert any("unknown paths key" in i.message for i in issues)

    def test_undefined_group_reference(self):
        raw = {"a/": {"inherit": {"group": "nonexistent/"}}}
        resolved, issues = resolve_entries(raw, "paths")
        assert any("unknown paths key" in i.message for i in issues)

    def test_two_level_cycle_detected(self):
        raw = {
            "a/": {"inherit": {"attributes": "b/"}},
            "b/": {"inherit": {"attributes": "a/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        cycle_issues = [i for i in issues if "cycle" in i.message]
        assert len(cycle_issues) >= 1

    def test_three_level_cycle_detected(self):
        raw = {
            "a/": {"inherit": {"attributes": "b/"}},
            "b/": {"inherit": {"attributes": "c/"}},
            "c/": {"inherit": {"attributes": "a/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        cycle_issues = [i for i in issues if "cycle" in i.message]
        assert len(cycle_issues) >= 1

    def test_a_cycle_in_one_part_doesnt_stop_the_others(self):
        raw = {
            "a/": {"purpose": "A", "inherit": {"group": "b/"}},
            "b/": {"inherit": {"group": "a/"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert any("cycle" in i.message for i in issues)
        assert resolved["a/"].attributes["purpose"] == "A"

    def test_broken_reference_isolated_to_one_entry(self):
        """A bad inherit reference on one entry must not prevent every
        other entry from resolving normally."""
        raw = {
            "broken/": {"group": {"lifecycle": "ongoing"}, "inherit": {"attributes": "nonexistent/"}},
            "fine/": {"purpose": "Fine", "group": {"lifecycle": "ongoing"}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        assert "fine/" in resolved
        assert resolved["fine/"].attributes["purpose"] == "Fine"
        assert any(i.key == "broken/" for i in issues)

    def test_exclude_rules_without_inherit_rules_is_error(self):
        raw = {"a/": {"inherit": {"exclude_rules": ["x-v1"]}}}
        resolved, issues = resolve_entries(raw, "paths")
        assert any("nothing to exclude from" in i.message for i in issues)

    def test_exclude_rules_referencing_non_inherited_rule_is_warning(self):
        raw = {
            "parent/": {"purpose": "P", "rules": {"rule-a-v1": [{"reason": "a"}]}},
            "child/": {"inherit": {"rules": "parent/", "exclude_rules": ["rule-nonexistent-v1"]}},
        }
        resolved, issues = resolve_entries(raw, "paths")
        warnings = [i for i in issues if i.level == "warning"]
        assert len(warnings) == 1
        assert "no effect" in warnings[0].message


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
