"""Interactive STIG rule application helpers.

Supports the `stig-apply` CLI command:
- ESXi artifacts: interactive per-rule apply in one warm Ansible session.
- Other supported targets (VM, VCSA, Photon, Ubuntu): interactive confirmation
  then playbook-level remediation for the target host.
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
from .platform_registry import default_registry

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

SUPPORTED_TARGET_TYPES: set[str] = default_registry().all_target_types()


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
        'ESXI-70-000001' -> 'esxi_70_000001_manage'
    """
    return re.sub(r"[-]", "_", rule_version).lower() + "_manage"


def load_esxi_rule_metadata(skeleton_path: Path = SKELETON_PATH) -> dict[str, RuleMetadata]:
    """Read the CKLB skeleton and return a dict keyed by rule_version."""
    with open(skeleton_path) as f:
        data: dict[str, Any] = json.load(f)
    rules: list[dict[str, Any]] = data["stigs"][0]["rules"]
    return {r["rule_version"]: RuleMetadata(r) for r in rules}


def generate_all_disabled_vars(metadata: dict[str, RuleMetadata]) -> dict[str, bool]:
    """Return a dict with every _manage var set to False."""
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


def load_stig_artifact(artifact_path: Path) -> dict[str, Any] | list[dict[str, Any]]:
    """Read a STIG artifact YAML and return parsed content."""
    with open(artifact_path) as f:
        raw: Any = yaml.safe_load(f)
    if not isinstance(raw, (dict, list)):
        raise ValueError(f"Expected a YAML mapping/list in {artifact_path}, got {type(raw).__name__}")
    return raw


def detect_target_type(
    raw: dict[str, Any] | list[dict[str, Any]],
    artifact_path: Path,
    override: str = "",
) -> str:
    """Detect STIG target type from override, payload, metadata, filename, or row prefixes."""
    if override:
        return override.strip().lower()

    detected = ""
    if isinstance(raw, dict):
        detected = str(raw.get("target_type") or "").strip().lower()
        if detected:
            return detected
        audit_type = str((raw.get("metadata") or {}).get("audit_type") or "").strip().lower()
        if audit_type.startswith("stig_"):
            return audit_type.replace("stig_", "", 1)

    stem = artifact_path.stem.lower()
    if stem.startswith("raw_stig_"):
        return stem.replace("raw_stig_", "", 1)

    rows: list[dict[str, Any]] = []
    if isinstance(raw, list):
        rows = [r for r in raw if isinstance(r, dict)]
    elif isinstance(raw, dict):
        data = raw.get("data") or raw.get("full_audit") or []
        if isinstance(data, list):
            rows = [r for r in data if isinstance(r, dict)]

    if rows:
        rv = str(rows[0].get("rule_version") or "").upper()
        inferred = default_registry().infer_target_type_from_rule_prefix(rv)
        if inferred:
            return inferred
    return ""


def infer_target_host(raw: dict[str, Any] | list[dict[str, Any]]) -> str:
    """Infer hostname for target-scoped remediation vars."""
    if isinstance(raw, dict):
        host = str((raw.get("metadata") or {}).get("host") or "").strip()
        if host:
            return host
        data = raw.get("data") or raw.get("full_audit") or []
        if isinstance(data, list) and data:
            first = data[0]
            if isinstance(first, dict):
                return str(first.get("name") or "").strip()
    if isinstance(raw, list) and raw:
        first = raw[0]
        if isinstance(first, dict):
            return str(first.get("name") or "").strip()
    return ""


def get_failing_rules(
    artifact_path: Path,
    stig_target_type: str = "esxi",
) -> list[dict[str, Any]]:
    """Read a STIG artifact and return normalized rows with status='open'."""
    raw = load_stig_artifact(artifact_path)
    if not isinstance(raw, dict):
        raise ValueError(f"Expected a YAML mapping in {artifact_path}, got {type(raw).__name__}")
    result = normalize_stig(raw, stig_target_type=stig_target_type)
    return [dict(row) for row in result.full_audit if row.get("status") == "open"]


def resolve_generic_apply_plan(target_type: str) -> tuple[str, str | None]:
    """Return (playbook_path, target_var_name)."""
    t = target_type.lower()
    if t == "vm":
        return ("playbooks/vm/stig_remediate.yml", "vm_stig_target_vms")
    if t in {"vcsa", "vcenter"}:
        return ("playbooks/vcsa/stig_remediate.yml", "vcsa_stig_target_hosts")
    if t == "photon":
        return ("playbooks/photon_stig_remediate.yml", "photon_target_hosts")
    if t in {"ubuntu", "linux"}:
        return ("playbooks/ubuntu_stig_remediate.yml", "ubuntu_target_hosts")
    raise ValueError(f"Unsupported target type for generic apply: {target_type}")


def build_generic_apply_args(
    *,
    playbook: str,
    inventory: str,
    limit: str,
    target_var: str | None,
    target_host: str,
    extra_vars: tuple[str, ...] = (),
) -> list[str]:
    """Construct ansible-playbook args for non-ESXi STIG apply."""
    cmd = ["ansible-playbook", playbook, "-i", inventory, "-l", limit]
    if target_var and target_host:
        cmd.append(f"-e{target_var}=['{target_host}']")
    for ev in extra_vars:
        cmd += ["-e", ev]
    return cmd


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
        "-eesxi_stig_enable_hardening=true",
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
    - Sets all 75 ``_manage`` vars to ``false`` at play level.
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
            "esxi_stig_enable_hardening": True,
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


def run_generic_interactive_apply(
    *,
    artifact: Path,
    inventory: str,
    limit: str,
    target_type: str,
    target_host: str,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Interactive apply for non-ESXi targets via target-specific remediation playbook."""
    import click

    if target_type.lower() not in SUPPORTED_TARGET_TYPES - {"esxi"}:
        raise click.ClickException(
            f"Unsupported target type '{target_type}'. Supported: esxi, vm, vcsa, photon, ubuntu."
        )

    failing_rows = get_failing_rules(artifact, stig_target_type=target_type.lower())
    if not failing_rows:
        click.echo("No failing (open) rules found in artifact. Nothing to apply.")
        return

    playbook, target_var = resolve_generic_apply_plan(target_type)
    click.echo(f"\nDetected target_type={target_type.lower()} with {len(failing_rows)} failing rule(s).")
    if target_var and target_host:
        click.echo(f"Target host: {target_host}")

    if not dry_run:
        answer = click.prompt("Proceed with remediation playbook apply? [y/n/abort]", default="n", show_default=False)
        if str(answer).strip().lower() not in {"y", "yes"}:
            click.echo("Aborted.")
            return

    args = build_generic_apply_args(
        playbook=playbook,
        inventory=inventory,
        limit=limit,
        target_var=target_var,
        target_host=target_host,
        extra_vars=extra_vars,
    )

    if dry_run:
        click.echo("[DRY-RUN] Generated apply command:")
        click.echo(" ".join(args))
        return

    rc = run_ansible_streaming(args)
    click.echo(f"\nAnsible exited with code {rc}.")
