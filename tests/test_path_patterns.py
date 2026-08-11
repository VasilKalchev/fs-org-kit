"""
tests/test_path_patterns.py - unit tests for fs_org_kit.path_patterns

Run with: python -m pytest tests/test_path_patterns.py -v
Or simply: python -m pytest tests/
"""

from pathlib import Path

from fs_org_kit.path_patterns import expand_pattern, is_pattern, patterns_may_overlap


class TestIsPattern:

    def test_literal_path_is_not_a_pattern(self):
        assert is_pattern("media/img/") is False

    def test_star_is_a_pattern(self):
        assert is_pattern("folder-a/*/some-folder/") is True

    def test_doublestar_is_a_pattern(self):
        assert is_pattern("projects/**/archive/") is True

    def test_question_mark_is_a_pattern(self):
        assert is_pattern("client-?/") is True

    def test_char_class_is_a_pattern(self):
        assert is_pattern("folder-b/folder[1-3]/") is True


class TestPatternsMayOverlapFixedLength:

    def test_two_distinct_literals_never_overlap(self):
        assert patterns_may_overlap("a/b/", "a/c/") is False

    def test_different_segment_counts_never_overlap(self):
        assert patterns_may_overlap("a/b/", "a/b/c/") is False

    def test_wildcard_segment_vs_matching_literal_overlaps(self):
        assert patterns_may_overlap("folder-a/*/some-folder/", "folder-a/x/some-folder/") is True

    def test_wildcard_segment_vs_non_matching_literal_prefix_no_overlap(self):
        assert patterns_may_overlap("folder-a/*/some-folder/", "folder-z/x/some-folder/") is False

    def test_two_patterns_with_compatible_wildcards_overlap(self):
        assert patterns_may_overlap("a/*/c/", "a/b/*/") is True

    def test_char_class_vs_char_class_conservatively_overlaps(self):
        """Known, documented approximation: [abc] and [xyz] can never
        actually share a character, but this is intentionally not
        proven - conservative means "may overlap", not "definitely
        does"."""
        assert patterns_may_overlap("folder-b/folder[1-3]/", "folder-b/folder[7-9]/") is True

    def test_identical_key_overlaps_with_itself(self):
        assert patterns_may_overlap("a/*/", "a/*/") is True


class TestPatternsMayOverlapDoubleStar:

    def test_doublestar_vs_different_literal_root_no_overlap(self):
        assert patterns_may_overlap("a/*/b/", "c/**") is False

    def test_doublestar_vs_matching_prefix_overlaps(self):
        assert patterns_may_overlap("a/x/**", "a/*/b/") is True

    def test_two_doublestars_with_same_prefix_overlap(self):
        assert patterns_may_overlap("projects/**/archive/", "projects/**/old/") is True

    def test_two_doublestars_with_different_prefixes_no_overlap(self):
        assert patterns_may_overlap("projects/**/archive/", "media/**/archive/") is False


class TestExpandPattern:

    def test_matches_only_directories(self, tmp_path):
        (tmp_path / "folder-a" / "one" / "some-folder").mkdir(parents=True)
        (tmp_path / "folder-a" / "two" / "some-folder").mkdir(parents=True)
        (tmp_path / "folder-a" / "not-a-dir.txt").write_text("x")
        matches = expand_pattern(tmp_path, "folder-a/*/some-folder/")
        assert matches == sorted(matches)
        assert len(matches) == 2
        assert all(m.is_dir() for m in matches)

    def test_no_matches_returns_empty_list(self, tmp_path):
        assert expand_pattern(tmp_path, "nothing-here/*/") == []

    def test_char_class_range(self, tmp_path):
        (tmp_path / "folder-b" / "folder1").mkdir(parents=True)
        (tmp_path / "folder-b" / "folder2").mkdir(parents=True)
        (tmp_path / "folder-b" / "folder9").mkdir(parents=True)
        matches = expand_pattern(tmp_path, "folder-b/folder[1-3]/")
        assert [m.name for m in matches] == ["folder1", "folder2"]

    def test_doublestar_matches_any_depth(self, tmp_path):
        (tmp_path / "projects" / "x" / "archive").mkdir(parents=True)
        (tmp_path / "projects" / "y" / "z" / "archive").mkdir(parents=True)
        matches = expand_pattern(tmp_path, "projects/**/archive/")
        assert len(matches) == 2
