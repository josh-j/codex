"""NCS Reporter CLI entry point."""

from __future__ import annotations

import logging
from pathlib import Path

import click
import yaml

from ._config import default_paths
from ._report_context import (
    generate_timestamps,
    get_jinja_env,
    load_hosts_data,
    load_yaml,
    report_context,
)
from ._renderers import PlatformRenderConfig, render_platform
from .aggregation import load_all_reports, write_output
from .platform_registry import default_registry
from .schema_loader import discover_schemas
from .view_models.generic import build_generic_node_view
from .view_models.site import build_site_dashboard_view

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# CLI group
# ---------------------------------------------------------------------------


@click.group()
@click.option("--verbose", "-v", is_flag=True, default=False, help="Enable debug-level logging.")
def main(verbose: bool) -> None:
    """NCS Reporter: Standalone reporting CLI for Codex."""
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.WARNING,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True,
    )


# ---------------------------------------------------------------------------
# validate-config
# ---------------------------------------------------------------------------


@main.command("validate-config")
@click.option(
    "--platforms-config", "-P",
    type=click.Path(exists=True), default=None,
    help="Path to platforms.yaml config.",
)
def validate_config(platforms_config: str | None) -> None:
    """Validate a platforms config file."""
    from ._config import load_platforms

    try:
        entries = load_platforms(platforms_config)
    except click.ClickException:
        raise
    except Exception as exc:
        raise click.ClickException(str(exc)) from exc

    seen: set[str] = set()
    renderable = [p for e in entries if e.get("render", True) for p in [e["platform"]] if p not in seen and not seen.add(p)]  # type: ignore[func-returns-value]
    click.echo(f"Valid! {len(entries)} platform entries.")
    click.echo(f"  Renderable platforms: {', '.join(renderable)}")


# ---------------------------------------------------------------------------
# Single-platform commands (linux, vmware, windows)
# ---------------------------------------------------------------------------


def _platform_command(platform: str, input_file: str, output_dir: str, report_stamp: str | None) -> None:
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)
    report_dir = default_registry().platform_to_report_dir(platform) or platform
    render_platform(
        platform,
        hosts_data,
        output_path,
        common_vars,
        config=PlatformRenderConfig(
            report_dir=report_dir,
            platform_paths=default_paths(),
        ),
    )
    click.echo(f"Done! Reports generated in {output_dir}")


def _register_platform_commands() -> None:
    """Dynamically register per-platform CLI commands from the default registry."""
    for p_name in default_registry().all_platform_names():
        display = default_registry().platform_display_name(p_name)

        @main.command(name=p_name)
        @click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
        @click.option("--output-dir", "-o", required=True, type=click.Path())
        @click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
        @click.pass_context
        def _cmd(ctx: click.Context, input_file: str, output_dir: str, report_stamp: str | None,
                 _platform: str = p_name, _display: str = display) -> None:
            f"""Generate {_display} fleet and node reports."""
            _platform_command(_platform, input_file, output_dir, report_stamp)

        _cmd.__doc__ = f"Generate {display} fleet and node reports."


_register_platform_commands()


# ---------------------------------------------------------------------------
# site
# ---------------------------------------------------------------------------


@main.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp", help="Report timestamp (YYYYMMDD).")
def site(input_file: str, output_dir: str, report_stamp: str | None) -> None:
    """Generate Global Site Health dashboard."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    data = load_yaml(input_file)
    common_vars = generate_timestamps(report_stamp)

    from .models.platforms_config import FILENAME_SITE_HEALTH, TEMPLATE_SITE
    click.echo("Rendering Global Site Health dashboard...")
    site_view = build_site_dashboard_view(data, ctx=report_context(common_vars))
    env = get_jinja_env()
    content = env.get_template(TEMPLATE_SITE).render(site_dashboard_view=site_view, **common_vars)
    (output_path / FILENAME_SITE_HEALTH).write_text(content)
    click.echo(f"Done! Global dashboard generated in {output_dir}")


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------


@main.command()
@click.option("--report-dir", required=True, type=click.Path(exists=True))
@click.option("--output", required=True, type=click.Path())
@click.option("--filter", "audit_filter")
def collect(report_dir: str, output: str, audit_filter: str | None) -> None:
    """Aggregate host YAML reports into a single fleet state file."""
    click.echo(f"Aggregating reports from {report_dir}...")
    data = load_all_reports(report_dir, audit_filter=audit_filter)
    if data:
        write_output(data, output)
        click.echo(f"Success: Aggregated {len(data['hosts'])} hosts into {output}")
    else:
        click.echo("Error: No data found or directory invalid.")


# ---------------------------------------------------------------------------
# node
# ---------------------------------------------------------------------------


@main.command()
@click.option("--platform", "-p", required=True, type=click.Choice(default_registry().all_platform_names()))
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--hostname", "-n", required=True)
@click.option("--output-dir", "-o", required=True, type=click.Path())
def node(platform: str, input_file: str, hostname: str, output_dir: str) -> None:
    """Generate a report for a single host from a raw YAML file."""
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    with open(input_file) as f:
        bundle = yaml.safe_load(f)

    common_vars = generate_timestamps()
    rc = report_context(common_vars)
    schema_names = default_registry().schema_names_for_platform(platform)
    all_schemas = discover_schemas()
    schema = next((all_schemas[n] for n in schema_names if n in all_schemas), None)
    if schema is None:
        click.echo(f"ERROR: no config found for platform '{platform}'", err=True)
        raise SystemExit(1)

    from .models.platforms_config import TEMPLATE_NODE
    view = build_generic_node_view(schema, hostname, bundle, ctx=rc)
    content = get_jinja_env().get_template(TEMPLATE_NODE).render(
        generic_node_view=view, **common_vars
    )
    dest = output_path / f"{hostname}.html"
    dest.write_text(content)
    click.echo(f"Success: Report generated at {dest}")


# ---------------------------------------------------------------------------
# fire-on-alerts
# ---------------------------------------------------------------------------


def _parse_cooldown(cooldown: str) -> float:
    """Parse a cooldown string like '7d', '24h', '1h' into seconds."""
    import re
    m = re.match(r"(\d+)\s*([dhms])", cooldown.strip().lower())
    if not m:
        return 7 * 86400  # default 7 days
    val, unit = int(m.group(1)), m.group(2)
    return val * {"d": 86400, "h": 3600, "m": 60, "s": 1}[unit]


def _load_alert_state(state_path: str) -> dict:
    """Load alert state from YAML file."""
    from pathlib import Path
    p = Path(state_path)
    if p.exists():
        with open(p) as f:
            return yaml.safe_load(f) or {}
    return {}


def _save_alert_state(state_path: str, state: dict) -> None:
    """Save alert state to YAML file."""
    from pathlib import Path
    Path(state_path).parent.mkdir(parents=True, exist_ok=True)
    with open(state_path, "w") as f:
        yaml.dump(state, f, default_flow_style=False)


@main.command("fire-on-alerts")
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--hostname", "-n", default=None, help="Hostname for state tracking (auto-detected from bundle if omitted).")
@click.option("--state-file", default=".alert_state.yaml", type=click.Path(), help="Path to alert state file for cooldown tracking.")
@click.option(
    "--project-dir",
    "-C",
    default=None,
    type=click.Path(exists=True, file_okay=False),
    help="Ansible project root. Playbook paths resolve relative to this directory. Defaults to cwd.",
)
@click.option("--dry-run", is_flag=True, default=False, help="Print actions without executing.")
def fire_on_alerts(input_file: str, hostname: str | None, state_file: str, project_dir: str | None, dry_run: bool) -> None:
    """Evaluate alerts against a raw bundle and execute actions for fired alerts.

    Respects per-alert cooldown periods to prevent duplicate notifications.
    State is tracked in a YAML file (default: .alert_state.yaml).
    """
    import json
    import subprocess
    from datetime import datetime, timezone

    with open(input_file) as f:
        bundle = yaml.safe_load(f)

    from .schema_loader import detect_schemas_for_bundle
    matched = detect_schemas_for_bundle(bundle)
    if not matched:
        click.echo("No matching schema detected for bundle.", err=True)
        raise SystemExit(1)

    from .models.report_schema import ActionSpec
    from .normalization.schema_driven import build_schema_alerts, extract_fields
    from .normalization._when import _compile_template

    # Auto-detect hostname from bundle metadata
    if not hostname:
        for key in bundle:
            meta = bundle[key].get("metadata", {}) if isinstance(bundle.get(key), dict) else {}
            if meta.get("host"):
                hostname = meta["host"]
                break
        hostname = hostname or "unknown"

    state = _load_alert_state(state_file)
    now = datetime.now(timezone.utc)
    fired_alert_ids: set[str] = set()
    failures = 0

    for schema in matched:
        click.echo(f"Schema: {schema.name}")
        fields, _coverage = extract_fields(schema, bundle)
        alerts = build_schema_alerts(schema, fields)

        # Track which alert IDs fired this run (for clear-on-resolve)
        current_fired = {a["id"] for a in alerts}

        if not alerts:
            click.echo("  No alerts fired.")

        for alert in alerts:
            alert_id = alert["id"]
            sev = alert["severity"]
            msg = alert["message"]
            action = alert.get("action")
            cooldown_str = alert.get("cooldown", "7d")
            fired_alert_ids.add(alert_id)

            click.echo(f"  [{sev}] {alert_id}: {msg}")

            if not action:
                continue

            # Check cooldown
            cooldown_secs = _parse_cooldown(cooldown_str)
            alert_state = state.get(alert_id, {})
            host_state = alert_state.get(hostname, {})
            last_fired = host_state.get("last_fired")

            if last_fired:
                try:
                    last_dt = datetime.fromisoformat(str(last_fired))
                    if last_dt.tzinfo is None:
                        last_dt = last_dt.replace(tzinfo=timezone.utc)
                    elapsed = (now - last_dt).total_seconds()
                    if elapsed < cooldown_secs:
                        remaining = cooldown_secs - elapsed
                        hours = int(remaining // 3600)
                        click.echo(f"    COOLDOWN: {hours}h remaining (last fired {last_fired})")
                        continue
                except (ValueError, TypeError):
                    pass  # invalid timestamp, proceed

            spec = action if isinstance(action, ActionSpec) else ActionSpec(**(action if isinstance(action, dict) else {"command": action}))

            if spec.playbook:
                merged_vars = {"alert_id": alert_id, "alert_severity": sev, "alert_host": hostname, "alert_msg": msg}
                merged_vars.update(spec.extra_vars)
                run_cmd: str | list[str] = ["ansible-playbook", spec.playbook, "-e", json.dumps(merged_vars)]
                display = f"ansible-playbook {spec.playbook}"
                run_shell = False
                run_timeout: int | None = spec.timeout
            else:
                raw_cmd = spec.command or ""
                try:
                    rendered = _compile_template(raw_cmd).render(**fields)
                except Exception:
                    rendered = raw_cmd
                run_cmd = rendered
                display = rendered
                run_shell = True
                run_timeout = None

            if dry_run:
                click.echo(f"    DRY-RUN: {display if run_shell else ' '.join(run_cmd)}")
            else:
                click.echo(f"    EXEC: {display}")
                result = subprocess.run(run_cmd, shell=run_shell, cwd=project_dir, timeout=run_timeout)  # noqa: S602
                if result.returncode != 0:
                    click.echo(f"    FAILED (exit code {result.returncode})", err=True)
                    failures += 1
                else:
                    state.setdefault(alert_id, {})[hostname] = {"last_fired": now.isoformat()}

        # Clear resolved alerts (fired last time but not this time)
        for alert_id in list(state.keys()):
            if alert_id not in current_fired and hostname in state.get(alert_id, {}):
                del state[alert_id][hostname]
                if not state[alert_id]:
                    del state[alert_id]
                click.echo(f"  CLEARED: {alert_id} on {hostname}")

    if not dry_run:
        _save_alert_state(state_file, state)

    if failures:
        raise SystemExit(1)


# ---------------------------------------------------------------------------
# Register extracted command modules
# ---------------------------------------------------------------------------

from ._cli_all import all_cmd  # noqa: E402
from ._cli_platform import platform, schema  # noqa: E402
from ._cli_stig_cklb import cklb, stig, stig_apply  # noqa: E402

main.add_command(all_cmd, "all")
main.add_command(stig)
main.add_command(cklb)
main.add_command(platform)
main.add_command(schema)
main.add_command(stig_apply, "stig-apply")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


if __name__ == "__main__":
    main()
