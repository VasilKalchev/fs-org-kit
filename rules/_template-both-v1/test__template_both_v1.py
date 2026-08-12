"""
Tests for _template-both-v1.

Scripts are invoked via subprocess exactly as the runner does, never by
importing their internals - that subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

Most of what's here covers the argument validation scope = "both" makes
the script's own responsibility; a rule copied from this template should
keep these cases and add its own on top.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "_template-both-v1-check.py"
FIX_SCRIPT = RULE_DIR / "_template-both-v1-fix.py"


def run(script: Path, params: dict, path=None, paths=None, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(script), "--params", json.dumps(params)]
    if path is not None:
        argv += ["--path", str(path)]
    for one in paths or []:
        argv += ["--paths", str(one)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def two_dirs(tmp_path: Path) -> list[Path]:
    made = []
    for name in ("a", "b"):
        directory = tmp_path / name
        directory.mkdir()
        (directory / "file.txt").write_text(name)
        made.append(directory)
    return made


class TestChecker:

    def test_single_path_is_ok(self, tmp_path):
        assert verdict(run(CHECK_SCRIPT, {}, path=tmp_path)) == {"status": "ok"}

    def test_a_path_set_is_ok(self, tmp_path):
        assert verdict(run(CHECK_SCRIPT, {}, paths=two_dirs(tmp_path))) == {"status": "ok"}

    def test_fix_is_rejected(self, tmp_path):
        assert run(CHECK_SCRIPT, {}, path=tmp_path, fix=True).returncode != 0

    def test_a_missing_path_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {}, path=tmp_path / "nope").returncode != 0


class TestScopeBothArgumentHandling:
    """The three ambiguous calls the runner can't disambiguate for it."""

    def test_both_flags_together_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {}, path=tmp_path, paths=two_dirs(tmp_path)).returncode != 0

    def test_neither_flag_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {}).returncode != 0

    def test_a_single_value_in_paths_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, {}, paths=[tmp_path]).returncode != 0


class TestFixer:

    def test_single_path_is_ok(self, tmp_path):
        assert verdict(run(FIX_SCRIPT, {}, path=tmp_path, fix=True)) == {"status": "ok"}

    def test_both_flags_together_is_broken(self, tmp_path):
        assert run(FIX_SCRIPT, {}, path=tmp_path, paths=two_dirs(tmp_path), fix=True).returncode != 0
