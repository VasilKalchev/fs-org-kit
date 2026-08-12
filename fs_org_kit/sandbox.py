#!/usr/bin/env python3
"""
fs_org_kit.sandbox - runs a rule script under an audit-hook harness that
blocks network access, subprocess execution, native calls, and writes
outside the places that invocation is entitled to touch.

This module has two halves, deliberately in one file so the policy that
the runner *builds* and the policy the child process *enforces* can never
drift apart:

    parent side (imported by the runner)
        capabilities_for()  what a manifest's [sandbox] table grants
        Policy.for_invocation()  what this specific invocation may do
        Policy.wrap()       turn a rule argv into a sandboxed argv

    child side (python -m fs_org_kit.sandbox ...)
        main()              install the hook, then run the rule script

What this is, and is not
------------------------
It is a guard against bugs and accidents: a checker that writes when the
protocol says checkers never write, a fixer that reaches outside the tree
it was pointed at, a rule that quietly phones home. All of those are
mistakes an author makes without meaning to, and none of them were
detectable before - the convention was documented and entirely unenforced.

It is NOT a security boundary, and shouldn't be described as one. An
audit hook lives inside the interpreter it is policing: `ctypes` reaches
straight past it (which is why `native` is a capability rather than a
permanent block), a bare `except:` can swallow the violation before it
propagates, and nothing here constrains a rule that was malicious rather
than careless. Real isolation means the OS - bubblewrap, Landlock,
Seatbelt - and stays out of scope (see doc/DESIGN.md, "OS-level
sandboxing"). Two things narrow the swallow hole rather than close it:
SandboxViolation derives from BaseException, so `except Exception` misses
it, and every violation is also recorded so a script that swallows one
and reports success still fails the invocation.

Capabilities
------------
A rule that genuinely needs one of the blocked operations declares it in
its manifest, exactly the way `uses_cache` declares a need for storage:

    [sandbox]
    subprocess = true     # e.g. basename-sync-v1 delegates to a user script

This keeps the runner free of per-rule knowledge - it reads a declaration,
it doesn't special-case a rule name (which is a standing constraint on
this project). It also puts the grant somewhere a reviewer reads before
trusting a rule, instead of somewhere they'd have to infer it from code.

Writable locations
------------------
Always writable:  the rule's own cache directory (when it has one), the
system temp directory, and the null/tty devices.

Additionally writable in --fix mode:  root, and the invocation's own
target path(s). Targets are listed separately because a catalog key may
name a location outside root (fs_org_kit.path_keys), which root alone
would not cover.

A checker therefore gets no writable location beyond its cache and temp,
which is the protocol's "checkers never write" rule, finally enforced.
A rule whose fixer legitimately writes somewhere it cannot predict - a
user-configured destination, say - declares `unrestricted_writes = true`
and says why in its manifest.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path

# Every capability a manifest's [sandbox] table may grant. Anything else
# in that table is a typo, and discovery warns about it rather than
# silently not granting what the author thought they'd asked for.
CAPABILITIES = ("network", "subprocess", "native", "unrestricted_writes")

# Devices that are always safe to write to - writing to /dev/null is a
# normal way to discard output, and the tty/std streams are how a script
# talks to the runner in the first place.
ALWAYS_WRITABLE_FILES = frozenset({"/dev/null", "/dev/zero", "/dev/tty", "/dev/stdout", "/dev/stderr"})


class SandboxViolation(BaseException):
    """Raised inside the rule's own process when it attempts a blocked
    operation.

    Derives from BaseException, not Exception, on purpose: rule scripts
    routinely wrap their work in `except Exception` to convert a crash
    into a clean nonzero exit, and a sandbox violation swallowed by that
    handler would be reported as an ordinary failure - or worse, ignored.
    BaseException walks past those handlers the way SystemExit does."""


# =====================================================================
# Parent side - building the policy
# =====================================================================

def capabilities_for(sandbox_table: object) -> tuple[set[str], list[str]]:
    """Read a manifest's [sandbox] table into (granted, complaints).

    Only `true` grants. A capability set to false, or absent, is denied,
    so a manifest can spell out its denials for a reader without changing
    anything. Complaints are returned rather than raised - discovery
    turns them into warnings attributed to the rule."""
    granted: set[str] = set()
    complaints: list[str] = []
    if sandbox_table is None:
        return granted, complaints
    if not isinstance(sandbox_table, dict):
        return granted, ["[sandbox] must be a table"]
    for name, value in sandbox_table.items():
        if name not in CAPABILITIES:
            complaints.append(
                f"[sandbox] declares unknown capability '{name}' - "
                f"nothing is granted for it (known: {', '.join(CAPABILITIES)})"
            )
            continue
        if value is True:
            granted.add(name)
        elif value is not False:
            complaints.append(f"[sandbox].{name} must be true or false, not {value!r}")
    return granted, complaints


@dataclass(frozen=True)
class Policy:
    """What one invocation of one rule script is allowed to do."""

    writable: tuple[str, ...] = ()
    network: bool = False
    subprocess: bool = False
    native: bool = False
    unrestricted_writes: bool = False

    @classmethod
    def for_invocation(
        cls,
        granted: set[str],
        *,
        is_fix: bool,
        targets: list[Path],
        root_dir: Path | None,
        cache_dir: Path | None,
    ) -> Policy:
        writable: list[Path] = []
        if cache_dir is not None:
            writable.append(cache_dir)
        writable.append(Path(tempfile.gettempdir()))
        if is_fix:
            if root_dir is not None:
                writable.append(root_dir)
            writable.extend(targets)
        return cls(
            writable=tuple(sorted({_normalize(p) for p in writable})),
            network="network" in granted,
            subprocess="subprocess" in granted,
            native="native" in granted,
            unrestricted_writes="unrestricted_writes" in granted,
        )

    def to_json(self) -> str:
        return json.dumps({
            "writable": list(self.writable),
            "network": self.network,
            "subprocess": self.subprocess,
            "native": self.native,
            "unrestricted_writes": self.unrestricted_writes,
        })

    @classmethod
    def from_json(cls, text: str) -> Policy:
        raw = json.loads(text)
        return cls(
            writable=tuple(raw.get("writable", ())),
            network=bool(raw.get("network", False)),
            subprocess=bool(raw.get("subprocess", False)),
            native=bool(raw.get("native", False)),
            unrestricted_writes=bool(raw.get("unrestricted_writes", False)),
        )

    def wrap(self, argv: list[str]) -> list[str]:
        """Turn `[python, script, ...rule args]` into the equivalent
        invocation routed through this module's child half. `-B` keeps the
        interpreter from writing .pyc files for anything the rule imports,
        which would otherwise be a write nobody asked for, in a directory
        nobody declared."""
        interpreter, script, *rule_args = argv
        return [interpreter, "-B", "-m", __spec__.name, self.to_json(), script, *rule_args]


def child_env(env: dict[str, str] | None = None) -> dict[str, str]:
    """Environment for the wrapped child. The child starts with `-m
    fs_org_kit.sandbox`, so the package has to be importable there even
    when the runner was started from a source tree that isn't on the
    default path."""
    env = dict(os.environ if env is None else env)
    package_parent = str(Path(__file__).resolve().parent.parent)
    existing = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = f"{package_parent}{os.pathsep}{existing}" if existing else package_parent
    # A rule that crashes has its traceback captured and reported by the
    # runner as the `broken` reason. Recent Pythons colorize tracebacks,
    # which would embed escape codes in that message.
    env["NO_COLOR"] = "1"
    return env


# =====================================================================
# Child side - enforcing the policy
# =====================================================================

def _normalize(path: Path | str) -> str:
    """realpath without requiring existence, so a not-yet-created file is
    judged by the directory it would land in. Symlinks in the existing
    prefix are followed, which is what makes a symlink out of a writable
    directory not a way around the policy."""
    return os.path.realpath(os.fspath(path))


_WRITE_EVENT_PATH_ARGS = {
    # event name -> which positional args name something being written
    "os.mkdir": (0,),
    "os.rmdir": (0,),
    "os.remove": (0,),
    "os.rename": (0, 1),
    "os.replace": (0, 1),
    "os.link": (1,),
    "os.symlink": (1,),
    "os.truncate": (0,),
    "os.chmod": (0,),
    "os.chown": (0,),
    "os.utime": (0,),
    "os.setxattr": (0,),
    "os.removexattr": (0,),
    "shutil.copyfile": (1,),
    "shutil.copymode": (1,),
    "shutil.copystat": (1,),
    "shutil.copytree": (1,),
    "shutil.move": (0, 1),
    "shutil.rmtree": (0,),
    "shutil.unpack_archive": (1,),
}

_NETWORK_EVENTS = frozenset({
    "socket.connect", "socket.bind", "socket.getaddrinfo", "socket.gethostbyname",
    "socket.sendto", "socket.sethostname", "urllib.Request", "ftplib.connect",
    "smtplib.connect", "imaplib.open", "poplib.connect", "nntplib.connect",
    "http.client.connect",
})

_SUBPROCESS_EVENTS = frozenset({
    "subprocess.Popen", "os.system", "os.exec", "os.posix_spawn", "os.spawn",
    "os.fork", "os.forkpty", "pty.spawn",
})

_NATIVE_EVENTS = frozenset({
    "ctypes.dlopen", "ctypes.dlsym", "ctypes.dlsym/handle", "ctypes.call_function",
    "ctypes.addressof", "ctypes.set_exception",
})

_WATCHED = frozenset(_WRITE_EVENT_PATH_ARGS) | _NETWORK_EVENTS | _SUBPROCESS_EVENTS | _NATIVE_EVENTS | {"open"}

# Bits that mean "this open() can modify the file". os.open reports its
# raw flags and no mode string, so the flags are the only signal there.
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND

violations: list[str] = []


def _open_is_write(args: tuple) -> bool:
    mode = args[1] if len(args) > 1 else None
    if isinstance(mode, str):
        return any(c in mode for c in "wax+")
    flags = args[2] if len(args) > 2 else 0
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _install(policy: Policy) -> None:
    """Install the audit hook. Nothing before this point is policed, which
    is why the parent computes every path in the policy and the child does
    no discovery of its own."""
    writable = tuple(policy.writable)
    # Per-thread, not a plain flag: a rule that uses threads would
    # otherwise let one thread's in-progress check disable the hook for
    # another thread's operation.
    state = threading.local()

    def is_writable(target: str) -> bool:
        real = _normalize(target)
        if real in ALWAYS_WRITABLE_FILES:
            return True
        return any(real == w or real.startswith(w + os.sep) for w in writable)

    def deny(what: str) -> None:
        violations.append(what)
        raise SandboxViolation(what)

    def hook(event: str, args: tuple) -> None:
        if event not in _WATCHED or getattr(state, "busy", False):
            return
        state.busy = True
        try:
            if event in _NETWORK_EVENTS:
                if not policy.network:
                    deny(f"network access ({event}) - declare [sandbox] network = true to allow it")
                return
            if event in _SUBPROCESS_EVENTS:
                if not policy.subprocess:
                    deny(f"running another process ({event}) - declare [sandbox] subprocess = true to allow it")
                return
            if event in _NATIVE_EVENTS:
                if not policy.native:
                    deny(f"a native/ctypes call ({event}) - declare [sandbox] native = true to allow it")
                return
            if policy.unrestricted_writes:
                return
            if event == "open":
                if _open_is_write(args) and _is_path(args[0]) and not is_writable(args[0]):
                    deny(f"write to {os.fspath(args[0])!s}")
                return
            for index in _WRITE_EVENT_PATH_ARGS[event]:
                # A non-path argument here is a file descriptor, and the
                # open() that produced it already passed this same check -
                # denying it again would only reject legitimate work.
                if len(args) > index and _is_path(args[index]) and not is_writable(args[index]):
                    deny(f"{event} on {os.fspath(args[index])!s}")
        finally:
            state.busy = False

    sys.addaudithook(hook)


def _is_path(value: object) -> bool:
    return isinstance(value, (str, bytes, os.PathLike))


def _describe(policy: Policy) -> str:
    allowed = [name for name in CAPABILITIES if getattr(policy, name)]
    where = ", ".join(policy.writable) or "nowhere"
    granted = f"; granted: {', '.join(allowed)}" if allowed else ""
    return f"writable: {where}{granted}"


def main(argv: list[str] | None = None) -> int:
    """Child entry point: `python -m fs_org_kit.sandbox <policy-json>
    <script> [rule args...]`.

    Deliberately not argparse - every argument after the script belongs to
    the rule, and argparse would try to interpret the ones that look like
    its own flags."""
    argv = list(sys.argv[1:] if argv is None else argv)
    if len(argv) < 2:
        print(f"usage: python -m {__spec__.name} <policy-json> <script> [args...]", file=sys.stderr)
        return 2

    policy = Policy.from_json(argv[0])
    script = argv[1]
    sys.argv = [script, *argv[2:]]
    sys.dont_write_bytecode = True

    # Running a script directly puts its own directory on sys.path;
    # runpy.run_path does not (it only rewrites sys.path[0] for the
    # importer-based cases, not for a plain .py file). Without this, a
    # rule split across more than one file - staleness-v1 imports a
    # _shared module beside it - runs standalone but not under the
    # sandbox, which would make the harness look like the bug.
    sys.path.insert(0, str(Path(script).resolve().parent))

    import runpy  # imported before the hook is installed, so its own reads aren't policed

    _install(policy)
    try:
        runpy.run_path(script, run_name="__main__")
    except SystemExit as e:
        code = e.code
        status = 0 if code is None else (code if isinstance(code, int) else 1)
    except SandboxViolation as e:
        print(f"sandbox: blocked {e} [{_describe(policy)}]", file=sys.stderr)
        return 1
    else:
        status = 0

    if violations:
        # Reached only if the script caught the violation and carried on -
        # `except BaseException` or a bare `except:`. The invocation still
        # fails, so a swallowed violation can't be reported as success.
        print(
            f"sandbox: blocked {violations[0]} [{_describe(policy)}] "
            f"- the rule script suppressed this and continued",
            file=sys.stderr,
        )
        return 1
    return status


if __name__ == "__main__":
    raise SystemExit(main())
