"""
tests/test_path_keys.py - unit tests for fs_org_kit.path_keys, plus the
validator/runner behavior that depends on it.

Run with: python -m pytest tests/test_path_keys.py -v
"""

import tomllib
from pathlib import Path

from fs_org_kit.path_keys import (
    OUTSIDE_ROOT_ATTR,
    comparison_key,
    escapes_root,
    is_absolute_key,
    resolve_key,
    walks_above_root,
)
from fs_org_kit.path_patterns import expand_pattern
from fs_org_kit.runner import collect_invocations
from fs_org_kit.validator import Validator, _index_source


class TestEscapeDetection:
    """The three routes out of root, and the things that only look like them."""

    def test_relative_key_stays_inside(self):
        assert not escapes_root("area/inv/")
        assert not is_absolute_key("area/inv/")

    def test_absolute_key_escapes(self):
        assert escapes_root("/etc/nginx/")
        assert is_absolute_key("/etc/nginx/")

    def test_home_relative_key_escapes(self):
        assert escapes_root("~/.config/")
        assert is_absolute_key("~/.config/")

    def test_dotdot_walking_up_escapes(self):
        assert escapes_root("../sibling/")
        assert walks_above_root("../sibling/")

    def test_dotdot_that_comes_back_down_does_not_escape(self):
        """"a/../b/" never leaves root, so it needs no flag."""
        assert not escapes_root("a/../b/")
        assert not walks_above_root("a/../b/")

    def test_dotdot_escaping_partway_through_is_caught(self):
        """Depth is tracked segment by segment, so a key that dips above
        root and returns is still an escape - it named a location outside
        root on the way."""
        assert walks_above_root("a/../../a/b/")

    def test_leading_dot_segment_is_not_an_escape(self):
        assert not escapes_root("./area/")

    def test_filename_containing_dots_is_not_an_escape(self):
        assert not escapes_root("area/..hidden/")
        assert not escapes_root("area/a..b/")


class TestResolveKey:
    """resolve_key is the only place a catalog key becomes a real path."""

    def test_relative_key_joins_onto_root(self, tmp_path):
        assert resolve_key(tmp_path, "area/inv/") == (tmp_path / "area/inv").resolve()

    def test_absolute_key_ignores_root(self, tmp_path):
        assert resolve_key(tmp_path, "/etc/nginx/") == Path("/etc/nginx")

    def test_home_relative_key_expands(self, tmp_path):
        assert resolve_key(tmp_path, "~/x/") == (Path.home() / "x").resolve()

    def test_plain_join_would_have_silently_discarded_root(self, tmp_path):
        """The accident outside_root exists to surface: Python's path join
        drops the left operand entirely when the right is absolute, so an
        absolute key was already 'working' - just pointing somewhere nobody
        declared."""
        assert (tmp_path / "/etc/nginx") == Path("/etc/nginx")

    def test_plain_join_would_not_have_expanded_tilde(self, tmp_path):
        """The other half of the accident: `~` isn't magic to pathlib, so
        a home-relative key used to resolve to a literal '~' directory
        under root."""
        assert (tmp_path / "~/x") != resolve_key(tmp_path, "~/x/")


class TestComparisonKey:
    """Normalization used for the validator's overlap check - disk-free."""

    def test_relative_and_absolute_lookalikes_are_distinct(self):
        assert comparison_key("etc/nginx/") != comparison_key("/etc/nginx/")

    def test_two_spellings_of_the_same_place_match(self):
        home = str(Path.home())
        assert comparison_key("~/x/") == comparison_key(f"{home}/x/")

    def test_trailing_slash_is_irrelevant(self):
        assert comparison_key("a/b/") == comparison_key("a/b")


# ---------------------------------------------------------------------
# Validator integration
# ---------------------------------------------------------------------

BOILERPLATE_HEAD = '''root = "~/usr/"

[meta]
schema_version = "2.0"
standard_version = "2.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"

[paths.doc]
names = ["purpose", "notes", "use_for", "not_for", "see_also"]
required = ["purpose"]

[paths.group]
names = ["lifecycle", "origin"]
multi = ["origin"]
required = ["lifecycle", "origin"]

[paths.rules]
allow_missing = false
'''

BOILERPLATE_TAIL = '''
[enums.group.lifecycle]
ongoing = "x"

[enums.group.origin]
self = "x"

[tags]
[abbreviations]
[folders]
[folders.doc]
names = []
[folders.reserved]
'''

ENTRY_DOC = '''purpose = "x"
notes = ""
use_for = ["x"]
not_for = [""]
see_also = ""
'''

ENTRY_GROUP = '''lifecycle = "ongoing"
origin = ["self"]
'''


def validate(standard_toml: str, tmp_path: Path):
    std_path = tmp_path / "test.toml"
    std_path.write_text(standard_toml)
    data = tomllib.loads(standard_toml)
    header_occurrences, key_lines = _index_source(standard_toml)
    validator = Validator(data, tmp_path, header_occurrences, key_lines)
    return validator.run(), validator


def entry(key: str, control: str = "") -> str:
    """One catalog entry in the three-table shape. `control` lands in the
    entry's `rules` table - that's where allow_missing/outside_root live."""
    block = f'\n[paths."{key}".doc]\n{ENTRY_DOC}\n[paths."{key}".group]\n{ENTRY_GROUP}'
    if control:
        block += f'\n[paths."{key}".rules]\n{control}'
    return block


def locations(issues, level="error"):
    return [i.location for i in issues if i.level == level]


class TestValidatorOutsideRoot:

    def test_absolute_key_without_the_flag_is_an_error(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("/etc/nginx/") + BOILERPLATE_TAIL, tmp_path)
        assert 'paths."/etc/nginx/"' in locations(issues)

    def test_absolute_key_with_the_flag_validates(self, tmp_path):
        issues, _ = validate(
            BOILERPLATE_HEAD + entry("/etc/nginx/", "outside_root = true\n") + BOILERPLATE_TAIL, tmp_path
        )
        assert locations(issues) == []

    def test_home_relative_key_needs_the_flag_too(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("~/.config/") + BOILERPLATE_TAIL, tmp_path)
        assert 'paths."~/.config/"' in locations(issues)

    def test_dotdot_key_needs_the_flag_too(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("../sibling/") + BOILERPLATE_TAIL, tmp_path)
        assert 'paths."../sibling/"' in locations(issues)

    def test_flag_on_an_inside_root_key_is_an_error(self, tmp_path):
        """A flag that claims something untrue about the entry is as much a
        defect as a missing one - it misleads the next reader."""
        issues, _ = validate(
            BOILERPLATE_HEAD + entry("area/inv/", "outside_root = true\n") + BOILERPLATE_TAIL, tmp_path
        )
        assert f'paths."area/inv/".rules.{OUTSIDE_ROOT_ATTR}' in locations(issues)

    def test_flag_must_be_a_boolean(self, tmp_path):
        issues, _ = validate(
            BOILERPLATE_HEAD + entry("/etc/nginx/", 'outside_root = "yes"\n') + BOILERPLATE_TAIL, tmp_path
        )
        assert f'paths."/etc/nginx/".rules.{OUTSIDE_ROOT_ATTR}' in locations(issues)

    def test_flag_cannot_arrive_through_inheritance(self, tmp_path):
        """The whole point of the flag is that escaping is deliberate at the
        escaping entry. Inheriting it would let an edit somewhere else widen
        what the tool walks into."""
        standard = (
            BOILERPLATE_HEAD
            + entry("/srv/a/", "outside_root = true\n")
            + entry("/srv/b/")
            + '\n[paths."/srv/b/".inherit]\nrules = "/srv/a/"\n'
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert f'paths."/srv/b/".rules.{OUTSIDE_ROOT_ATTR}' in locations(issues)

    def test_flag_cannot_arrive_from_attribute_defaults(self, tmp_path):
        head = BOILERPLATE_HEAD.replace(
            "allow_missing = false\n", "allow_missing = false\noutside_root = true\n"
        )
        issues, _ = validate(head + entry("/etc/nginx/") + BOILERPLATE_TAIL, tmp_path)
        assert f'paths."/etc/nginx/".rules.{OUTSIDE_ROOT_ATTR}' in locations(issues)

    def test_cross_entry_listing_an_outside_path_needs_the_flag(self, tmp_path):
        standard = (
            BOILERPLATE_HEAD
            + entry("area/a/")
            + '\n[[paths.cross]]\npaths = ["area/a/", "/etc/nginx/"]\n'
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert "paths.cross[0].paths" in locations(issues)

    def test_cross_entry_with_the_flag_validates(self, tmp_path):
        standard = (
            BOILERPLATE_HEAD
            + entry("area/a/")
            + '\n[[paths.cross]]\npaths = ["area/a/", "/etc/nginx/"]\n\n[paths.cross.rules]\noutside_root = true\n'
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert locations(issues) == []

    def test_cross_flag_with_no_outside_paths_is_an_error(self, tmp_path):
        standard = (
            BOILERPLATE_HEAD
            + entry("area/a/")
            + '\n[[paths.cross]]\npaths = ["area/a/", "area/b/"]\n\n[paths.cross.rules]\noutside_root = true\n'
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert f"paths.cross[0].rules.{OUTSIDE_ROOT_ATTR}" in locations(issues)


class TestValidatorOverlapAcrossTheRootBoundary:

    def test_inside_and_outside_lookalikes_do_not_collide(self, tmp_path):
        """"/srv/*/" and "srv/*/" name different places; flagging them as
        overlapping would be a false positive."""
        standard = (
            BOILERPLATE_HEAD
            + entry("/srv/*/", "outside_root = true\n")
            + entry("srv/*/")
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert locations(issues) == []

    def test_two_spellings_of_the_same_outside_place_still_collide(self, tmp_path):
        home = str(Path.home())
        standard = (
            BOILERPLATE_HEAD
            + entry("~/shared/*/", "outside_root = true\n")
            + entry(f"{home}/shared/*/", "outside_root = true\n")
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert locations(issues) != []


# ---------------------------------------------------------------------
# Runner integration
# ---------------------------------------------------------------------

class TestRunnerResolvesOutsideRootTargets:

    def test_absolute_target_is_found_where_it_actually_lives(self, tmp_path):
        """The directory exists outside root and nothing exists at the
        would-be joined location, so finding it proves resolve_key is being
        used rather than a plain join."""
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()

        std_text = BOILERPLATE_HEAD + entry(f"{outside}/", "outside_root = true\n") + BOILERPLATE_TAIL
        data = tomllib.loads(std_text)
        _, validator = validate(std_text, tmp_path)
        _, missing = collect_invocations(data, root, validator.rule_catalog, validator.resolved_paths)
        assert missing == []

    def test_absent_outside_root_target_is_reported_missing(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        gone = tmp_path / "not-there"

        std_text = BOILERPLATE_HEAD + entry(f"{gone}/", "outside_root = true\n") + BOILERPLATE_TAIL
        data = tomllib.loads(std_text)
        _, validator = validate(std_text, tmp_path)
        _, missing = collect_invocations(data, root, validator.rule_catalog, validator.resolved_paths)
        assert missing == [f"{gone}/"]

    def test_allow_missing_applies_outside_root_the_same_way(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        gone = tmp_path / "not-there"

        std_text = (
            BOILERPLATE_HEAD
            + entry(f"{gone}/", "outside_root = true\nallow_missing = true\n")
            + BOILERPLATE_TAIL
        )
        data = tomllib.loads(std_text)
        _, validator = validate(std_text, tmp_path)
        _, missing = collect_invocations(data, root, validator.rule_catalog, validator.resolved_paths)
        assert missing == []


class TestExpandPatternOutsideRoot:

    def test_absolute_pattern_globs_from_the_filesystem_anchor(self, tmp_path):
        """Path.glob refuses an absolute pattern outright, so expand_pattern
        has to split off the anchor itself."""
        for name in ("alpha", "beta"):
            (tmp_path / name).mkdir()
        (tmp_path / "not-a-dir.txt").write_text("x")

        matches = expand_pattern(Path("/nonexistent-root"), f"{tmp_path}/*/")
        assert matches == [tmp_path / "alpha", tmp_path / "beta"]

    def test_relative_pattern_still_globs_from_root(self, tmp_path):
        (tmp_path / "alpha").mkdir()
        assert expand_pattern(tmp_path, "*/") == [tmp_path / "alpha"]
