"""
tests/test_sandbox.py - unit tests for fs_org_kit.sandbox.

The enforcement half only exists in a child process, so those tests drive
a real one: a throwaway script is written to disk and run exactly the way
the runner runs a rule. Asserting on the process's exit code and stderr is
the only way to test what an audit hook actually did - importing the module
and calling the hook by hand would test a different code path than the one
that ships.

Run with: python -m pytest tests/test_sandbox.py -v
"""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

from fs_org_kit.sandbox import CAPABILITIES, Policy, capabilities_for, child_env


def run_under_sandbox(script_body: str, policy: Policy, tmp_path: Path, args: list[str] | None = None):
    """Write script_body to disk and run it wrapped exactly as the runner
    wraps a rule script."""
    script = tmp_path / "rule-check.py"
    script.write_text(script_body)
    argv = policy.wrap([sys.executable, str(script), *(args or [])])
    return subprocess.run(argv, capture_output=True, text=True, env=child_env(), timeout=60)


def writable_policy(*paths: Path, **caps) -> Policy:
    return Policy(writable=tuple(str(p.resolve()) for p in paths), **caps)


class TestCapabilitiesFor:
    """Reading a manifest's [sandbox] table."""

    def test_absent_table_grants_nothing(self):
        assert capabilities_for(None) == (set(), [])

    def test_true_grants(self):
        granted, complaints = capabilities_for({"subprocess": True})
        assert granted == {"subprocess"}
        assert complaints == []

    def test_false_is_a_denial_not_a_grant(self):
        """Spelling out a denial is allowed - it documents intent for a
        reader without changing behavior."""
        granted, complaints = capabilities_for({"network": False})
        assert granted == set()
        assert complaints == []

    def test_unknown_capability_is_reported(self):
        """A typo'd capability that silently granted nothing would surface
        much later as a confusing runtime failure."""
        granted, complaints = capabilities_for({"subproccess": True})
        assert granted == set()
        assert len(complaints) == 1
        assert "subproccess" in complaints[0]

    def test_non_boolean_value_is_reported(self):
        granted, complaints = capabilities_for({"network": "yes"})
        assert granted == set()
        assert complaints

    def test_non_table_is_reported(self):
        assert capabilities_for(["network"]) == (set(), ["[sandbox] must be a table"])

    def test_every_capability_name_is_accepted(self):
        granted, complaints = capabilities_for({name: True for name in CAPABILITIES})
        assert granted == set(CAPABILITIES)
        assert complaints == []


class TestPolicyForInvocation:
    """What each kind of invocation is entitled to."""

    def test_checker_gets_no_target_or_root(self, tmp_path):
        """"Checkers never write" was a documented convention with nothing
        enforcing it; this is what enforcing it looks like."""
        policy = Policy.for_invocation(
            set(), is_fix=False, targets=[tmp_path / "t"], root_dir=tmp_path, cache_dir=None
        )
        assert str(tmp_path) not in policy.writable
        assert str(tmp_path / "t") not in policy.writable

    def test_checker_still_gets_its_cache(self, tmp_path):
        """duplicate-files-v1 is a checker that has to persist hashes."""
        cache = tmp_path / "cache"
        policy = Policy.for_invocation(
            set(), is_fix=False, targets=[], root_dir=tmp_path, cache_dir=cache
        )
        assert str(cache.resolve()) in policy.writable

    def test_temp_dir_is_always_writable(self):
        policy = Policy.for_invocation(set(), is_fix=False, targets=[], root_dir=None, cache_dir=None)
        assert str(Path(tempfile.gettempdir()).resolve()) in policy.writable

    def test_fixer_gets_root_and_targets(self, tmp_path):
        target = tmp_path / "t"
        policy = Policy.for_invocation(
            set(), is_fix=True, targets=[target], root_dir=tmp_path, cache_dir=None
        )
        assert str(tmp_path.resolve()) in policy.writable
        assert str(target.resolve()) in policy.writable

    def test_out_of_root_target_is_writable_for_a_fixer(self, tmp_path):
        """A target outside root is exactly the case root alone can't cover."""
        root = tmp_path / "root"
        outside = tmp_path / "elsewhere"
        policy = Policy.for_invocation(
            set(), is_fix=True, targets=[outside], root_dir=root, cache_dir=None
        )
        assert str(outside.resolve()) in policy.writable

    def test_round_trips_through_json(self, tmp_path):
        policy = Policy.for_invocation(
            {"network", "subprocess"}, is_fix=True, targets=[tmp_path], root_dir=tmp_path, cache_dir=None
        )
        assert Policy.from_json(policy.to_json()) == policy

    def test_wrap_preserves_the_rule_argv(self, tmp_path):
        policy = Policy()
        wrapped = policy.wrap([sys.executable, "/rules/x-check.py", "--path", "/p", "--params", "{}"])
        assert wrapped[-4:] == ["--path", "/p", "--params", "{}"]
        assert "/rules/x-check.py" in wrapped
        assert "-B" in wrapped  # no .pyc writes for anything the rule imports


class TestWritesAreBlocked:

    def test_write_outside_the_policy_is_blocked(self, tmp_path):
        target = tmp_path / "forbidden.txt"
        result = run_under_sandbox(
            f"open({str(target)!r}, 'w').write('x')\n", Policy(), tmp_path
        )
        assert result.returncode != 0
        assert "sandbox: blocked" in result.stderr
        assert not target.exists()

    def test_write_inside_the_policy_succeeds(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        target = allowed / "f.txt"
        result = run_under_sandbox(
            f"open({str(target)!r}, 'w').write('x')\nprint('{{}}')\n",
            writable_policy(allowed), tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert target.read_text() == "x"

    def test_reads_are_never_blocked(self, tmp_path):
        source = tmp_path / "readable.txt"
        source.write_text("content")
        result = run_under_sandbox(
            f"print(open({str(source)!r}).read())\n", Policy(), tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "content" in result.stdout

    def test_os_open_write_flags_are_caught_without_a_mode_string(self, tmp_path):
        """os.open reports flags and no mode, so the flags are the only
        signal that a write is coming."""
        target = tmp_path / "viaosopen.txt"
        result = run_under_sandbox(
            f"import os\nos.close(os.open({str(target)!r}, os.O_WRONLY | os.O_CREAT))\n",
            Policy(), tmp_path,
        )
        assert result.returncode != 0
        assert "sandbox: blocked" in result.stderr
        assert not target.exists()

    def test_mkdir_outside_the_policy_is_blocked(self, tmp_path):
        target = tmp_path / "newdir"
        result = run_under_sandbox(f"import os\nos.mkdir({str(target)!r})\n", Policy(), tmp_path)
        assert result.returncode != 0
        assert not target.exists()

    def test_delete_outside_the_policy_is_blocked(self, tmp_path):
        victim = tmp_path / "keepme.txt"
        victim.write_text("important")
        result = run_under_sandbox(f"import os\nos.remove({str(victim)!r})\n", Policy(), tmp_path)
        assert result.returncode != 0
        assert victim.read_text() == "important"

    def test_rename_is_checked_on_both_ends(self, tmp_path):
        """Moving a file out of a writable area is as much a write to the
        source as to the destination."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        source = allowed / "f.txt"
        source.write_text("x")
        outside = tmp_path / "escaped.txt"
        result = run_under_sandbox(
            f"import os\nos.rename({str(source)!r}, {str(outside)!r})\n",
            writable_policy(allowed), tmp_path,
        )
        assert result.returncode != 0
        assert not outside.exists()

    def test_shutil_move_out_of_the_policy_is_blocked(self, tmp_path):
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        source = allowed / "f.txt"
        source.write_text("x")
        outside = tmp_path / "escaped.txt"
        result = run_under_sandbox(
            f"import shutil\nshutil.move({str(source)!r}, {str(outside)!r})\n",
            writable_policy(allowed), tmp_path,
        )
        assert result.returncode != 0
        assert not outside.exists()

    def test_symlink_escape_does_not_widen_the_policy(self, tmp_path):
        """A symlink inside a writable directory pointing out of it must not
        become a way to write out of it - which is why paths are compared
        after realpath, not as written."""
        allowed = tmp_path / "allowed"
        allowed.mkdir()
        outside_dir = tmp_path / "outside"
        outside_dir.mkdir()
        (allowed / "escape").symlink_to(outside_dir)

        target = allowed / "escape" / "f.txt"
        result = run_under_sandbox(
            f"open({str(target)!r}, 'w').write('x')\n", writable_policy(allowed), tmp_path
        )
        assert result.returncode != 0
        assert not (outside_dir / "f.txt").exists()

    def test_unrestricted_writes_lets_everything_through(self, tmp_path):
        target = tmp_path / "anywhere.txt"
        result = run_under_sandbox(
            f"open({str(target)!r}, 'w').write('x')\nprint('{{}}')\n",
            Policy(unrestricted_writes=True), tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert target.exists()


class TestCapabilitiesAreEnforced:

    @pytest.mark.parametrize("body,needle", [
        ("import socket; socket.getaddrinfo('example.invalid', 80)", "network"),
        ("import subprocess; subprocess.run(['/bin/true'])", "another process"),
        ("import ctypes; ctypes.CDLL(None)", "native"),
    ])
    def test_blocked_by_default(self, tmp_path, body, needle):
        result = run_under_sandbox(body + "\n", Policy(), tmp_path)
        assert result.returncode != 0
        assert needle in result.stderr

    def test_network_granted(self, tmp_path):
        result = run_under_sandbox(
            "import socket\n"
            "try: socket.getaddrinfo('example.invalid', 80)\n"
            "except OSError: pass\n"
            "print('reached-the-end')\n",
            Policy(network=True), tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "reached-the-end" in result.stdout

    def test_subprocess_granted(self, tmp_path):
        result = run_under_sandbox(
            "import subprocess\nsubprocess.run(['/bin/true'])\nprint('ran')\n",
            Policy(subprocess=True), tmp_path,
        )
        assert result.returncode == 0, result.stderr
        assert "ran" in result.stdout


class TestViolationsCannotBeSwallowed:

    def test_except_exception_does_not_catch_a_violation(self, tmp_path):
        """Rule scripts routinely wrap their work in `except Exception` to
        turn a crash into a clean exit. A violation caught by that handler
        would be reported as an ordinary failure, or as success."""
        target = tmp_path / "f.txt"
        result = run_under_sandbox(
            "try:\n"
            f"    open({str(target)!r}, 'w').write('x')\n"
            "except Exception:\n"
            '    print(\'{"status": "ok"}\')\n',
            Policy(), tmp_path,
        )
        assert result.returncode != 0
        assert '"status": "ok"' not in result.stdout

    def test_bare_except_still_fails_the_invocation(self, tmp_path):
        """A bare `except:` does catch BaseException, so the exception alone
        isn't enough - the violation is recorded too, and a script that
        suppressed one can't report success."""
        target = tmp_path / "f.txt"
        result = run_under_sandbox(
            "try:\n"
            f"    open({str(target)!r}, 'w').write('x')\n"
            "except BaseException:\n"
            '    print(\'{"status": "ok"}\')\n',
            Policy(), tmp_path,
        )
        assert result.returncode != 0
        assert "suppressed" in result.stderr


class TestScriptSemanticsArePreserved:
    """Whatever the harness does, a rule must behave the way it does when
    run standalone - that's the documented, debuggable contract."""

    def test_argv_reaches_the_script(self, tmp_path):
        result = run_under_sandbox(
            "import sys, json\nprint(json.dumps(sys.argv[1:]))\n",
            Policy(), tmp_path, args=["--path", "/p", "--params", "{}"],
        )
        assert json.loads(result.stdout) == ["--path", "/p", "--params", "{}"]

    def test_exit_code_is_propagated(self, tmp_path):
        result = run_under_sandbox("import sys\nsys.exit(3)\n", Policy(), tmp_path)
        assert result.returncode == 3

    def test_a_sibling_module_beside_the_script_is_importable(self, tmp_path):
        """runpy.run_path does not put the script's directory on sys.path
        the way direct execution does. staleness-v1 imports a _shared
        module beside it, and broke on exactly this."""
        (tmp_path / "_helper.py").write_text("VALUE = 'imported'\n")
        result = run_under_sandbox(
            "from _helper import VALUE\nprint(VALUE)\n", Policy(), tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert "imported" in result.stdout

    def test_stdout_is_not_polluted_by_the_harness(self, tmp_path):
        """The runner parses stdout as exactly one JSON line."""
        result = run_under_sandbox('print(\'{"status": "ok"}\')\n', Policy(), tmp_path)
        assert result.stdout.strip() == '{"status": "ok"}'

    def test_uncaught_error_still_reports_on_stderr(self, tmp_path):
        result = run_under_sandbox("raise ValueError('boom')\n", Policy(), tmp_path)
        assert result.returncode != 0
        assert "boom" in result.stderr

    def test_a_string_exit_code_keeps_its_message(self, tmp_path):
        """sys.exit("...") prints its message at top level; caught by the
        harness, it must still print, since it's the `broken` reason."""
        result = run_under_sandbox('import sys\nsys.exit("custom failure")\n', Policy(), tmp_path)
        assert result.returncode == 1
        assert "custom failure" in result.stderr


class TestPolicyEdges:

    def test_a_filesystem_anchor_covers_everything_beneath_it(self, tmp_path):
        """"/" (or "C:\\") already ends in a separator - appending another
        used to make nothing beneath it match."""
        anchor = os.path.realpath(tmp_path.anchor)
        target = tmp_path / "out.txt"
        result = run_under_sandbox(
            f"open({str(target)!r}, 'w').write('x')\n", Policy(writable=(anchor,)), tmp_path
        )
        assert result.returncode == 0, result.stderr
        assert target.read_text() == "x"

    def test_sqlite_outside_the_policy_is_blocked(self, tmp_path):
        """sqlite3 opens its file from C, without an `open` event."""
        database = tmp_path / "elsewhere.sqlite3"
        result = run_under_sandbox(
            f"import sqlite3\nsqlite3.connect({str(database)!r})\n", Policy(), tmp_path
        )
        assert result.returncode != 0
        assert "sqlite3.connect" in result.stderr
        assert not database.exists()
