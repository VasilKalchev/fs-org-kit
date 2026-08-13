"""
tests/test_doc.py - unit tests for fs_org_kit.doc

Run with: python -m pytest tests/test_doc.py -v
"""

import re
from pathlib import Path

import pytest

from fs_org_kit.doc import main, slug_for

from conftest import minimal_meta

BOILERPLATE = 'root = "{root}/"\n\n' + minimal_meta() + '''
[paths.attributes]
names = ["purpose", "notes", "use_for", "see_also"]
required = ["purpose"]


[paths.attributes.group]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle", "origin"]

{body}

[enums.group.lifecycle]
transient = "x"
temporary = "x"
ongoing = "x"
archival = "x"
[enums.group.origin]
self = "x"
external = "x"
[tags]
[abbreviations]
[folders.attributes]
names = []
[folders.reserved]
'''


def write_standard(tmp_path, body: str) -> "Path":
    std = tmp_path / "fs-org-std.toml"
    std.write_text(BOILERPLATE.format(root=tmp_path, body=body))
    return std


class TestSlugFor:
    """slug_for() must reproduce exactly what a renderer computes from a
    heading's visible text - a mismatch here means a ToC link silently
    stops working. Backticks are code-span syntax, not rendered text."""

    def test_basic(self):
        assert slug_for("Hello World") == "hello%20world"

    def test_backticks_stripped_slash_kept(self):
        assert slug_for("`area/`") == "area/"

    def test_case_folded(self):
        assert slug_for("`Downloads/`") == "downloads/"


class TestValidateFirst:

    def test_invalid_standard_exits_two(self, tmp_path):
        bad = tmp_path / "fs-org-std.toml"
        bad.write_text("this is not valid { toml")
        assert main([str(bad)]) == 2

    def test_missing_file_exits_two(self, tmp_path):
        assert main([str(tmp_path / "nonexistent.toml")]) == 2

    def test_validation_error_blocks_generation(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[[paths."x/".rules.nonexistent-rule-v1]]
reason = "r"
''')
        exit_code = main([str(std)])
        assert exit_code == 2
        captured = capsys.readouterr()
        assert "validation error" in captured.err

    def test_warnings_do_not_block(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a"]
purpose = "A"

[paths."a".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        exit_code = main([str(std)])
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "validation warning" in captured.err
        assert "# " in captured.out  # doc still generated to stdout


class TestSections:

    def _std(self, tmp_path):
        return write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')

    def test_default_includes_all_present_sections(self, tmp_path, capsys):
        main([str(self._std(tmp_path))])
        out = capsys.readouterr().out
        assert "## Overview" in out
        assert "## Paths" in out

    def test_empty_sections_omitted(self, tmp_path, capsys):
        """No paths.cross in the fixture - the section shouldn't appear at all."""
        main([str(self._std(tmp_path))])
        out = capsys.readouterr().out
        assert "## Cross-Path Sets" not in out
        assert "## Tags" not in out  # empty [tags] table


class TestTagsSection:
    """Tag namespaces render like the enums they resemble. What they
    never render is a value something on disk currently carries - the
    standard doesn't know one."""

    def _std(self, tmp_path, tags_toml: str):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        std.write_text(std.read_text() + tags_toml)
        return std

    def _render(self, tmp_path, capsys, tags_toml: str) -> str:
        main([str(self._std(tmp_path, tags_toml))])
        return capsys.readouterr().out

    def test_a_namespace_renders_its_values(self, tmp_path, capsys):
        out = self._render(tmp_path, capsys, '''
[tags.state]
description = "Where a unit of work stands."
multi = false

[tags.state.values]
abandoned = "stopped deliberately"
complete = "finished"
''')
        assert "## Tags" in out
        assert "**`tags.state`:**" in out
        assert "Where a unit of work stands." in out
        assert "| `abandoned` | stopped deliberately |" in out
        assert "| `complete` | finished |" in out

    def test_cardinality_is_stated(self, tmp_path, capsys):
        single = self._render(tmp_path, capsys, '''
[tags.state]
multi = false
[tags.state.values]
complete = "finished"
''')
        assert "Exactly one value applies at a time." in single

    def test_multi_valued_namespace_says_so(self, tmp_path, capsys):
        multi = self._render(tmp_path, capsys, '''
[tags.topic]
multi = true
[tags.topic.values]
python = "about Python"
''')
        assert "Multiple values may apply at once." in multi

    def test_several_namespaces_each_get_a_table(self, tmp_path, capsys):
        out = self._render(tmp_path, capsys, '''
[tags.priority.values]
high = "now"

[tags.state.values]
complete = "finished"
''')
        assert "**`tags.priority`:**" in out
        assert "**`tags.state`:**" in out

    def test_empty_tags_table_emits_no_section(self, tmp_path, capsys):
        assert "## Tags" not in self._render(tmp_path, capsys, "")


class TestTableOfContents:

    def test_toc_present_by_default(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        assert "Table of Contents" in capsys.readouterr().out

    def test_paths_nest_by_depth_and_show_only_the_leaf(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."a/b/"]
purpose = "AB"

[paths."a/b/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."a/b/c/"]
purpose = "ABC"

[paths."a/b/c/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "  - [`a/`](#a/)" in out
        assert "    - [`b/`](#a/b/)" in out
        assert "      - [`c/`](#a/b/c/)" in out
        toc, _, _ = out.partition("## Paths")
        assert "[`a/b/c/`]" not in toc

    def test_every_link_resolves_to_a_real_heading(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."a/".rules.file-extensions-v1]]
reason = "r"

[paths."a/".rules.file-extensions-v1.params]
allowed = ["jpg"]
''')
        rules_dir = Path(__file__).resolve().parent.parent / "rules"
        exit_code = main([str(std), "--rules-dir", str(rules_dir)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert len(out) > 0
        headings = re.findall(r"^#{2,3} (.+)$", out, re.MULTILINE)
        heading_slugs = {slug_for(h) for h in headings}
        links = set(re.findall(r"\]\(#([^)]+)\)", out))
        assert links, "expected at least one link to actually test something"
        assert links <= heading_slugs


class TestAttributeTable:
    """The renderer knows no field names - it renders whatever the
    standard declared, in the shape the value actually has."""

    def test_list_valued_field_becomes_bullets_not_a_repr(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
see_also = ["b/", "c/"]

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."b/"]
purpose = "B"

[paths."b/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "**See also:**" in out
        assert "- b/" in out and "- c/" in out
        assert "['b/'" not in out

    def test_string_valued_field_becomes_a_table_row(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
see_also = "b/"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        assert "| See also | b/ |" in capsys.readouterr().out

    def test_field_of_only_empty_strings_is_omitted(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
see_also = [""]

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        assert "See also" not in capsys.readouterr().out

    def test_an_undeclared_field_name_is_not_rendered(self, tmp_path, capsys):
        """The declaration drives rendering, so a field the namespace never
        declared (already a validator warning) can't appear in the docs."""
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
undeclared = "should not be rendered"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        assert "should not be rendered" not in capsys.readouterr().out

    def test_a_grouping_field_links_to_its_vocabulary(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "| Lifecycle | [`ongoing`](#enums) |" in out


class TestInheritanceRendering:

    def test_inherited_field_shown_at_its_resolved_value(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."active/x/"]
purpose = "Active X"

[paths."active/x/".group]
lifecycle = "ongoing"
origin = ["self"]

[paths."archive/x/".group]
lifecycle = "archival"

[paths."archive/x/".inherit]
attributes = "active/x/"
group = "active/x/"
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "Active X" in out


class TestRuleReverseIndex:

    def test_rule_lists_every_attachment_site(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."a/".rules.file-extensions-v1]]
reason = "reason A"

[paths."a/".rules.file-extensions-v1.params]
allowed = ["jpg"]

[paths."b/"]
purpose = "B"

[paths."b/".group]
lifecycle = "ongoing"
origin = ["self"]

[[paths."b/".rules.file-extensions-v1]]
reason = "reason B"

[paths."b/".rules.file-extensions-v1.params]
allowed = ["png"]
''')
        exit_code = main([str(std)])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "reason A" in out
        assert "reason B" in out
        assert "Attached at 2 location" in out


class TestNoEmDashes:

    def test_generated_output_has_no_em_dashes(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"

[paths."a/".group]
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "\u2014" not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
