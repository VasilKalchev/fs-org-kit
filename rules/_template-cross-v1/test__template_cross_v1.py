"""
Tests for _template-cross-v1.

Scripts are invoked via subprocess exactly as the runner does, never by
importing their internals - that subprocess call IS the documented
contract, so testing through it is the only way to catch a break in it.

These run as part of this repo's own suite, which is what keeps the
template honest: if the protocol changes and the template doesn't, this
fails here rather than in whatever someone copied it into.
"""

import json
import subprocess
import sys
from pathlib import Path

RULE_DIR = Path(__file__).parent
CHECK_SCRIPT = RULE_DIR / "_template-cross-v1-check.py"
FIX_SCRIPT = RULE_DIR / "_template-cross-v1-fix.py"


def run(script: Path, paths, params: dict, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(script), "--params", json.dumps(params)]
    for path in paths:
        argv += ["--paths", str(path)]
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

    def test_two_clean_directories_are_ok(self, tmp_path):
        assert verdict(run(CHECK_SCRIPT, two_dirs(tmp_path), {})) == {"status": "ok"}

    def test_recursive_false_is_accepted(self, tmp_path):
        assert verdict(run(CHECK_SCRIPT, two_dirs(tmp_path), {"recursive": False})) == {"status": "ok"}

    def test_fix_is_rejected(self, tmp_path):
        assert run(CHECK_SCRIPT, two_dirs(tmp_path), {}, fix=True).returncode != 0

    def test_a_single_path_is_broken(self, tmp_path):
        """The 2-or-more minimum is the script's own to enforce."""
        assert run(CHECK_SCRIPT, two_dirs(tmp_path)[:1], {}).returncode != 0

    def test_a_missing_path_is_broken(self, tmp_path):
        first, _ = two_dirs(tmp_path)
        assert run(CHECK_SCRIPT, [first, tmp_path / "nope"], {}).returncode != 0


class TestFixer:

    def test_two_clean_directories_are_ok(self, tmp_path):
        assert verdict(run(FIX_SCRIPT, two_dirs(tmp_path), {}, fix=True)) == {"status": "ok"}

    def test_a_single_path_is_broken(self, tmp_path):
        assert run(FIX_SCRIPT, two_dirs(tmp_path)[:1], {}, fix=True).returncode != 0
