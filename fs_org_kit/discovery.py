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
returned list rather than exceptions. The only things that raise are
problems with the *tool itself* (an unreadable rule.template.toml),
since discovery genuinely cannot proceed without knowing the schema.
"""

from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


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
    dir_path: Path
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
    exclude: list[str] = field(default_factory=list)
    params_names: list[str] = field(default_factory=list)
    params_defaults: dict = field(default_factory=dict)

    @property
    def has_fixer(self) -> bool:
        return self.fix_script is not None


RULE_DIR_PATTERN = re.compile(r"^(?P<name>.+)-v(?P<major>\d+)$")


def _load_rule_schema(rule_template_path: Path) -> tuple[frozenset[str], frozenset[str]]:
    """Read enums.severity / enums.scope from rule.template.toml, so the
    set of valid values lives in one place instead of being duplicated
    here and risking drift if the template ever changes."""
    try:
        with rule_template_path.open("rb") as f:
            data = tomllib.load(f)
    except (OSError, tomllib.TOMLDecodeError) as e:
        raise RuntimeError(f"cannot read rule schema from {rule_template_path}: {e}") from e

    severity_values = frozenset(data.get("enums", {}).get("severity", {}).keys())
    scope_values = frozenset(data.get("enums", {}).get("scope", {}).keys())
    if not severity_values or not scope_values:
        raise RuntimeError(f"{rule_template_path} is missing enums.severity or enums.scope")
    return severity_values, scope_values


def _scan_tier(
    tier_dir: Path,
    tier: Tier,
    severity_values: frozenset[str],
    scope_values: frozenset[str],
) -> tuple[dict[str, RuleEntry], list[DiscoveryIssue]]:
    """Scan one tier directory for rule subdirectories."""
    entries: dict[str, RuleEntry] = {}
    issues: list[DiscoveryIssue] = []

    if not tier_dir.is_dir():
        return entries, issues  # tier doesn't exist yet - not an error

    for child in sorted(tier_dir.iterdir()):
        if child.name.startswith(".") or child.name == "__pycache__":
            continue

        if not child.is_dir():
            issues.append(DiscoveryIssue(
                IssueLevel.WARNING, tier, None,
                f"unexpected file '{child.name}' in {tier.value} rules directory, ignored",
            ))
            continue

        match = RULE_DIR_PATTERN.match(child.name)
        if not match:
            issues.append(DiscoveryIssue(
                IssueLevel.WARNING, tier, child.name,
                "directory name doesn't match <name>-v<major>, ignored",
            ))
            continue

        rule_id = child.name
        dir_major = match.group("major")

        manifest_path = child / f"{rule_id}.toml"
        if not manifest_path.is_file():
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"no manifest found, expected {rule_id}.toml",
            ))
            continue

        try:
            with manifest_path.open("rb") as f:
                manifest = tomllib.load(f)
        except tomllib.TOMLDecodeError as e:
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"{manifest_path.name} is not valid TOML: {e}",
            ))
            continue

        check_script = child / f"{rule_id}-check.py"
        if not check_script.is_file():
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"no checker script found, expected {rule_id}-check.py",
            ))
            continue

        fix_script_candidate = child / f"{rule_id}-fix.py"
        fix_script = fix_script_candidate if fix_script_candidate.is_file() else None

        version = manifest.get("version")
        if not version or "." not in str(version):
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"manifest 'version' missing or malformed: {version!r}",
            ))
            continue
        manifest_major = str(version).split(".", 1)[0]
        if manifest_major != dir_major:
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"manifest version major ({manifest_major}) doesn't match "
                f"directory suffix -v{dir_major}",
            ))
            continue

        severity = manifest.get("severity", "info")
        if severity not in severity_values:
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"severity {severity!r} not one of {sorted(severity_values)}",
            ))
            continue

        scope = manifest.get("scope", "single")
        if scope not in scope_values:
            issues.append(DiscoveryIssue(
                IssueLevel.ERROR, tier, rule_id,
                f"scope {scope!r} not one of {sorted(scope_values)}",
            ))
            continue

        overrides_bundled = bool(manifest.get("overrides_bundled", False))
        if overrides_bundled and tier == Tier.EXTERNAL:
            issues.append(DiscoveryIssue(
                IssueLevel.WARNING, tier, rule_id,
                "external-tier rule claims overrides_bundled = true; ignored - "
                "an unverified rule can never override another rule's identity",
            ))
            overrides_bundled = False

        params = manifest.get("params", {})

        entries[rule_id] = RuleEntry(
            rule_id=rule_id,
            tier=tier,
            dir_path=child,
            manifest_path=manifest_path,
            check_script=check_script,
            fix_script=fix_script,
            version=str(version),
            purpose=str(manifest.get("purpose", "")),
            severity=severity,
            scope=scope,
            protocol_version=str(manifest.get("protocol_version", "1.0")),
            overrides_bundled=overrides_bundled,
            uses_cache=bool(manifest.get("uses_cache", False)),
            exclude=list(manifest.get("exclude", [])),
            params_names=list(params.get("names", [])),
            params_defaults=dict(params.get("defaults", {})),
        )

    return entries, issues


def discover_rules(
    standard_dir: Path,
    bundled_rules_dir: Optional[Path] = None,
    include_external: bool = False,
    rule_template_path: Optional[Path] = None,
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
    rule_template_path Defaults to the repo's own rule.template.toml.

    Precedence:
      - own overrides bundled ONLY if the own rule's manifest sets
        overrides_bundled = true. Without it, a same-name collision with
        a bundled rule is a warning and the bundled version stays
        authoritative; the own rule is not loaded.
      - external NEVER overrides anything - not bundled, not own -
        regardless of any overrides_bundled it claims (that claim is
        itself flagged and ignored).
    """
    repo_root = Path(__file__).resolve().parent.parent
    if bundled_rules_dir is None:
        bundled_rules_dir = repo_root / "rules"
    if rule_template_path is None:
        rule_template_path = repo_root / "rule.template.toml"

    severity_values, scope_values = _load_rule_schema(rule_template_path)

    all_issues: list[DiscoveryIssue] = []

    bundled_entries, bundled_issues = _scan_tier(
        bundled_rules_dir, Tier.BUNDLED, severity_values, scope_values)
    all_issues.extend(bundled_issues)

    own_entries, own_issues = _scan_tier(
        standard_dir / "rules.own", Tier.OWN, severity_values, scope_values)
    all_issues.extend(own_issues)

    external_entries: dict[str, RuleEntry] = {}
    if include_external:
        external_entries, external_issues = _scan_tier(
            standard_dir / "rules.external", Tier.EXTERNAL, severity_values, scope_values)
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
