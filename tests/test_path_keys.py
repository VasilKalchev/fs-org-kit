"""
tests/test_path_keys.py - unit tests for fs_org_kit.path_keys, plus the
validator/runner behavior that depends on it.

Run with: python -m pytest tests/test_path_keys.py -v
"""

import tomllib
from pathlib import Path

from fs_org_kit.path_keys import comparison_key, is_absolute_key, is_home_relative, resolve_key
from fs_org_kit.path_patterns import expand_pattern
from fs_org_kit.runner import collect_invocations
from fs_org_kit.validator import Validator, _index_source


class TestKeyShape:

    def test_a_relative_key_is_not_absolute(self):
        assert not is_absolute_key("area/inv/")

    def test_a_leading_slash_is_absolute(self):
        assert is_absolute_key("/etc/nginx/")

    def test_a_tilde_key_is_absolute_once_expanded(self):
        assert is_absolute_key("~/.config/")
        assert is_home_relative("~/.config/")


class TestResolveKey:
    """resolve_key is the only place a catalog key becomes a real path."""

    def test_relative_key_joins_onto_root(self, tmp_path):
        assert resolve_key(tmp_path, "area/inv/") == (tmp_path / "area/inv").resolve()

    def test_absolute_key_ignores_root(self, tmp_path):
        assert resolve_key(tmp_path, "/etc/nginx/") == Path("/etc/nginx")

    def test_home_relative_key_expands(self, tmp_path):
        assert resolve_key(tmp_path, "~/x/") == (Path.home() / "x").resolve()

    def test_dotdot_key_resolves_above_root(self, tmp_path):
        root = tmp_path / "root"
        assert resolve_key(root, "../sibling/") == (tmp_path / "sibling").resolve()

    def test_plain_join_would_have_silently_discarded_root(self, tmp_path):
        """Why every consumer goes through resolve_key: Python's path join
        drops the left operand entirely when the right is absolute, so an
        absolute key joined by hand lands somewhere other than intended."""
        assert (tmp_path / "/etc/nginx") == Path("/etc/nginx")

    def test_plain_join_would_not_have_expanded_tilde(self, tmp_path):
        """The other half: `~` isn't magic to pathlib, so a home-relative
        key would resolve to a literal '~' directory under root."""
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
# Validator / runner integration
# ---------------------------------------------------------------------

BOILERPLATE_HEAD = '''root = "~/usr/"

[meta]
schema_version = "2.0"
standard_version = "2.0"
schema_date = "2026-01-01"
standard_date = "2026-01-01"

[paths.attributes]
names = ["purpose"]
required = ["purpose"]

[paths.attributes.group]
names = ["lifecycle"]
required = ["lifecycle"]
'''

BOILERPLATE_TAIL = '''
[enums.group.lifecycle]
ongoing = "x"

[tags]
[abbreviations]
[folders]
'''


def validate(standard_toml: str, tmp_path: Path):
    std_path = tmp_path / "test.toml"
    std_path.write_text(standard_toml)
    data = tomllib.loads(standard_toml)
    header_occurrences, key_lines = _index_source(standard_toml)
    validator = Validator(data, tmp_path, header_occurrences, key_lines)
    return validator.run(), validator


def entry(key: str) -> str:
    return f'\n[paths."{key}"]\npurpose = "x"\n\n[paths."{key}".group]\nlifecycle = "ongoing"\n'


def errors(issues):
    return [i for i in issues if i.level == "error"]


class TestValidatorOutOfRootKeys:
    """A key naming somewhere outside root is ordinary: it resolves where
    it says, and nothing has to be declared for that."""

    def test_an_absolute_key_validates(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("/etc/nginx/") + BOILERPLATE_TAIL, tmp_path)
        assert errors(issues) == []

    def test_a_home_relative_key_validates(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("~/.config/") + BOILERPLATE_TAIL, tmp_path)
        assert errors(issues) == []

    def test_a_dotdot_key_validates(self, tmp_path):
        issues, _ = validate(BOILERPLATE_HEAD + entry("../sibling/") + BOILERPLATE_TAIL, tmp_path)
        assert errors(issues) == []

    def test_a_cross_set_may_reference_one(self, tmp_path):
        standard = (
            BOILERPLATE_HEAD
            + entry("area/a/")
            + '\n[[paths.cross]]\npaths = ["area/a/", "/etc/nginx/"]\n'
            + BOILERPLATE_TAIL
        )
        issues, _ = validate(standard, tmp_path)
        assert errors(issues) == []


class TestValidatorOverlapAcrossTheRootBoundary:

    def test_inside_and_outside_lookalikes_do_not_collide(self, tmp_path):
        """"/srv/*/" and "srv/*/" name different places; flagging them as
        overlapping would be a false positive."""
        standard = BOILERPLATE_HEAD + entry("/srv/*/") + entry("srv/*/") + BOILERPLATE_TAIL
        issues, _ = validate(standard, tmp_path)
        assert errors(issues) == []

    def test_two_spellings_of_the_same_outside_place_still_collide(self, tmp_path):
        home = str(Path.home())
        standard = BOILERPLATE_HEAD + entry("~/shared/*/") + entry(f"{home}/shared/*/") + BOILERPLATE_TAIL
        issues, _ = validate(standard, tmp_path)
        assert errors(issues) != []


class TestRunnerResolvesOutsideRootTargets:

    def _invocations(self, std_text: str, tmp_path: Path, root: Path):
        data = tomllib.loads(std_text)
        _, validator = validate(std_text, tmp_path)
        return collect_invocations(data, root, validator.rule_catalog, validator.resolved_paths)

    def _entry_with_rule(self, key: str) -> str:
        return (
            f'\n[paths."{key}"]\npurpose = "x"\n'
            f'\n[paths."{key}".group]\nlifecycle = "ongoing"\n'
            f'\n[[paths."{key}".rules.file-extensions-v1]]\nreason = "r"\n'
            f'\n[paths."{key}".rules.file-extensions-v1.params]\nallowed = ["jpg"]\n'
        )

    def test_absolute_target_is_invoked_where_it_actually_lives(self, tmp_path):
        """The directory exists outside root and nothing exists at the
        would-be joined location, so finding it proves resolve_key is being
        used rather than a plain join."""
        outside = tmp_path / "outside"
        outside.mkdir()
        root = tmp_path / "root"
        root.mkdir()

        std_text = BOILERPLATE_HEAD + self._entry_with_rule(f"{outside}/") + BOILERPLATE_TAIL
        invocations = self._invocations(std_text, tmp_path, root)
        assert [inv.target_path for inv in invocations] == [outside]

    def test_an_absent_target_contributes_no_invocation(self, tmp_path):
        root = tmp_path / "root"
        root.mkdir()
        gone = tmp_path / "not-there"

        std_text = BOILERPLATE_HEAD + self._entry_with_rule(f"{gone}/") + BOILERPLATE_TAIL
        assert self._invocations(std_text, tmp_path, root) == []


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
