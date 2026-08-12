"""
Tests for _template-single-v1.

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
CHECK_SCRIPT = RULE_DIR / "_template-single-v1-check.py"
FIX_SCRIPT = RULE_DIR / "_template-single-v1-fix.py"


def run(script: Path, path, params: dict, fix: bool = False) -> subprocess.CompletedProcess:
    argv = [sys.executable, str(script), "--path", str(path),
            "--params", json.dumps(params)]
    if fix:
        argv.append("--fix")
    return subprocess.run(argv, capture_output=True, text=True)


def verdict(result: subprocess.CompletedProcess) -> dict:
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class TestChecker:

    def test_a_clean_directory_is_ok(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        assert verdict(run(CHECK_SCRIPT, tmp_path, {})) == {"status": "ok"}

    def test_recursive_false_is_accepted(self, tmp_path):
        (tmp_path / "sub").mkdir()
        assert verdict(run(CHECK_SCRIPT, tmp_path, {"recursive": False})) == {"status": "ok"}

    def test_fix_is_rejected(self, tmp_path):
        assert run(CHECK_SCRIPT, tmp_path, {}, fix=True).returncode != 0

    def test_a_missing_path_is_broken(self, tmp_path):
        assert run(CHECK_SCRIPT, tmp_path / "nope", {}).returncode != 0

    def test_bad_params_json_is_broken(self, tmp_path):
        result = subprocess.run(
            [sys.executable, str(CHECK_SCRIPT), "--path", str(tmp_path), "--params", "{not json"],
            capture_output=True, text=True,
        )
        assert result.returncode != 0


class TestFixer:

    def test_a_clean_directory_is_ok(self, tmp_path):
        (tmp_path / "file.txt").write_text("hello")
        assert verdict(run(FIX_SCRIPT, tmp_path, {}, fix=True)) == {"status": "ok"}

    def test_a_missing_path_is_broken(self, tmp_path):
        assert run(FIX_SCRIPT, tmp_path / "nope", {}, fix=True).returncode != 0
