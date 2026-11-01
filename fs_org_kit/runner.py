#!/usr/bin/env python3
"""
runner.py - validates a populated standard, then runs every attached rule's
checker (or fixer, in --fix mode) against the real filesystem.

Usage:
    python -m fs_org_kit.runner path/to/your-file.toml
    python -m fs_org_kit.runner path/to/your-file.toml --fix
    python -m fs_org_kit.runner path/to/your-file.toml --include-external
    python -m fs_org_kit.runner path/to/your-file.toml --rules-dir /path/to/bundled/rules
    python -m fs_org_kit.runner path/to/your-file.toml --no-color

The standard is validated first (reusing fs_org_kit.validator) - a standard
with structural errors is never run against the real filesystem. The
resolved rule catalog from that validation pass (bundled + own + optional
external, with collisions already settled) is reused directly rather than
running discovery a second time.

What gets resolved into invocations:
    - per-path attachments:        [[paths."x/".rules.<name>]]
    - blanket path attachments:    [[paths.rules.<name>]] - every
      *cataloged* path (every path with its own [paths."..."] entry)
    - cross-path attachments:      [[paths.cross.rules.<name>]]
    - blanket folder attachments:  [[folders.rules.<name>]] - ONE
      invocation, on root. The rule's own params do the walking:
      exclusions, recursion, and which folders count are specified by the
      rule, not the runner (see doc/DESIGN.md, "Recursive rule invocation
      on folders").
    - reserved-name attachments:   [[folders.reserved."_x".rules.<name>]] -
      once per folder actually NAMED _x, anywhere under root. A reserved
      entry describes what a name means wherever it appears, so its
      target set comes from a name match on disk rather than from a
      catalog key. A folder that is both a reserved name and its own
      [paths."..."] entry gets both sets of rules - they answer different
      questions ("what _arch means anywhere" vs "what prj/_arch is"), the
      same way a per-path attachment and [[folders.rules]] already
      coexist on one folder.

A param value may be {ref = "dotted.path"} instead of a literal - see
fs_org_kit.param_refs - substituted with whatever is at that path
elsewhere in the standard, verbatim. Applied uniformly to every
invocation regardless of which rule or param it's on; the runner has no
per-rule knowledge of what any param means, and reshapes nothing on the
way through.

A [paths."..."] key may be a glob pattern instead of a literal path -
see fs_org_kit.path_patterns - expanded here against the real
filesystem into zero, one, or many real targets, each sharing that
entry's fields/rule attachments. Pattern-overlap between two catalog
keys is caught by the validator (a static, disk-free check); this
module only ever expands one key at a time against real disk state, and
treats a pattern matching nothing the same way a literal path treats
not existing: it contributes no invocations, silently.

Checker/fixer protocol - see doc/RULES.md for the authoritative
version:
    scope=single -> --path <one path>
    scope=cross  -> --paths <path> [--paths <path> ...] (2 or more)
    scope=both   -> the script itself must accept both and validate them
    always:        --params '<json object>'
    fixer only:    --fix (never passed to a checker)
    uses_cache:    --cache-dir <dir>, only for rules declaring
                   uses_cache = true in their manifest. The core owns
                   the location (fs_org_kit.cache) so it keeps an
                   inventory it can list and clear; a rule never picks
                   its own. Omitted if the directory can't be created,
                   in which case the rule must run uncached.
    stdout: exactly one JSON line -
        {"status": "ok"} | {"status": "violation", "message": "..."}
        | {"status": "fixed", "message": "..."} | {"status": "unfixable", "message": "..."}
    exit 0 = ran fine, read stdout. nonzero = the script itself is broken.

Every invocation runs inside the audit-hook harness in
fs_org_kit.sandbox unless --no-sandbox is passed: no network, no
subprocess, no native calls, and no writes beyond the rule's own cache
directory and the system temp directory - plus, in --fix mode, root and
that invocation's own target path(s). A rule needing more declares it in
its manifest's [sandbox] table, the same way uses_cache declares a need
for storage; the runner reads the declaration and never special-cases a
rule by name. It's a guard against accidents, not a security boundary -
see the sandbox module's own docstring for what it can't do.

In --fix mode, a rule with a fixer is invoked via its -fix.py directly
(not checked first, then fixed) - the fixer is expected to detect and
resolve in one self-contained pass, per the protocol's four-status
contract. A rule with no fixer still runs its checker normally in --fix
mode; fix mode doesn't skip rules that can't be fixed, it just can't fix
them.

Targets are expanded once, up front, so a fixer can move or delete a
folder that a later invocation in the same pass was already planned
against. Such an invocation is reported `skipped` rather than run - the
status is the runner's alone, never something a script can return, and it
doesn't affect the exit code. Its target isn't re-checked in that pass:
the plan was fixed before the move, so wherever the folder landed was
expanded before it arrived. Run again for the settled state.

Exit codes:
    0  every invocation came back ok, fixed, or skipped (or there was nothing to run)
    1  at least one violation, unfixable, or broken invocation
    2  the standard could not be read, or had structural validation errors
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fs_org_kit.cache import ensure_rule_cache_dir
from fs_org_kit.discovery import RuleEntry
from fs_org_kit.fields import iter_rule_instances
from fs_org_kit.inherit import ResolvedEntry, RuleAttachment
from fs_org_kit.param_refs import expand_params
from fs_org_kit.path_keys import resolve_key
from fs_org_kit.path_patterns import expand_pattern, is_pattern
from fs_org_kit.sandbox import Policy, child_env, child_io_env
from fs_org_kit.validator import (
    StandardLoadError, add_discovery_args, load_and_validate, should_color, use_utf8_output,
)

DEFAULT_TIMEOUT_SECONDS = 30.0

_COLOR = {
    "violation": "\033[33m",
    "unfixable": "\033[31m",
    "broken": "\033[31m",
    "fixed": "\033[32m",
    "skipped": "\033[2m",
    "reset": "\033[0m",
    "dim": "\033[2m",
}


# ---------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------

@dataclass
class Invocation:
    rule_id: str
    entry: RuleEntry
    location: str          # dotted TOML location, for reporting
    reason: str
    params: dict[str, Any]
    target_path: Path | None = None
    target_paths: list[Path] | None = None
    # which targets were really on disk when the plan was built, stamped
    # by collect_invocations. Distinguishes "a fixer moved this" (skip)
    # from "this was never here" (a misconfigured attachment, which must
    # still reach the script and be reported broken). None means the
    # Invocation was built outside collect_invocations (tests), where
    # there's no snapshot to compare against.
    present_at_plan: frozenset[Path] | None = None
    # carried per-invocation so the sandbox can tell a fixer which tree it
    # was pointed at; None only when an Invocation is built outside the
    # normal collect_invocations path (tests), where root is unknowable
    root_dir: Path | None = None

    @property
    def targets(self) -> list[Path]:
        if self.target_path is not None:
            return [self.target_path]
        return list(self.target_paths or [])

    def target_display(self, relative_to: Path) -> str:
        """The target(s) as shown in a report line. Each is relativized on
        its own: joining first and relativizing the joined string never
        matches, so every cross-scope invocation would silently fall back
        to absolute paths and report in a different format from every
        single-target one."""
        def shorten(p: Path) -> str:
            try:
                return str(p.relative_to(relative_to))
            except ValueError:
                return str(p)  # genuinely outside (e.g. root elsewhere) - show absolute
        return ", ".join(shorten(p) for p in self.targets)


@dataclass
class RunResult:
    invocation: Invocation
    status: str      # "ok" | "violation" | "fixed" | "unfixable" | "broken" | "skipped"
    message: str = ""


# ---------------------------------------------------------------------
# Resolving the standard into invocations
# ---------------------------------------------------------------------

def _resolve_params(entry: RuleEntry, inst: dict[str, Any]) -> dict[str, Any]:
    inst_params = inst.get("params", {})
    if not isinstance(inst_params, dict):
        inst_params = {}
    return {**entry.params_defaults, **inst_params}


# One (rule_id, entry, index, instance dict, origin_note) tuple per
# attachment, from either shape a rules table comes in - a raw TOML dict
# (instance(s) still plain dicts) or an already-inheritance-resolved one
# (RuleAttachment objects). Every call site that builds Invocations reads
# instances this way first, so "what counts as one attachment" can't
# drift between them.

def _iter_raw_instances(
    rules_table: Any, catalog: dict[str, RuleEntry]
) -> Iterator[tuple[str, RuleEntry, int, dict[str, Any], str | None]]:
    for rule_id, instances in iter_rule_instances(rules_table):
        entry = catalog.get(rule_id)
        if entry is None:
            continue  # already reported by the validation pass, skip silently here
        for i, inst in enumerate(instances):
            if isinstance(inst, dict):
                yield rule_id, entry, i, inst, None


def _iter_resolved_instances(
    resolved_rules: dict[str, list[RuleAttachment]], catalog: dict[str, RuleEntry]
) -> Iterator[tuple[str, RuleEntry, int, dict[str, Any], str | None]]:
    for rule_id, attachments in resolved_rules.items():
        entry = catalog.get(rule_id)
        if entry is None:
            continue  # already reported by the validation pass, skip silently here
        for i, attachment in enumerate(attachments):
            yield rule_id, entry, i, attachment.instance, attachment.origin_note


def _emit(
    invocations: list[Invocation],
    rule_id: str,
    entry: RuleEntry,
    index: int,
    inst: dict[str, Any],
    origin_note: str | None,
    loc_prefix: str,
    *,
    target_path: Path | None = None,
    target_paths: list[Path] | None = None,
) -> None:
    reason = inst.get("reason", "")
    params = _resolve_params(entry, inst)
    loc = f"{loc_prefix}.rules.{rule_id}[{index}]{origin_note or ''}"
    invocations.append(Invocation(rule_id, entry, loc, reason, params, target_path=target_path, target_paths=target_paths))


def _add_invocations(
    invocations: list[Invocation],
    attachments: Iterator[tuple[str, RuleEntry, int, dict[str, Any], str | None]],
    targets: list[Path],
    loc_prefix: str,
) -> None:
    """One invocation per (attachment, target). Callers pass either
    iterator above, which is why both yield the same 5-tuple: whether an
    attachment came from raw TOML or from inheritance changes nothing
    about how it turns into invocations."""
    for rule_id, entry, i, inst, origin_note in attachments:
        for abs_path in targets:
            _emit(invocations, rule_id, entry, i, inst, origin_note, loc_prefix, target_path=abs_path)


def _resolve_active_targets(
    resolved_paths: dict[str, ResolvedEntry], root_dir: Path
) -> list[tuple[str, Path]]:
    """The cataloged paths that exist on disk right now - the only ones
    any rule gets invoked against. One that isn't there is simply skipped:
    a catalog is a description of where things go, not an assertion that
    every location currently exists, and "this path should exist" is a
    question for a rule, not for the runner.

    A glob-style key (fs_org_kit.path_patterns) can produce zero, one,
    or many (key, abs_path) tuples from one catalog entry - every real
    match shares that entry's resolved fields/rules, invoked once
    per match, the same way a [folders.reserved."_x"] entry is invoked
    once per folder named _x. ([[folders.rules]] is the other shape: one
    invocation, on root, with the rule's own params doing the walking.)

    A real match that's ALSO its own explicit literal catalog entry is
    excluded from the pattern's own expansion - the validator only lets
    a literal overlap a pattern through when that literal explicitly
    inherits from it (see Validator._check_pattern_overlaps), so by the
    time the runner runs, any such overlap is guaranteed sanctioned:
    the literal entry's own resolved fields/rules (already including
    whatever it inherited) are authoritative for that one real folder,
    not a second, separate invocation via the pattern."""
    # resolve_key ends in a realpath syscall chain, so each literal key is
    # resolved once here and read twice below
    literals = {key: resolve_key(root_dir, key) for key in resolved_paths if not is_pattern(key)}
    literal_abs_paths = set(literals.values())
    active: list[tuple[str, Path]] = []
    for key in resolved_paths:
        if is_pattern(key):
            active.extend((key, m) for m in expand_pattern(root_dir, key) if m not in literal_abs_paths)
        elif literals[key].is_dir():
            active.append((key, literals[key]))
    return active


def _find_reserved_folders(root_dir: Path, names: set[str]) -> dict[str, list[Path]]:
    """One walk of the tree, collecting every folder whose own name is one
    of the reserved names. A reserved entry is a NAME, not a location, so
    this is the only place its targets can come from - unlike a catalog
    key, there's nothing to resolve without looking.

    Symlinks aren't followed (a link back up the tree would otherwise
    walk forever), and a match isn't pruned: a reserved folder nested
    inside another one is still that name appearing in the tree, and the
    entry says it means the same thing wherever it appears."""
    found: dict[str, list[Path]] = {name: [] for name in names}
    if not names or not root_dir.is_dir():
        return found
    for dirpath, dirnames, _filenames in os.walk(root_dir, followlinks=False):
        dirnames.sort()
        for dirname in dirnames:
            if dirname in found:
                found[dirname].append(Path(dirpath) / dirname)
    return found


def collect_invocations(
    data: dict[str, Any],
    root_dir: Path,
    catalog: dict[str, RuleEntry],
    resolved_paths: dict[str, ResolvedEntry],
    resolved_folders: dict[str, ResolvedEntry] | None = None,
) -> list[Invocation]:
    """Walk the standard and build one Invocation per (rule, target)
    pair. A cataloged path that isn't on disk contributes none."""
    invocations: list[Invocation] = []
    paths = data.get("paths", {})

    active_targets = _resolve_active_targets(resolved_paths, root_dir)

    # per-path attachments - resolved rules already include inherited +
    # excluded + this entry's own, merged
    for key, abs_path in active_targets:
        resolved = resolved_paths[key]
        _add_invocations(
            invocations, _iter_resolved_instances(resolved.rules, catalog), [abs_path], f'paths."{key}"'
        )

    # paths.rules blanket - every *cataloged* path that currently exists.
    # The blanket table itself isn't an entry that can use `inherit`, so
    # this stays on the raw-dict path, same as before.
    _add_invocations(
        invocations, _iter_raw_instances(paths.get("rules"), catalog),
        [abs_path for _key, abs_path in active_targets], "paths",
    )

    # paths.cross
    for i, cross in enumerate(paths.get("cross", [])):
        if not isinstance(cross, dict):
            continue
        rules_table = cross.get("rules")
        referenced = cross.get("paths", [])
        if not isinstance(rules_table, dict) or not referenced:
            continue
        abs_paths = [resolve_key(root_dir, p) for p in referenced if isinstance(p, str)]
        for rule_id, entry, j, inst, origin_note in _iter_raw_instances(rules_table, catalog):
            _emit(invocations, rule_id, entry, j, inst, origin_note, f"paths.cross[{i}]", target_paths=abs_paths)

    # folders.rules blanket - apply to root itself
    # the rule's own params control recursion, exclusion, etc.
    folders_rules = data.get("folders", {}).get("rules")
    for rule_id, entry, j, inst, origin_note in _iter_raw_instances(folders_rules, catalog):
        _emit(invocations, rule_id, entry, j, inst, origin_note, "folders", target_path=root_dir)

    # folders.reserved."_x".rules - once per folder named _x on disk. The
    # entries are already inheritance-resolved (a reserved entry can
    # inherit from another reserved entry), so this reuses the same
    # resolved-rules path individual [paths."..."] entries take. A
    # reserved name that matches nothing on disk simply contributes no
    # invocations, the same as a cataloged path that isn't there.
    if resolved_folders:
        with_rules = {name: r for name, r in resolved_folders.items() if r.rules}
        for name, matches in _find_reserved_folders(root_dir, set(with_rules)).items():
            if not matches:
                continue
            _add_invocations(
                invocations, _iter_resolved_instances(with_rules[name].rules, catalog),
                matches, f'folders.reserved."{name}"',
            )

    # {ref = "dotted.path"} param values (see fs_org_kit.param_refs) are
    # expanded here, once, regardless of which of the four attachment
    # shapes above produced the invocation - the validator has already
    # confirmed every reference resolves, so no error handling is needed
    # on this side.
    for inv in invocations:
        inv.params, _ = expand_params(inv.params, data)
        inv.root_dir = root_dir
        # one snapshot of what the plan was built against, so a target
        # that disappears later can be told apart from one that was
        # never there (see _stale_target). Path-derived targets are
        # already filtered to what exists; paths.cross resolves its
        # references directly, so this is the only check they get.
        inv.present_at_plan = frozenset(p for p in inv.targets if p.is_dir())

    return invocations


# ---------------------------------------------------------------------
# Invoking rule scripts
# ---------------------------------------------------------------------

def invoke_script(
    script: Path,
    invocation: Invocation,
    is_fix: bool,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sandboxed: bool = True,
) -> RunResult:
    argv = [sys.executable, str(script)]
    if invocation.target_path is not None:
        argv += ["--path", str(invocation.target_path)]
    else:
        for p in invocation.target_paths or []:
            argv += ["--paths", str(p)]
    argv += ["--params", json.dumps(invocation.params)]
    if is_fix:
        argv.append("--fix")
    cache_dir = None
    if invocation.entry.uses_cache:
        # The core owns the location; the rule is handed a ready-made,
        # rule-private directory rather than resolving one itself (see
        # fs_org_kit.cache). If it can't be created, the flag is simply
        # omitted and the rule runs uncached - slower, never wrong.
        cache_dir = ensure_rule_cache_dir(invocation.rule_id)
        if cache_dir is not None:
            argv += ["--cache-dir", str(cache_dir)]

    env = None
    if sandboxed:
        # The policy is built here, in the parent, from the manifest's
        # declared capabilities plus this invocation's own targets - the
        # child does no discovery of its own, since anything it worked out
        # after the hook was installed would have to be exempted from it.
        policy = Policy.for_invocation(
            set(invocation.entry.sandbox),
            is_fix=is_fix,
            targets=invocation.targets,
            root_dir=invocation.root_dir,
            cache_dir=cache_dir,
        )
        argv = policy.wrap(argv)
        env = child_env()

    try:
        result = subprocess.run(
            argv, capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout, env=child_io_env(env),
        )
    except subprocess.TimeoutExpired:
        return RunResult(invocation, "broken", f"timed out after {timeout:.0f}s")
    except OSError as e:
        return RunResult(invocation, "broken", f"failed to launch: {e}")

    if result.returncode != 0:
        reason = result.stderr.strip() or result.stdout.strip() or f"exited {result.returncode} with no output"
        return RunResult(invocation, "broken", reason)

    try:
        payload = json.loads(result.stdout.strip())
    except json.JSONDecodeError:
        return RunResult(invocation, "broken", f"did not print exactly one JSON line on stdout: {result.stdout!r}")
    if not isinstance(payload, dict):
        # valid JSON, wrong shape - `[]` or `"ok"` must cost this one
        # invocation, not crash the run and hide every other result
        return RunResult(invocation, "broken", f"stdout JSON is not an object: {payload!r}")

    status = payload.get("status")
    if status not in ("ok", "violation", "fixed", "unfixable"):
        return RunResult(invocation, "broken", f"unrecognized status in JSON output: {payload!r}")

    return RunResult(invocation, status, payload.get("message", ""))


def _stale_target(invocation: Invocation) -> str | None:
    """Why this invocation's plan no longer matches disk, or None if it
    still does.

    collect_invocations expands every target up front, from one snapshot,
    so a fixer running earlier in the same pass can move or delete a
    folder that a later invocation was already planned against - moving a
    stale project into archive/ is a fixer doing its job, not a mistake.
    Handing the vanished path to the script anyway makes it exit nonzero,
    which the protocol reads as "the script itself is broken": the one
    signal reserved for a rule that's genuinely misconfigured. Checking
    here keeps that signal meaning what it says."""
    targets = invocation.targets
    present = invocation.present_at_plan
    for p in targets:
        if p.is_dir():
            continue
        if present is not None and p not in present:
            # absent when the plan was built too, so nothing moved it -
            # an attachment naming somewhere that isn't there. Let the
            # script run and report it broken, exactly as before.
            continue
        what = "is no longer a directory" if p.exists() else "no longer exists"
        # the report line already names a single target - saying which one
        # only adds anything when several share the one invocation
        where = f"{p} " if len(targets) > 1 else ""
        return f"{where}{what} (moved or removed during this run)"
    return None


def run_invocation(
    invocation: Invocation,
    fix_requested: bool,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    sandboxed: bool = True,
) -> RunResult:
    stale = _stale_target(invocation)
    if stale is not None:
        return RunResult(invocation, "skipped", stale)
    entry = invocation.entry
    if fix_requested and entry.has_fixer:
        return invoke_script(entry.fix_script, invocation, is_fix=True, timeout=timeout, sandboxed=sandboxed)
    return invoke_script(entry.check_script, invocation, is_fix=False, timeout=timeout, sandboxed=sandboxed)


# ---------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------

def _format_result(result: RunResult, standard_dir: Path, color: bool) -> str:
    tag = result.status.upper()
    target = result.invocation.target_display(standard_dir)
    if color and result.status in _COLOR:
        c = _COLOR[result.status]
        tag = f"{c}{tag}{_COLOR['reset']}"
    line = f"{result.invocation.location}: [{tag}] {result.invocation.rule_id} ({target})"
    if result.message:
        line += f": {result.message}"
    return line


def _print_summary(results: list[RunResult], color: bool) -> None:
    counts = {"ok": 0, "violation": 0, "fixed": 0, "unfixable": 0, "broken": 0, "skipped": 0}
    for r in results:
        counts[r.status] = counts.get(r.status, 0) + 1

    print("Summary")
    for status in ("ok", "violation", "fixed", "unfixable", "broken", "skipped"):
        n = counts[status]
        label = status.rjust(9)
        if color and status in _COLOR and n:
            print(f"  {_COLOR[status]}{label}{_COLOR['reset']}  {n}")
        else:
            print(f"  {label}  {n}")
    print(f"\n{len(results)} invocation(s) total")


# ---------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
    )
    parser.add_argument("path", type=Path, help="path to a populated fs-org-std.toml")
    parser.add_argument("--fix", action="store_true", help="invoke fixers where available, instead of just reporting")
    add_discovery_args(parser)
    parser.add_argument("--no-color", action="store_true", help="disable colored output")
    parser.add_argument(
        "--no-sandbox", action="store_true",
        help="run rule scripts directly, without the audit-hook harness (fs_org_kit.sandbox) that "
             "blocks network, subprocess, native calls, and out-of-policy writes",
    )
    parser.add_argument(
        "--timeout", type=float, default=DEFAULT_TIMEOUT_SECONDS,
        help=f"seconds allowed per rule invocation before it's treated as broken (default {DEFAULT_TIMEOUT_SECONDS:.0f}s) "
             f"- raise this for fixers that shell out to slow external tools (e.g. audio transcoding)",
    )
    args = parser.parse_args(argv)
    use_utf8_output()

    try:
        data, validator, warnings = load_and_validate(
            args.path, include_external=args.include_external,
            bundled_rules_dir=args.rules_dir, before="running rules",
        )
    except StandardLoadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    standard_dir = args.path.resolve().parent
    color = should_color(args.no_color)

    if warnings:
        note = f"standard validated: 0 errors, {len(warnings)} warning(s) (run the validator directly for details)"
        print(f"{_COLOR['dim']}{note}{_COLOR['reset']}\n" if color else f"{note}\n")

    root = data.get("root", "")
    root_dir = resolve_key(standard_dir, root) if root else standard_dir

    invocations = collect_invocations(
        data, root_dir, validator.rule_catalog, validator.resolved_paths, validator.resolved_folders
    )

    if not invocations:
        print("no rule attachments to run")
        return 0

    # Each result is printed as it arrives, not after the whole pass: a
    # run that dies or is interrupted partway must still show what the
    # fixers before that point already changed on disk.
    results = []
    for inv in invocations:
        result = run_invocation(inv, args.fix, timeout=args.timeout, sandboxed=not args.no_sandbox)
        results.append(result)
        if result.status != "ok":
            print(_format_result(result, standard_dir, color), flush=True)

    print()
    _print_summary(results, color)

    if any(r.status in ("violation", "unfixable", "broken") for r in results):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
