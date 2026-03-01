"""Break-glass ESXi STIG rule application helpers.

Supports the `stig-apply` CLI command: reads a raw STIG artifact to find
failing rules, then generates a single Ansible playbook with ``pause`` tasks
for interactive per-rule confirmation.  One vCenter connection is established
for the entire session, reducing per-rule overhead from ~15-25 s (subprocess
spawn + vCenter auth each time) to ~2-5 s (role invocation within a warm play).
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

# Rules that require a non-empty config var when enabled (from stig.yaml Phase 0 assert).
# Derived directly from the assertions in internal.vmware.esxi/tasks/stig.yaml.
RULE_REQUIRED_VARS: dict[str, str] = {
    "ESXI-70-000004": "esxi_stig_syslog_host",
    "ESXI-70-000007": "esxi_stig_welcome_message",
    "ESXI-70-000039": "esxi_stig_ad_admin_group",
    "ESXI-70-000045": "esxi_stig_log_dir",
    "ESXI-70-000046": "esxi_stig_ntp_servers",
}


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


def check_rule_config_vars(
    rule_versions: list[str],
    extra_vars: tuple[str, ...] = (),
) -> list[tuple[str, str]]:
    """Return (rule_version, required_var) pairs where the required config var is not
    present in the supplied ``extra_vars``.

    Only ``key=value`` style extra-vars are parsed; ``@file`` forms and bare flags are
    ignored.  A missing entry is a *warning*, not an error — the variable may already
    be supplied by inventory or group_vars.
    """
    supplied: set[str] = set()
    for ev in extra_vars:
        if "=" in ev and not ev.startswith("@"):
            key, _, _ = ev.partition("=")
            supplied.add(key.strip())

    return [(rv, var) for rv in rule_versions if (var := RULE_REQUIRED_VARS.get(rv)) and var not in supplied]


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
    """Construct the ansible-playbook argument list for a single rule application.

    Retained for backwards-compatibility and direct testing; the main
    ``run_interactive_apply`` path now uses ``build_interactive_playbook`` instead.
    """
    cmd = [
        "ansible-playbook",
        playbook,
        "-i",
        inventory,
        "-l",
        limit,
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


def build_interactive_playbook(
    failing_rows: list[dict[str, Any]],
    metadata: dict[str, RuleMetadata],
    group_id_map: dict[str, str],
    *,
    esxi_host: str,
    post_audit: bool = False,  # noqa: ARG001  (reserved for future per-rule post-check)
) -> str:
    """Generate a single Ansible playbook YAML with ``pause`` tasks for interactive application.

    The generated play:
    - Sets all 75 ``_Manage`` vars to ``false`` at play level.
    - For each failing rule: emits a debug banner, a ``pause`` prompt, an abort
      ``fail`` guard, and an ``include_role`` that enables only that rule.
    - Targets ``esxi_stig_target_hosts`` at play-vars level so every role call
      uses the same ESXi host without re-specifying it.

    One vCenter connection is established by the first role invocation and
    reused for all subsequent roles, making per-rule time ~2-5 s vs ~15-25 s
    with the old one-subprocess-per-rule approach.
    """
    all_disabled = generate_all_disabled_vars(metadata)

    resolved: list[tuple[str, RuleMetadata | None, dict[str, Any]]] = []
    for row in failing_rows:
        rv = _infer_rule_version(row, group_id_map)
        if rv:
            resolved.append((rv, metadata.get(rv), row))

    total = len(resolved)
    tasks: list[dict[str, Any]] = []

    for idx, (rule_version, meta, row) in enumerate(resolved, 1):
        pause_var = f"_ncs_pause_{idx}"
        manage_var = rule_version_to_manage_var(rule_version)
        severity = (meta.severity if meta else row.get("severity", "?")).upper()
        # Embed the banner in the pause prompt. Ansible's pause module writes
        # the prompt via os.write (direct stdout), so real newlines render
        # correctly — unlike debug: msg: which JSON-encodes them as \n.
        banner = _rule_banner(idx, total, rule_version, meta, row)
        prompt = f"{banner}\nApply rule {idx}/{total} {rule_version} ({severity})? [y/n/abort]"

        tasks.append(
            {
                "name": f"NCS | Confirm: {rule_version} [{severity}]",
                "ansible.builtin.pause": {"prompt": prompt},
                "register": pause_var,
            }
        )
        tasks.append(
            {
                "name": f"NCS | Abort check: {rule_version}",
                "ansible.builtin.fail": {"msg": "Aborted by user."},
                "when": f"{pause_var}.user_input | lower in ['a', 'abort', 'q', 'quit']",
            }
        )
        tasks.append(
            {
                "name": f"NCS | Apply {rule_version}",
                "ansible.builtin.include_role": {"name": "internal.vmware.esxi"},
                "vars": {manage_var: True},
                "when": f"{pause_var}.user_input | lower in ['y', 'yes']",
            }
        )

    play: dict[str, Any] = {
        "name": f"NCS ESXi STIG Apply — {total} failing rule(s) on {esxi_host}",
        "hosts": "all",
        "connection": "local",
        "gather_facts": False,
        "vars": {
            **all_disabled,
            "vmware_stig_enable_hardening": True,
            "esxi_stig_target_hosts": [esxi_host],
        },
        "tasks": tasks,
    }

    return str(yaml.dump([play], default_flow_style=False, sort_keys=False, allow_unicode=True))


def run_ansible_streaming(args: list[str]) -> int:
    """Run ansible-playbook, streaming stdout/stderr to the terminal.

    Returns the process exit code.
    """
    proc = subprocess.Popen(args, stdout=sys.stdout, stderr=sys.stderr)
    proc.wait()
    return proc.returncode


# ---------------------------------------------------------------------------
# Interactive loop helpers
# ---------------------------------------------------------------------------


def _rule_banner(index: int, total: int, rule_version: str, meta: RuleMetadata | None, row: dict[str, Any]) -> str:
    """Return a formatted rule banner string."""
    sep = "─" * 65
    severity = (meta.severity if meta else row.get("severity", "unknown")).upper()
    title = meta.rule_title if meta else row.get("title", "Unknown Rule")
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
    inventory: str,
    limit: str,
    esxi_host: str,
    skip_snapshot: bool,
    post_audit: bool,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Main entry point for the interactive break-glass apply loop.

    Generates a single Ansible playbook with ``ansible.builtin.pause`` tasks
    (one per failing rule) and runs it once.  Interactive prompts are handled
    natively inside Ansible so the vCenter connection stays warm across rules,
    reducing per-rule time from ~15-25 s to ~2-5 s.
    """
    import click

    metadata = load_esxi_rule_metadata()
    group_id_map = build_group_id_map(metadata)
    failing_rows = get_failing_rules(artifact)

    if not failing_rows:
        click.echo("No failing (open) rules found in artifact. Nothing to apply.")
        return

    click.echo(f"\nFound {len(failing_rows)} failing rule(s).")

    # ESXi hosts cannot be snapshotted like VMs; inform the user and move on.
    if not skip_snapshot:
        click.echo(
            "Note: Pre-hardening snapshots are not applicable for ESXi host hardening "
            "(ESXi hosts cannot be snapshotted). Snapshot phase skipped. "
            "Use --skip-snapshot to suppress this message."
        )

    # Warn about rules that require config vars not supplied via --extra-vars.
    resolved_versions = [_infer_rule_version(row, group_id_map) for row in failing_rows]
    missing = check_rule_config_vars([rv for rv in resolved_versions if rv], extra_vars)
    if missing:
        click.echo("\nWarning: the following failing rules require config vars not found in --extra-vars")
        click.echo("(they may already be set in inventory/group_vars, otherwise the role will assert-fail):\n")
        for rv, var in missing:
            click.echo(f"  {rv}  →  needs  {var}  (supply with -e {var}=<value>)")
        click.echo("")

    playbook_yaml = build_interactive_playbook(
        failing_rows,
        metadata,
        group_id_map,
        esxi_host=esxi_host,
        post_audit=post_audit,
    )

    if dry_run:
        click.echo("[DRY-RUN] Generated playbook:")
        click.echo(playbook_yaml)
        return

    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", prefix="ncs_stig_apply_", delete=False) as tmp:
        tmp.write(playbook_yaml)
        playbook_file = tmp.name

    try:
        args = ["ansible-playbook", playbook_file, "-i", inventory, "-l", limit]
        for ev in extra_vars:
            args += ["-e", ev]
        rc = run_ansible_streaming(args)
        click.echo(f"\nAnsible exited with code {rc}.")
    finally:
        Path(playbook_file).unlink(missing_ok=True)
