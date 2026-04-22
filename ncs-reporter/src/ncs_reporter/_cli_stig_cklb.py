"""STIG, CKLB, and stig-apply CLI commands (extracted from cli.py)."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click

from ._config import load_config_yaml, load_platforms, resolve_config_dir
from .cklb_export import generate_cklb
from .models.platforms_config import PlatformEntry
from .platform_registry import PlatformRegistry, default_registry

logger = logging.getLogger("ncs_reporter")


# ---------------------------------------------------------------------------
# CKLB generation core logic
# ---------------------------------------------------------------------------


def _resolve_skeleton_path(
    skeleton_file: str,
    *,
    explicit_skeleton_dir: Path | None,
    config_dir: Path | None,
    extra_config_dirs: tuple[Path, ...] = (),
    builtin_skeleton_dir: Path,
) -> Path | None:
    """Resolve a skeleton file path using a layered search.

    Resolution order:
      1. --skeleton-dir / bare filename  (legacy explicit CLI override)
      2. --config-dir / path-from-schema (supports subdirs like cklb_skeletons/)
      3. Any extra_config_dirs / path-from-schema (per-collection configs)
      4. Package builtins / bare filename (bundled VMware/Photon skeletons)
    """
    bare_name = Path(skeleton_file).name

    if explicit_skeleton_dir:
        candidate = explicit_skeleton_dir / bare_name
        if candidate.exists():
            return candidate

    if config_dir:
        candidate = config_dir / skeleton_file
        if candidate.exists():
            return candidate

    for extra in extra_config_dirs:
        candidate = extra / skeleton_file
        if candidate.exists():
            return candidate

    candidate = builtin_skeleton_dir / bare_name
    if candidate.exists():
        return candidate

    return None


def _generate_cklb_artifacts(
    hosts_data: dict[str, Any],
    output_path: Path,
    *,
    registry: PlatformRegistry | None = None,
    explicit_skeleton_dir: Path | None = None,
    config_dir: Path | None = None,
    extra_config_dirs: tuple[Path, ...] = (),
) -> None:
    """Core CKLB generation logic.

    Called directly from ``all_cmd`` (with the runtime registry already built
    from --config-dir) and wrapped by the ``cklb`` CLI command for standalone
    invocation.
    """
    from .models.platforms_config import CKLB_SKELETONS_DIR
    effective_registry = registry or default_registry()
    builtin_skeleton_dir = Path(__file__).parent / CKLB_SKELETONS_DIR

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig") or not isinstance(payload, dict):
                continue
            target_type = str(payload.get("target_type", ""))
            skeleton_file = effective_registry.stig_skeleton_for_target(target_type)
            if not skeleton_file:
                logger.debug(
                    "No skeleton mapping for target_type '%s' on host '%s' (audit_type='%s')",
                    target_type, hostname, audit_type,
                )
                continue

            sk_path = _resolve_skeleton_path(
                skeleton_file,
                explicit_skeleton_dir=explicit_skeleton_dir,
                config_dir=config_dir,
                extra_config_dirs=extra_config_dirs,
                builtin_skeleton_dir=builtin_skeleton_dir,
            )

            if sk_path is None:
                searched = " \u2192 ".join(filter(None, [
                    str(explicit_skeleton_dir / Path(skeleton_file).name) if explicit_skeleton_dir else None,
                    str(config_dir / skeleton_file) if config_dir else None,
                    *(str(extra / skeleton_file) for extra in extra_config_dirs),
                    str(builtin_skeleton_dir / Path(skeleton_file).name),
                ]))
                click.echo(
                    f"Warning: Skeleton not found for {target_type}: {skeleton_file} "
                    f"(searched: {searched})"
                )
                continue

            ip_addr = str(payload.get("ip_address") or bundle.get("ip_address") or "")
            dest = output_path / f"{hostname}_{target_type}.cklb"
            generate_cklb(hostname, payload.get("full_audit", []), sk_path, dest, ip_address=ip_addr)
            click.echo(f"Generated CKLB: {dest}")


def _registry_from_config_dir(config_dir: str | None) -> PlatformRegistry | None:
    """Build a PlatformRegistry from --config-dir if provided, else None."""
    if not config_dir:
        return None
    try:
        config_yaml = load_config_yaml(config_dir)
        _extra_dirs, _platforms_cfg = resolve_config_dir(config_dir, (), None, config_yaml)
        platforms = load_platforms(_platforms_cfg, extra_config_dirs=_extra_dirs)
        return PlatformRegistry([PlatformEntry.model_validate(p) for p in platforms])
    except Exception as exc:
        logger.warning("Could not build registry from config-dir '%s': %s", config_dir, exc)
        return None


def _resolve_extra_config_dirs(config_dir: str | None) -> tuple[Path, ...]:
    """Read config.yaml from config_dir and return its extra_config_dirs as Paths.

    Used so CKLB skeleton resolution can search per-collection config dirs when
    they host the skeletons alongside their platform YAMLs.
    """
    if not config_dir:
        return ()
    try:
        config_yaml = load_config_yaml(config_dir)
        extras, _platforms_cfg = resolve_config_dir(config_dir, (), None, config_yaml)
    except Exception as exc:
        logger.warning("Could not resolve extra_config_dirs for '%s': %s", config_dir, exc)
        return ()
    root = Path(config_dir).resolve()
    return tuple(Path(p) for p in extras if Path(p).resolve() != root)


# ---------------------------------------------------------------------------
# stig
# ---------------------------------------------------------------------------


@click.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--report-stamp")
@click.option("--config-dir", default=None, type=click.Path(exists=True, file_okay=False))
def stig(input_file: str, output_dir: str, report_stamp: str | None, config_dir: str | None) -> None:
    """Generate STIG compliance reports (per-host and fleet overview)."""
    from ._report_context import generate_timestamps, load_hosts_data
    from ._renderers import render_stig

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)
    common_vars = generate_timestamps(report_stamp)

    registry = _registry_from_config_dir(config_dir)
    cklb_output = output_path / "cklb"
    cklb_output.mkdir(parents=True, exist_ok=True)
    _generate_cklb_artifacts(
        hosts_data,
        cklb_output,
        registry=registry,
        config_dir=Path(config_dir) if config_dir else None,
        extra_config_dirs=_resolve_extra_config_dirs(config_dir),
    )

    render_stig(hosts_data, output_path, common_vars, cklb_dir=cklb_output)
    click.echo(f"Done! STIG reports generated in {output_dir}")


# ---------------------------------------------------------------------------
# cklb
# ---------------------------------------------------------------------------


@click.command()
@click.option("--input", "-i", "input_file", required=True, type=click.Path(exists=True))
@click.option("--output-dir", "-o", required=True, type=click.Path())
@click.option("--skeleton-dir", type=click.Path(exists=True), help="Legacy: explicit skeleton directory override.")
@click.option("--config-dir", type=click.Path(exists=True, file_okay=False),
              help="Config directory containing platform configs and skeleton files.")
def cklb(input_file: str, output_dir: str, skeleton_dir: str | None, config_dir: str | None) -> None:
    """Generate CKLB artifacts for STIG results.

    Skeleton resolution order:
      1. --skeleton-dir (legacy explicit override, bare filename)
      2. --config-dir + path from stig_platform_to_checklist (e.g. cklb_skeletons/foo.cklb)
      3. Package builtins in src/ncs_reporter/cklb_skeletons/ (bare filename)
    """
    from ._report_context import load_hosts_data

    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    hosts_data = load_hosts_data(input_file)

    registry = _registry_from_config_dir(config_dir)

    _generate_cklb_artifacts(
        hosts_data,
        output_path,
        registry=registry,
        explicit_skeleton_dir=Path(skeleton_dir) if skeleton_dir else None,
        config_dir=Path(config_dir) if config_dir else None,
        extra_config_dirs=_resolve_extra_config_dirs(config_dir),
    )


# ---------------------------------------------------------------------------
# stig-apply
# ---------------------------------------------------------------------------


@click.command("stig-apply")
@click.argument("artifact", type=click.Path(exists=True, path_type=Path))
@click.option("--inventory", default="inventory/production/", show_default=True)
@click.option("--limit", required=True)
@click.option("--target-type", default="")
@click.option("--target-host", default="")
@click.option("--esxi-host", default="", help="Legacy alias for --target-host.")
@click.option("--skip-snapshot", is_flag=True)
@click.option("--post-audit", is_flag=True)
@click.option("--extra-vars", "-e", "extra_vars", multiple=True)
@click.option("--dry-run", is_flag=True)
def stig_apply(
    artifact: Path,
    inventory: str,
    limit: str,
    target_type: str,
    target_host: str,
    esxi_host: str,
    skip_snapshot: bool,
    post_audit: bool,
    extra_vars: tuple[str, ...],
    dry_run: bool,
) -> None:
    """Apply STIG remediation interactively from a raw STIG YAML artifact."""
    from ._stig_apply import (
        SUPPORTED_TARGET_TYPES,
        detect_target_type,
        infer_target_host,
        load_stig_artifact,
        run_generic_interactive_apply,
        run_interactive_apply,
    )

    raw = load_stig_artifact(artifact)
    detected = detect_target_type(raw, artifact, override=target_type)
    if not detected:
        raise click.ClickException(
            "Could not determine target type. Provide --target-type (esxi/vm/vcsa/photon/ubuntu)."
        )
    normalized = detected.lower()
    if normalized not in SUPPORTED_TARGET_TYPES:
        raise click.ClickException(
            f"Unsupported target type '{normalized}'. Supported: {', '.join(sorted(SUPPORTED_TARGET_TYPES))}."
        )

    effective_host = target_host or esxi_host or infer_target_host(raw)
    if normalized == "esxi":
        if not effective_host:
            raise click.ClickException("ESXi apply requires --target-host.")
        run_interactive_apply(
            artifact=artifact, inventory=inventory, limit=limit, esxi_host=effective_host,
            skip_snapshot=skip_snapshot, post_audit=post_audit, extra_vars=extra_vars, dry_run=dry_run,
        )
    else:
        run_generic_interactive_apply(
            artifact=artifact, inventory=inventory, limit=limit, target_type=normalized,
            target_host=effective_host, extra_vars=extra_vars, dry_run=dry_run,
        )
