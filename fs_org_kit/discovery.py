"""
fs_org_kit.discovery - finds and catalogs rules across the three trust
tiers (bundled, own, external), and resolves collisions between them
per the precedence policy below. See doc/DESIGN.md, "Discovery is
centralized".

The validator, runner, and doc generator all import this rather than
re-implementing tier/precedence logic themselves - one place to get it
right, not three places that can quietly drift out of sync.

Never raises for a single malformed rule - a bad manifest, a missing
checker script, a name collision, all become DiscoveryIssues in the
returned list rather than exceptions.

This module also owns the manifest schema (see MANIFEST_KEYS, SEVERITY,
SCOPE below): which fields a rule manifest may carry, what they default
to, and the two vocabularies discovery checks. That's the tool's half of
the runner<->rule contract, not something a standard configures - a
`severity` nobody implemented is a value nothing downstream could act
on. See doc/DESIGN.md, "The rule manifest schema lives in code".
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

from fs_org_kit.sandbox import capabilities_for


class Tier(str, Enum):
    BUNDLED = "bundled"
    OWN = "own"
    EXTERNAL = "external"


class IssueLevel(str, Enum):
    ERROR = "error"
    WARNING = "warning"


@dataclass(frozen=True)
class DiscoveryIssue:
    level: IssueLevel
    tier: Optional[Tier]
    rule_id: Optional[str]  # directory name, when known
    message: str

    def __str__(self) -> str:
        location = self.tier.value if self.tier else "discovery"
        if self.rule_id:
            location = f"{location}/{self.rule_id}"
        return f"[{self.level.value.upper()}] {location}: {self.message}"


@dataclass(frozen=True)
class RuleEntry:
    rule_id: str  # e.g. "file-extensions-v1" - the directory name, verbatim
    tier: Tier
    manifest_path: Path
    check_script: Path
    fix_script: Optional[Path]
    version: str
    purpose: str
    severity: str
    scope: str
    protocol_version: str
    overrides_bundled: bool
    uses_cache: bool = False
    # capability names this rule's [sandbox] table grants - see
    # fs_org_kit.sandbox. Empty means the default policy applies: no
    # network, no subprocess, no native calls, and writes confined to the
    # rule's cache plus (in --fix mode) root and its own targets.
    sandbox: frozenset[str] = frozenset()
    params_names: list[str] = field(default_factory=list)
    params_defaults: dict = field(default_factory=dict)

    @property
    def has_fixer(self) -> bool:
        return self.fix_script is not None


RULE_DIR_PATTERN = re.compile(r"^(?P<name>.+)-v(?P<major>\d+)$")

# A leading underscore disables a rule directory in every tier: it is not
# loaded, not checked, and not reported. That's what makes the bundled
# `_template-*-v1/` rules copyable starting points rather than rules that
# run against everyone's filesystem, and it gives a user somewhere to
# park a half-written rule without deleting it.
DISABLED_PREFIX = "_"

# Valid `severity` values, and what each one means. Both vocabularies are
# closed and live here rather than in a file a user could edit: a value
# the tool doesn't implement is a value nothing can act on.
SEVERITY = {
    "none": "deliberately silenced - never reported, regardless of any default",
    "info": "worth noting, no action expected",
    "warn": "should be addressed, but nothing is broken yet",
    "error": "the standard is actively violated and needs correction",
}

SCOPE = {
    "single": "invoked once per path - takes --path, exactly one location",
    "cross": "invoked once per cross-path set - takes --paths, 2 or more locations",
    "both": "attachable either way - the script must accept both flags and validate them itself",
}

# Protocol majors this runner knows how to invoke a rule script with. An
# additive set, not a single "current" value like SUPPORTED_SCHEMA_MAJOR:
# rules are numerous and independently maintained (bundled, own, and
# especially external, on someone else's update schedule), so a wire-format
# bump must not stop every rule that hasn't migrated yet from working. Grows
# when a new major ships; only shrinks if an old wire format is deliberately
# retired. See doc/VERSIONING.md.
SUPPORTED_PROTOCOL_MAJORS = frozenset({"1"})

# Every top-level key a manifest may carry. Anything else is a typo doing
# nothing, so discovery says so instead of ignoring it silently. Defaults
# are applied where each field is read below; a field absent from this
# set has no reader and therefore no meaning.
MANIFEST_KEYS = frozenset({
    "version", "purpose", "severity", "scope", "protocol_version",
    "overrides_bundled", "uses_cache", "sandbox", "params",
})


def _scan_tier(
    tier_dir: Path,
    tier: Tier,
) -> tuple[dict[str, RuleEntry], list[DiscoveryIssue]]:
    """Scan one tier directory for rule subdirectories. Deciding what is
    even a candidate lives here; deciding whether a candidate is a valid
    rule lives in _load_rule."""
    entries: dict[str, RuleEntry] = {}
    issues: list[DiscoveryIssue] = []

    if not tier_dir.is_dir():
        return entries, issues  # tier doesn't exist yet - not an error

    for child in sorted(tier_dir.iterdir()):
        if child.name.startswith((".", DISABLED_PREFIX)):
            continue  # disabled, or an editor/interpreter artifact (__pycache__)

        if not child.is_dir():
            issues.append(DiscoveryIssue(
                IssueLevel.WARNING, tier, None,
                f"unexpected file '{child.name}' in {tier.value} rules directory, ignored",
            ))
            continue

        entry, child_issues = _load_rule(child, tier)
        issues.extend(child_issues)
        if entry is not None:
            entries[entry.rule_id] = entry

    return entries, issues


def _load_rule(child: Path, tier: Tier) -> tuple[RuleEntry | None, list[DiscoveryIssue]]:
    """Validate one candidate rule directory into a RuleEntry, or None if
    it isn't a usable rule. Every check that reads the manifest is here,
    so adding a manifest field means touching exactly this function."""
    issues: list[DiscoveryIssue] = []

    def reject(level: IssueLevel, rule_id: str | None, message: str) -> tuple[None, list[DiscoveryIssue]]:
        issues.append(DiscoveryIssue(level, tier, rule_id, message))
        return None, issues

    match = RULE_DIR_PATTERN.match(child.name)
    if not match:
        return reject(IssueLevel.WARNING, child.name, "directory name doesn't match <name>-v<major>, ignored")

    rule_id = child.name
    dir_major = match.group("major")

    manifest_path = child / f"{rule_id}.toml"
    if not manifest_path.is_file():
        return reject(IssueLevel.ERROR, rule_id, f"no manifest found, expected {rule_id}.toml")

    try:
        with manifest_path.open("rb") as f:
            manifest = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        return reject(IssueLevel.ERROR, rule_id, f"{manifest_path.name} is not valid TOML: {e}")

    for key in sorted(set(manifest) - MANIFEST_KEYS):
        issues.append(DiscoveryIssue(
            IssueLevel.WARNING, tier, rule_id,
            f"unknown manifest field '{key}', ignored - nothing reads it "
            f"(valid: {', '.join(sorted(MANIFEST_KEYS))})",
        ))

    check_script = child / f"{rule_id}-check.py"
    if not check_script.is_file():
        return reject(IssueLevel.ERROR, rule_id, f"no checker script found, expected {rule_id}-check.py")

    fix_script_candidate = child / f"{rule_id}-fix.py"
    fix_script = fix_script_candidate if fix_script_candidate.is_file() else None

    version = manifest.get("version")
    if not version or "." not in str(version):
        return reject(IssueLevel.ERROR, rule_id, f"manifest 'version' missing or malformed: {version!r}")
    manifest_major = str(version).split(".", 1)[0]
    if manifest_major != dir_major:
        return reject(
            IssueLevel.ERROR, rule_id,
            f"manifest version major ({manifest_major}) doesn't match directory suffix -v{dir_major}",
        )

    protocol_version = manifest.get("protocol_version", "1.0")
    if not protocol_version or "." not in str(protocol_version):
        return reject(IssueLevel.ERROR, rule_id, f"manifest 'protocol_version' malformed: {protocol_version!r}")
    protocol_major = str(protocol_version).split(".", 1)[0]
    if protocol_major not in SUPPORTED_PROTOCOL_MAJORS:
        # A warning, not an error: unlike a broken manifest, this isn't a
        # mistake to fix - it resolves itself once either side is updated.
        # The rule is still excluded from the catalog (never added below),
        # but that exclusion doesn't block the rest of the standard from
        # validating - only an attachment that actually references this
        # rule will fail, at that specific site.
        return reject(
            IssueLevel.WARNING, rule_id,
            f"protocol_version {protocol_version!r} (major {protocol_major}) isn't one this runner "
            f"speaks (supports major {'/'.join(sorted(SUPPORTED_PROTOCOL_MAJORS))}) - excluded from "
            "the catalog until either side is updated",
        )

    severity = manifest.get("severity", "info")
    if severity not in SEVERITY:
        return reject(IssueLevel.ERROR, rule_id, f"severity {severity!r} not one of {sorted(SEVERITY)}")

    scope = manifest.get("scope", "single")
    if scope not in SCOPE:
        return reject(IssueLevel.ERROR, rule_id, f"scope {scope!r} not one of {sorted(SCOPE)}")

    overrides_bundled = bool(manifest.get("overrides_bundled", False))
    if overrides_bundled and tier == Tier.EXTERNAL:
        issues.append(DiscoveryIssue(
            IssueLevel.WARNING, tier, rule_id,
            "external-tier rule claims overrides_bundled = true; ignored - "
            "an unverified rule can never override another rule's identity",
        ))
        overrides_bundled = False

    sandbox_grants, sandbox_complaints = capabilities_for(manifest.get("sandbox"))
    for complaint in sandbox_complaints:
        issues.append(DiscoveryIssue(IssueLevel.WARNING, tier, rule_id, complaint))
    if sandbox_grants and tier == Tier.EXTERNAL:
        # Honored, unlike overrides_bundled - an external rule asking for
        # a capability isn't claiming another rule's identity, and
        # silently denying it would only produce a confusing runtime
        # failure with no way forward. Said out loud, though: the point
        # of the external tier is that nobody vouched for this rule.
        issues.append(DiscoveryIssue(
            IssueLevel.WARNING, tier, rule_id,
            f"external-tier rule grants itself [sandbox] "
            f"{', '.join(sorted(sandbox_grants))} - review the rule before relying on it",
        ))

    params = manifest.get("params", {})

    return RuleEntry(
        rule_id=rule_id,
        tier=tier,
        manifest_path=manifest_path,
        check_script=check_script,
        fix_script=fix_script,
        version=str(version),
        purpose=str(manifest.get("purpose", "")),
        severity=severity,
        scope=scope,
        protocol_version=str(protocol_version),
        overrides_bundled=overrides_bundled,
        uses_cache=bool(manifest.get("uses_cache", False)),
        sandbox=frozenset(sandbox_grants),
        params_names=list(params.get("names", [])),
        params_defaults=dict(params.get("defaults", {})),
    ), issues


def discover_rules(
    standard_dir: Path,
    bundled_rules_dir: Optional[Path] = None,
    include_external: bool = False,
) -> tuple[dict[str, RuleEntry], list[DiscoveryIssue]]:
    """
    Find every rule across the three trust tiers and merge them into one
    catalog.

    standard_dir       parent of rules.own/ and rules.external/ - normally
                        the directory containing the fs-org-std.toml being
                        processed.
    bundled_rules_dir  fs-org-kit's own rules/. Defaults to the repo's
                        rules/ directory, assuming an unpackaged checkout -
                        revisit this default once real install paths are
                        settled (see doc/DESIGN.md, "Packaging and CLI
                        Commands").
    include_external   rules.external/ is not even scanned unless this is
                        True - existing on disk must not mean running.

    A rule directory whose name starts with "_" is skipped in every tier,
    silently - that's how the bundled templates stay out of the catalog.

    Precedence:
      - own overrides bundled ONLY if the own rule's manifest sets
        overrides_bundled = true. Without it, a same-name collision with
        a bundled rule is a warning and the bundled version stays
        authoritative; the own rule is not loaded.
      - external NEVER overrides anything - not bundled, not own -
        regardless of any overrides_bundled it claims (that claim is
        itself flagged and ignored).
    """
    if bundled_rules_dir is None:
        bundled_rules_dir = Path(__file__).resolve().parent.parent / "rules"

    all_issues: list[DiscoveryIssue] = []

    bundled_entries, bundled_issues = _scan_tier(bundled_rules_dir, Tier.BUNDLED)
    all_issues.extend(bundled_issues)

    own_entries, own_issues = _scan_tier(standard_dir / "rules.own", Tier.OWN)
    all_issues.extend(own_issues)

    external_entries: dict[str, RuleEntry] = {}
    if include_external:
        external_entries, external_issues = _scan_tier(
            standard_dir / "rules.external", Tier.EXTERNAL)
        all_issues.extend(external_issues)

    catalog: dict[str, RuleEntry] = dict(bundled_entries)

    for rule_id, own_entry in own_entries.items():
        if rule_id in catalog:
            if own_entry.overrides_bundled:
                catalog[rule_id] = own_entry
            else:
                all_issues.append(DiscoveryIssue(
                    IssueLevel.WARNING, Tier.OWN, rule_id,
                    "same name as a bundled rule; bundled stays authoritative "
                    f"(set overrides_bundled = true in {own_entry.manifest_path.name} "
                    "to replace it intentionally)",
                ))
        else:
            catalog[rule_id] = own_entry

    for rule_id, ext_entry in external_entries.items():
        if rule_id in catalog:
            all_issues.append(DiscoveryIssue(
                IssueLevel.WARNING, Tier.EXTERNAL, rule_id,
                f"same name as an existing {catalog[rule_id].tier.value} rule; "
                "external rules can never override another rule, ignored",
            ))
        else:
            catalog[rule_id] = ext_entry

    return catalog, all_issues


if __name__ == "__main__":
    # Manual smoke-test entry point - not the intended way to run discovery
    # in normal use, just a quick way to eyeball a catalog while developing.
    import sys

    std_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path.cwd()
    include_ext = "--include-external" in sys.argv

    found, found_issues = discover_rules(std_dir, include_external=include_ext)

    print(f"Discovered {len(found)} rule(s):")
    for rid, entry in sorted(found.items()):
        fixer = "yes" if entry.has_fixer else "no"
        print(f"  {rid:30s} tier={entry.tier.value:9s} severity={entry.severity:6s} "
              f"scope={entry.scope:7s} fixer={fixer}")

    if found_issues:
        print(f"\n{len(found_issues)} issue(s):")
        for issue in found_issues:
            print(f"  {issue}")
