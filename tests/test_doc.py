"""
tests/test_doc.py - unit tests for fs_org_kit.doc

Run with: python -m pytest tests/test_doc.py -v
"""

import re
from pathlib import Path

import pytest

from fs_org_kit.doc import _format_value, _slugify, main


BOILERPLATE = '''root = "{root}/"

[meta]
schema_version = "1.0"
schema_date = "2026-01-01"
standard_version = "1.0"
standard_date = "2026-01-01"

[paths.attributes]
names = ["purpose", "notes", "lifecycle", "origin", "allow_missing"]
[paths.attributes.defaults]
allow_missing = false

{body}

[enums.paths.lifecycle]
transient = "x"
temporary = "x"
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


def write_standard(tmp_path, body: str) -> "Path":
    std = tmp_path / "fs-org-std.toml"
    std.write_text(BOILERPLATE.format(root=tmp_path, body=body))
    return std


class TestSlugify:

    def test_basic(self):
        assert _slugify("Hello World") == "hello-world"

    def test_slashes_become_hyphens(self):
        assert _slugify("active/project-x/") == "active-project-x"

    def test_special_chars_stripped(self):
        assert _slugify('weird[name]"quoted"') == "weirdnamequoted"

    def test_empty_falls_back(self):
        assert _slugify("") == "section"
        assert _slugify("///") == "section"


class TestFormatValue:

    def test_booleans_are_lowercase(self):
        assert _format_value(True) == "true"
        assert _format_value(False) == "false"

    def test_strings_quoted(self):
        assert _format_value("hello") == '"hello"'
        assert _format_value("") == '""'

    def test_lists(self):
        assert _format_value(["a", "b"]) == '["a", "b"]'
        assert _format_value([]) == "[]"


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
[paths."z/"]
purpose = "Z"
lifecycle = "ongoing"
origin = ["self"]

[paths."a/"]
purpose = "A"
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
lifecycle = "ongoing"
origin = ["self"]
''')

    def test_default_includes_all_present_sections(self, tmp_path, capsys):
        main([str(self._std(tmp_path))])
        out = capsys.readouterr().out
        assert "## Overview" in out
        assert "## Paths" in out

    def test_sections_filter(self, tmp_path, capsys):
        main([str(self._std(tmp_path)), "--sections", "overview"])
        out = capsys.readouterr().out
        assert "## Overview" in out
        assert "## Paths" not in out

    def test_exclude_sections(self, tmp_path, capsys):
        main([str(self._std(tmp_path)), "--exclude-sections", "overview"])
        out = capsys.readouterr().out
        assert "## Overview" not in out
        assert "## Paths" in out

    def test_unknown_section_errors(self, tmp_path, capsys):
        exit_code = main([str(self._std(tmp_path)), "--sections", "bogus"])
        assert exit_code == 2
        assert "unknown value" in capsys.readouterr().err

    def test_empty_sections_omitted(self, tmp_path, capsys):
        """No paths.cross in the fixture - the section shouldn't appear at all."""
        main([str(self._std(tmp_path))])
        out = capsys.readouterr().out
        assert "## Cross-Path Sets" not in out
        assert "## Tags" not in out  # empty [tags] table


class TestDiagrams:

    def _std_with_paths(self, tmp_path):
        return write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]

[paths."a/aa/"]
purpose = "AA"
lifecycle = "ongoing"
origin = ["self"]
''')

    def test_no_diagrams_flag(self, tmp_path, capsys):
        main([str(self._std_with_paths(tmp_path)), "--no-diagrams"])
        out = capsys.readouterr().out
        assert "```mermaid" not in out

    def test_diagrams_filter(self, tmp_path, capsys):
        main([str(self._std_with_paths(tmp_path)), "--diagrams", "tree"])
        out = capsys.readouterr().out
        assert out.count("```mermaid") == 1

    def test_tree_reflects_nesting(self, tmp_path, capsys):
        main([str(self._std_with_paths(tmp_path)), "--sections", "overview", "--diagrams", "tree"])
        out = capsys.readouterr().out
        assert 'n0["a/"]' in out or 'n1["a/"]' in out
        assert "-->" in out

    def test_node_limit_guard(self, tmp_path, capsys):
        body_parts = []
        for i in range(45):
            body_parts.append(f'[paths."item{i}/"]\npurpose = "x"\nlifecycle = "ongoing"\norigin = ["self"]\n')
        std = write_standard(tmp_path, "\n".join(body_parts))
        main([str(std), "--sections", "overview"])
        out = capsys.readouterr().out
        assert "```mermaid" not in out
        assert "skipped" in out

    def test_lifecycle_diagram_only_for_known_vocabulary(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std), "--sections", "enums", "--diagrams", "lifecycle"])
        out = capsys.readouterr().out
        # BOILERPLATE's lifecycle enum matches the known vocabulary exactly
        assert "```mermaid" in out

    def test_mermaid_special_chars_sanitized(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."weird[name]/"]
purpose = "has \\"quotes\\" and [brackets]"
lifecycle = "ongoing"
origin = ["self"]
''')
        exit_code = main([str(std), "--sections", "overview", "--diagrams", "tree"])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "```mermaid" in out
        start = out.index("```mermaid")
        end = out.index("```", start + 3)
        mermaid_block = out[start:end]
        # a raw " or [ inside a node's ["label"] would break mermaid's own
        # syntax - check node-label lines specifically, not the whole
        # block (the block legitimately contains [" and "] as delimiters)
        node_lines = [line for line in mermaid_block.splitlines() if '["' in line]
        assert node_lines, "expected at least one node label line to check"
        for line in node_lines:
            label = line.split('["', 1)[1].rsplit('"]', 1)[0]
            assert '"' not in label
            assert "[" not in label and "]" not in label


class TestTableOfContents:

    def test_toc_present_by_default(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        assert "Table of Contents" in capsys.readouterr().out

    def test_no_toc_flag(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std), "--no-toc"])
        assert "Table of Contents" not in capsys.readouterr().out

    def test_every_link_has_a_matching_anchor(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
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
        anchors = set(re.findall(r'<a id="([^"]+)"></a>', out))
        links = set(re.findall(r"\]\(#([^)]+)\)", out))
        assert links, "expected at least one link to actually test something"
        assert links <= anchors


class TestInheritanceRendering:

    def test_inherited_field_shown_and_marked(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."active/x/"]
purpose = "Active X"
lifecycle = "ongoing"
origin = ["self"]

[paths."archive/x/"]
lifecycle = "archival"

[paths."archive/x/".inherit]
attributes = "active/x/"
''')
        main([str(std), "--sections", "paths"])
        out = capsys.readouterr().out
        assert "Active X" in out
        assert "inherited from" in out


class TestRuleReverseIndex:

    def test_rule_lists_every_attachment_site(self, tmp_path, capsys):
        std = write_standard(tmp_path, '''
[paths."a/"]
purpose = "A"
lifecycle = "ongoing"
origin = ["self"]

[[paths."a/".rules.file-extensions-v1]]
reason = "reason A"

[paths."a/".rules.file-extensions-v1.params]
allowed = ["jpg"]

[paths."b/"]
purpose = "B"
lifecycle = "ongoing"
origin = ["self"]

[[paths."b/".rules.file-extensions-v1]]
reason = "reason B"

[paths."b/".rules.file-extensions-v1.params]
allowed = ["png"]
''')
        exit_code = main([str(std), "--sections", "rules"])
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
lifecycle = "ongoing"
origin = ["self"]
''')
        main([str(std)])
        out = capsys.readouterr().out
        assert "\u2014" not in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
