"""Break-glass ESXi STIG rule application helpers.

Supports the `stig-apply` CLI command: reads a raw STIG artifact to find
failing rules, then drives ansible-playbook once per rule with interactive
confirmation between each step.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

from .normalization.stig import normalize_stig

# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

SKELETON_PATH = Path(__file__).parent / "cklb_skeletons" / "cklb_skeleton_vsphere7_esxi_V1R4.json"


class RuleMetadata:
    """Lightweight view of one CKLB rule entry."""

    def __init__(self, raw: dict[str, Any]) -> None:
        self.rule_version: str = raw.get("rule_version", "")
        self.rule_title: str = raw.get("rule_title", "")
        self.group_id: str = raw.get("group_id", "")
        self.severity: str = raw.get("severity", "medium")
        self.fix_text: str = raw.get("fix_text", "")

    @property
    def manage_var(self) -> str:
        return rule_version_to_manage_var(self.rule_version)


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def rule_version_to_manage_var(rule_version: str) -> str:
    """Convert rule_version string to Ansible manage-var name.

    Examples:
        'ESXI-70-000001' -> 'esxi_70_000001_Manage'
    """
    return re.sub(r"[-]", "_", rule_version).lower() + "_Manage"


def load_esxi_rule_metadata(skeleton_path: Path = SKELETON_PATH) -> dict[str, RuleMetadata]:
    """Read the CKLB skeleton and return a dict keyed by rule_version."""
    with open(skeleton_path) as f:
        data: dict[str, Any] = json.load(f)
    rules: list[dict[str, Any]] = data["stigs"][0]["rules"]
    return {r["rule_version"]: RuleMetadata(r) for r in rules}


def generate_all_disabled_vars(metadata: dict[str, RuleMetadata]) -> dict[str, bool]:
    """Return a dict with every _Manage var set to False."""
    return {meta.manage_var: False for meta in metadata.values()}


def build_group_id_map(metadata: dict[str, RuleMetadata]) -> dict[str, str]:
    """Return a mapping of group_id (V-NNNNNN) → rule_version (ESXI-70-NNNNNN).

    Used to resolve V-format identifiers written by the stig_xml callback into
    the ESXI-70-* rule versions needed to drive ansible-playbook.
    """
    return {meta.group_id: rv for rv, meta in metadata.items() if meta.group_id}


def get_failing_rules(artifact_path: Path) -> list[dict[str, Any]]:
    """Read a raw_stig_esxi.yaml artifact and return normalized rows with status='open'."""
    with open(artifact_path) as f:
        raw: Any = yaml.safe_load(f)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping in {artifact_path}, got {type(raw).__name__}")

    result = normalize_stig(raw, stig_target_type="esxi")
    return [dict(row) for row in result.full_audit if row.get("status") == "open"]


def _infer_rule_version(row: dict[str, Any], group_id_map: dict[str, str] | None = None) -> str:
    """Try to pull an ESXI-70-NNNNNN version string out of a normalized row.

    Resolution order:
      1. Direct ``rule_version`` key (set by ncs_collector artifacts that include it).
      2. Any field whose value already matches the ESXI-70-\\d+ pattern.
      3. V-NNNNNN group_id lookup via the skeleton map (produced by the stig_xml
         callback, which writes rows with ``id: V-256376`` style identifiers).
    """
    if rv := row.get("rule_version", ""):
        return str(rv)
    for key in ("rule_id", "id", "vuln_id"):
        val = str(row.get(key, ""))
        if re.match(r"ESXI-70-\d+", val, re.IGNORECASE):
            return val.upper()
    if group_id_map:
        for key in ("id", "rule_id", "vuln_id"):
            val = str(row.get(key, ""))
            if val in group_id_map:
                return group_id_map[val]
    return ""


def build_ansible_args(
    *,
    playbook: str,
    inventory: str,
    limit: str,
    manage_var: str,
    all_disabled_file: str,
    esxi_host: str,
    tags: list[str] | None = None,
    skip_tags: list[str] | None = None,
    extra_vars: tuple[str, ...] = (),
) -> list[str]:
    """Construct the ansible-playbook argument list for a single rule application."""
    cmd = [
        "ansible-playbook",
        playbook,
        "-i", inventory,
        "-l", limit,
        f"-e@{all_disabled_file}",
        f"-e{manage_var}=true",
        "-evmware_stig_enable_hardening=true",
        f"-eesxi_stig_target_hosts=['{esxi_host}']",
    ]
    if tags:
        cmd += ["--tags", ",".join(tags)]
    if skip_tags:
        cmd += ["--skip-tags", ",".join(skip_tags)]
    for ev in extra_vars:
        cmd += ["-e", ev]
    return cmd


def run_ansible_streaming(args: list[str]) -> int:
    """Run ansible-playbook, streaming stdout/stderr to the terminal.

    Returns the process exit code.
    """
    proc = subprocess.Popen(args, stdout=sys.stdout, stderr=sys.stderr)
    proc.wait()
    return proc.returncode


# ---------------------------------------------------------------------------
# Interactive loop
# ---------------------------------------------------------------------------


def _prompt_yn_abort(message: str) -> str:
    """Prompt for y/n/abort. Returns 'y', 'n', or 'abort'."""
    import click

    while True:
        val = click.prompt(message, default="n").strip().lower()
        if val in ("y", "yes"):
            return "y"
        if val in ("n", "no"):
            return "n"
        if val in ("a", "abort", "q", "quit"):
            return "abort"
        click.echo("  Enter y, n, or abort.")


def _rule_banner(index: int, total: int, rule_version: str, meta: RuleMetadata | None, row: dict[str, Any]) -> str:
    """Return a formatted rule banner string."""
    sep = "─" * 65
    severity = (meta.severity if meta else row.get("severity", "unknown")).upper()
    title = (meta.rule_title if meta else row.get("title", "Unknown Rule"))
    finding = row.get("description") or row.get("checktext") or row.get("details") or ""
    fix = (meta.fix_text[:120] + "…") if meta and len(meta.fix_text) > 120 else (meta.fix_text if meta else "")

    lines = [
        sep,
        f"Rule {index}/{total}: {rule_version}  │  {severity}",
        f"Title:   {title}",
    ]
    if finding:
        lines.append(f"Finding: {finding[:200]}")
    if fix:
        lines.append(f"Fix:     {fix}")
    lines.append(sep)
    return "\n".join(lines)


def run_interactive_apply(
    *,
    artifact: Path,
    playbook: str,
    inventory: str,
    limit: str,
    esxi_host: str,
    skip_snapshot: bool,
    post_audit: bool,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Main entry point for the interactive break-glass apply loop."""
    import click

    metadata = load_esxi_rule_metadata()
    group_id_map = build_group_id_map(metadata)
    failing_rows = get_failing_rules(artifact)

    if not failing_rows:
        click.echo("No failing (open) rules found in artifact. Nothing to apply.")
        return

    click.echo(f"\nFound {len(failing_rows)} failing rule(s).")

    # --- Pre-hardening snapshot ---
    # ESXi hosts cannot be snapshotted like VMs; the playbook's snapshot phase only
    # acts on vm_stig_target_vms (which is empty here). Inform the user and skip.
    if not skip_snapshot:
        click.echo(
            "Note: Pre-hardening snapshots are not applicable for ESXi host hardening "
            "(ESXi hosts cannot be snapshotted). Snapshot phase skipped. "
            "Use --skip-snapshot to suppress this message."
        )

    # Build the all-disabled vars file once
    all_disabled = generate_all_disabled_vars(metadata)

    applied: list[str] = []
    skipped: list[str] = []
    total = len(failing_rows)

    # Skip the snapshot and vm plays; also skip the post-remediation audit play
    # unless the caller explicitly wants per-rule confirmation via --post-audit.
    per_rule_skip_tags = ["snapshot", "vm"]
    if not post_audit:
        per_rule_skip_tags.append("audit")

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".yaml", prefix="ncs_stig_disabled_", delete=False
    ) as tmp:
        yaml.dump(all_disabled, tmp)
        disabled_file = tmp.name

    try:
        for idx, row in enumerate(failing_rows, 1):
            rule_version = _infer_rule_version(row, group_id_map)
            meta = metadata.get(rule_version) if rule_version else None

            if not rule_version:
                click.echo(f"\n[{idx}/{total}] Could not determine rule_version for row: {row.get('rule_id', '?')} — skipping.")
                skipped.append(row.get("rule_id", "?"))
                continue

            click.echo("\n" + _rule_banner(idx, total, rule_version, meta, row))

            answer = _prompt_yn_abort("Apply this rule? [y/n/abort]")
            if answer == "abort":
                click.echo("Aborted by user.")
                break
            if answer == "n":
                skipped.append(rule_version)
                click.echo(f"Skipped {rule_version}.")
                continue

            manage_var = rule_version_to_manage_var(rule_version)
            ansible_args = build_ansible_args(
                playbook=playbook,
                inventory=inventory,
                limit=limit,
                manage_var=manage_var,
                all_disabled_file=disabled_file,
                esxi_host=esxi_host,
                skip_tags=per_rule_skip_tags,
                extra_vars=extra_vars,
            )

            if dry_run:
                click.echo(f"[DRY-RUN] Would run: {' '.join(ansible_args)}")
                applied.append(rule_version)
            else:
                rc = run_ansible_streaming(ansible_args)
                click.echo(f"\nAnsible exited with code {rc}.")
                applied.append(rule_version)

            if idx < total:
                cont = _prompt_yn_abort("Continue to next rule? [y/n/abort]")
                if cont != "y":
                    click.echo("Stopping early.")
                    break

    finally:
        Path(disabled_file).unlink(missing_ok=True)

    # Summary
    click.echo("\n" + "=" * 65)
    click.echo(f"Summary: {len(applied)} applied, {len(skipped)} skipped")
    if applied:
        click.echo("  Applied: " + ", ".join(applied))
    if skipped:
        click.echo("  Skipped: " + ", ".join(skipped))
