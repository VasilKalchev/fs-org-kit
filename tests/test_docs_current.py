"""
Tests the documentation against what is actually on disk.

Everything checked here is derivable from the repository - test counts,
the rule inventory, which modules have tests, whether a doc link points
at a real file. Prose that says "remember to update the count" fails
silently; these fail loudly.

Not a style checker. It only asserts facts that have a single correct
answer, so a failure here is always a real drift, never an opinion.
"""

import re
import subprocess
import sys
import tomllib
from collections import Counter
from pathlib import Path

import pytest

from fs_org_kit.discovery import IssueLevel, discover_rules

REPO_ROOT = Path(__file__).resolve().parent.parent
RULES_DIR = REPO_ROOT / "rules"
DOC_DIR = REPO_ROOT / "doc"
TESTING_MD = DOC_DIR / "TESTING.md"
README_MD = REPO_ROOT / "README.md"

# Bundled rules that predate this check and still have no tests. This is
# debt, not policy - shrink it, never grow it. A new rule with no tests
# fails `test_every_bundled_rule_has_tests` rather than being quietly
# added here, and a rule that gains tests fails
# `test_untested_list_has_no_stale_entries` until it's removed.
RULES_WITHOUT_TESTS = frozenset({
    "mime-type-v1",
    "naming-pattern-v1",
    "spelling-abbreviations-v1",
    "staleness-v1",
    "timestamp-consistency-v1",
    "uncataloged-reserved-v1",
})

NUMBER_WORDS = {
    1: "one", 2: "two", 3: "three", 4: "four", 5: "five", 6: "six",
    7: "seven", 8: "eight", 9: "nine", 10: "ten", 11: "eleven",
    12: "twelve", 13: "thirteen", 14: "fourteen", 15: "fifteen",
    16: "sixteen", 17: "seventeen", 18: "eighteen", 19: "nineteen",
    20: "twenty",
}

# Scratch space, deliberately not held to the same standard as the docs.
SCAN_EXCLUDE = {"scratch.md"}

# A changelog names files that were renamed or deleted - that's its job,
# not drift. Its Markdown links are still checked; only bare mentions are
# exempt.
HISTORICAL = {"CHANGELOG.md"}


def rule_dirs() -> list[Path]:
    return sorted(d for d in RULES_DIR.iterdir() if d.is_dir() and not d.name.startswith("_"))


def scanned_files() -> list[Path]:
    """Every file whose text may reference a doc, excluding scratch space."""
    patterns = ("*.md", "*.toml", "doc/*.md", "fs_org_kit/*.py", "tests/*.py",
                "rules/*/*.py", ".claude/skills/*/*.md", ".claude/skills/*/*.py")
    found = {p for pattern in patterns for p in REPO_ROOT.glob(pattern)}
    return sorted(p for p in found if p.name not in SCAN_EXCLUDE)


@pytest.fixture(scope="module")
def collected() -> Counter:
    """Test count per file, keyed by repo-relative path, from pytest itself."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q",
         "-o", "addopts=", "-p", "no:cacheprovider"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    if result.returncode != 0:
        pytest.fail(f"collection failed:\n{result.stdout}\n{result.stderr}")

    counts: Counter = Counter()
    for line in result.stdout.splitlines():
        head = line.split("::", 1)[0]
        if "::" in line and head.endswith(".py") and (REPO_ROOT / head).exists():
            counts[head] += 1
    if not counts:
        pytest.fail(f"parsed no tests out of collection output:\n{result.stdout}")
    return counts


class TestTestCoverage:
    """Every module and every rule is actually tested."""

    def test_every_module_has_a_test_file(self):
        modules = {p.stem for p in (REPO_ROOT / "fs_org_kit").glob("*.py") if p.stem != "__init__"}
        missing = {m for m in modules if not (REPO_ROOT / "tests" / f"test_{m}.py").exists()}
        assert not missing

    def test_every_bundled_rule_has_tests(self):
        missing = {d.name for d in rule_dirs() if not list(d.glob("test_*.py"))}
        assert not missing - RULES_WITHOUT_TESTS

    def test_untested_list_has_no_stale_entries(self):
        """A rule that gained tests must come off the list, or it hides a regression."""
        now_tested = {name for name in RULES_WITHOUT_TESTS
                      if list((RULES_DIR / name).glob("test_*.py"))}
        assert not now_tested

    def test_untested_list_names_real_rules(self):
        assert RULES_WITHOUT_TESTS <= {d.name for d in rule_dirs()}


class TestRuleInventory:
    """The bundled tier is structurally sound and correctly counted."""

    def test_every_bundled_rule_discovers_cleanly(self, tmp_path):
        catalog, issues = discover_rules(standard_dir=tmp_path, bundled_rules_dir=RULES_DIR)
        errors = [str(i) for i in issues if i.level is IssueLevel.ERROR]
        assert not errors
        assert set(catalog) == {d.name for d in rule_dirs()}

    def test_manifest_version_major_matches_directory(self):
        mismatched = []
        for d in rule_dirs():
            manifest = d / f"{d.name}.toml"
            declared = tomllib.loads(manifest.read_text())["version"].split(".")[0]
            if f"v{declared}" != d.name.rsplit("-", 1)[-1]:
                mismatched.append(d.name)
        assert not mismatched

    def test_readme_states_the_real_rule_count(self):
        count = len(rule_dirs())
        word = NUMBER_WORDS[count]
        text = README_MD.read_text()
        assert f"{word} bundled rules" in text, f"README should say '{word} bundled rules'"

    def test_no_stale_rule_count_anywhere(self):
        """Catches a count updated in one doc but not another.

        Only the plural "<word> bundled rules" is a live claim; the
        singular ("the twelfth bundled rule") is historical and left
        alone, which is why CHANGELOG.md needs no exemption here.
        """
        correct = NUMBER_WORDS[len(rule_dirs())]
        stale = []
        for path in [p for p in scanned_files() if p.suffix == ".md"]:
            text = path.read_text()
            stale += [f"{path.relative_to(REPO_ROOT)}: {w}"
                      for w in NUMBER_WORDS.values()
                      if w != correct and f"{w} bundled rules" in text]
        assert not stale


class TestTestingMdCounts:
    """doc/TESTING.md's stated counts match what pytest actually collects."""

    #   ### Runner tests (29 tests, `tests/test_runner.py`)
    #   - **`rules/x-v1/test_x_v1.py`** (14 tests): ...
    HEADING = re.compile(r"\((\d+) tests?, `([^`]+\.py)`\)")
    BULLET = re.compile(r"\*\*`([^`]+\.py)`\*\* \((\d+) tests?\)")
    AGGREGATE = re.compile(r"\((\d+) tests?, inside `rules/`\)")

    def claimed(self) -> dict[str, int]:
        text = TESTING_MD.read_text()
        claims = {path: int(n) for n, path in self.HEADING.findall(text)}
        claims.update({path: int(n) for path, n in self.BULLET.findall(text)})
        return claims

    def test_every_claimed_count_is_correct(self, collected):
        wrong = {path: (claim, collected.get(path))
                 for path, claim in self.claimed().items()
                 if collected.get(path) != claim}
        assert not wrong, f"stated (claimed, actual): {wrong}"

    def test_bundled_aggregate_is_correct(self, collected):
        actual = sum(n for path, n in collected.items() if path.startswith("rules/"))
        stated = self.AGGREGATE.findall(TESTING_MD.read_text())
        assert stated, "TESTING.md should state a total for the bundled rule tests"
        assert [int(s) for s in stated] == [actual] * len(stated)

    def test_every_test_file_is_documented(self, collected):
        text = TESTING_MD.read_text()
        undocumented = {path for path in collected if path not in text}
        assert not undocumented


class TestDocReferences:
    """Every doc a file points at exists - renaming one can't leave dangling links."""

    LINK = re.compile(r"\]\(([^)\s]+\.md)(?:#[^)]*)?\)")
    DOC_MENTION = re.compile(r"doc/([A-Za-z0-9_.-]+\.md)")

    def test_markdown_links_resolve(self):
        broken = []
        for md in [p for p in scanned_files() if p.suffix == ".md"]:
            for target in self.LINK.findall(md.read_text()):
                if target.startswith(("http://", "https://")):
                    continue
                if not (md.parent / target).exists():
                    broken.append(f"{md.relative_to(REPO_ROOT)} -> {target}")
        assert not broken

    def test_doc_paths_mentioned_in_prose_and_code_exist(self):
        """Catches a stale path in a docstring, which no link check would see."""
        broken = []
        for path in scanned_files():
            if path.name in HISTORICAL:
                continue
            for name in set(self.DOC_MENTION.findall(path.read_text())):
                if not (DOC_DIR / name).exists():
                    broken.append(f"{path.relative_to(REPO_ROOT)} -> doc/{name}")
        assert not broken
