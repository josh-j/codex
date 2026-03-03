#!/usr/bin/env python3
"""Validate generated report artifacts for publish readiness."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml


SUPPORTED_CKLB_TARGETS = {
    "esxi",
    "vm",
    "vcsa",
    "vcenter",
    "vami",
    "eam",
    "lookup_svc",
    "perfcharts",
    "vcsa_photon_os",
    "postgresql",
    "rhttpproxy",
    "sts",
    "ui",
}


def _expect(path: Path, label: str, errors: list[str]) -> None:
    if not path.exists():
        errors.append(f"missing {label}: {path}")


def _load_platform_contract(platforms_config: Path | None) -> tuple[list[str], str, str, str]:
    if platforms_config is None:
        return (
            [
                "platform/linux/ubuntu/linux_fleet_report.html",
                "platform/linux/photon/photon_fleet_report.html",
                "platform/vmware/vcenter/vcsa/vcsa_fleet_report.html",
                "platform/windows/windows_fleet_report.html",
            ],
            "site_health_report.html",
            "stig_fleet_report.html",
            "search_index.js",
        )
    raw = yaml.safe_load(platforms_config.read_text(encoding="utf-8")) or {}
    platforms = raw.get("platforms", [])
    if not isinstance(platforms, list):
        raise ValueError(f"invalid platforms config {platforms_config}: missing platforms list")

    fleet_reports: list[str] = []
    site_report = "site_health_report.html"
    stig_fleet_report = "stig_fleet_report.html"
    search_index = "search_index.js"
    for p in platforms:
        if not isinstance(p, dict):
            continue
        paths = p.get("paths")
        if not isinstance(paths, dict):
            continue
        report_dir = str(p.get("report_dir", "")).strip()
        schema_name = str(p.get("schema_name") or p.get("platform") or "").strip()
        if report_dir and schema_name:
            fleet_reports.append(
                str(paths.get("report_fleet", "")).format(
                    report_dir=report_dir,
                    schema_name=schema_name,
                    hostname="",
                    target_type="",
                    report_stamp="",
                )
            )
        site_report = str(paths.get("report_site", site_report))
        stig_fleet_report = str(paths.get("report_stig_fleet", stig_fleet_report))
        search_index = str(paths.get("report_search_entry", "search_index.js"))
    # search_index_entry is a URL template, not the global file. Keep canonical artifact name.
    search_index = "search_index.js"
    return fleet_reports, site_report, stig_fleet_report, search_index


def verify(report_root: Path, platforms_config: Path | None = None) -> list[str]:
    errors: list[str] = []
    platform = report_root / "platform"
    cklb_dir = report_root / "cklb"
    fleet_candidates_rel, site_report_rel, stig_fleet_rel, search_index_rel = _load_platform_contract(platforms_config)

    _expect(report_root / site_report_rel, "site dashboard", errors)
    _expect(report_root / stig_fleet_rel, "stig fleet report", errors)
    _expect(report_root / search_index_rel, "search index", errors)

    fleet_candidates = [report_root / rel for rel in fleet_candidates_rel]
    if not any(p.exists() for p in fleet_candidates):
        errors.append("no fleet reports found under expected platform paths")

    raw_stig_files = sorted(platform.rglob("raw_stig_*.yaml"))
    if not raw_stig_files:
        errors.append(f"no raw STIG artifacts found under {platform}")
        return errors

    for raw in raw_stig_files:
        host = raw.parent.name
        target_type = raw.stem.replace("raw_stig_", "", 1)
        host_html = raw.parent / f"{host}_stig_{target_type}.html"
        if not host_html.exists():
            errors.append(f"missing STIG host html for {raw}: expected {host_html}")

        if target_type in SUPPORTED_CKLB_TARGETS:
            cklb = cklb_dir / f"{host}_{target_type}.cklb"
            if not cklb.exists():
                errors.append(f"missing CKLB for {raw}: expected {cklb}")

    return errors


def verify_stig_emission(
    report_root: Path,
    required_targets: list[str],
    min_hosts_per_target: int = 1,
) -> tuple[list[str], dict[str, set[str]]]:
    """Validate STIG callback emission coverage and payload integrity."""
    errors: list[str] = []
    platform = report_root / "platform"
    raw_stig_files = sorted(platform.rglob("raw_stig_*.yaml"))
    target_hosts: dict[str, set[str]] = {}

    if not raw_stig_files:
        return [f"no raw STIG artifacts found under {platform}"], target_hosts

    for raw in raw_stig_files:
        host = raw.parent.name
        target_type_from_name = raw.stem.replace("raw_stig_", "", 1).strip().lower()

        try:
            payload = yaml.safe_load(raw.read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"invalid yaml in {raw}: {exc}")
            continue

        if not isinstance(payload, dict):
            errors.append(f"invalid STIG payload shape in {raw}: expected mapping")
            continue

        meta = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
        engine = str(meta.get("engine", "")).strip()
        if engine != "ncs_collector_callback":
            errors.append(f"{raw} engine expected 'ncs_collector_callback', got '{engine}'")

        audit_type = str(meta.get("audit_type", "")).strip().lower()
        if not audit_type.startswith("stig"):
            errors.append(f"{raw} audit_type should start with 'stig', got '{audit_type}'")

        target_type = str(payload.get("target_type", "")).strip().lower()
        if not target_type:
            errors.append(f"{raw} missing target_type")
            target_type = target_type_from_name
        elif target_type != target_type_from_name:
            errors.append(
                f"{raw} target_type mismatch: file implies '{target_type_from_name}', payload has '{target_type}'"
            )

        target_hosts.setdefault(target_type, set()).add(host)

    for target in required_targets:
        count = len(target_hosts.get(target, set()))
        if count < min_hosts_per_target:
            errors.append(
                f"target '{target}' coverage too low: required >= {min_hosts_per_target} host(s), found {count}"
            )

    return errors, target_hosts


def _collect_missing_cklb_paths(report_root: Path) -> list[str]:
    missing: list[str] = []
    platform = report_root / "platform"
    cklb_dir = report_root / "cklb"
    for raw in sorted(platform.rglob("raw_stig_*.yaml")):
        host = raw.parent.name
        target_type = raw.stem.replace("raw_stig_", "", 1)
        if target_type in SUPPORTED_CKLB_TARGETS:
            cklb = cklb_dir / f"{host}_{target_type}.cklb"
            if not cklb.exists():
                missing.append(str(cklb))
    return missing


def _collect_missing_host_html_paths(report_root: Path) -> list[str]:
    missing: list[str] = []
    platform = report_root / "platform"
    for raw in sorted(platform.rglob("raw_stig_*.yaml")):
        host = raw.parent.name
        target_type = raw.stem.replace("raw_stig_", "", 1)
        host_html = raw.parent / f"{host}_stig_{target_type}.html"
        if not host_html.exists():
            missing.append(str(host_html))
    return missing


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify report artifacts for production readiness.")
    parser.add_argument("--report-root", default="tests/reports", help="Root directory containing generated reports.")
    parser.add_argument(
        "--platforms-config",
        default=None,
        help="Optional platforms.yaml path; when provided, expected report paths are derived from it.",
    )
    parser.add_argument(
        "--require-targets",
        default="",
        help="Comma-separated STIG target types that must be present (e.g. vcsa,esxi,vm,windows,ubuntu,photon).",
    )
    parser.add_argument(
        "--min-hosts-per-target",
        type=int,
        default=1,
        help="Minimum number of hosts required for each --require-targets entry.",
    )
    args = parser.parse_args()

    report_root = Path(args.report_root)
    platforms_config = Path(args.platforms_config) if args.platforms_config else None
    errors = verify(report_root, platforms_config=platforms_config)
    required_targets = [t.strip().lower() for t in args.require_targets.split(",") if t.strip()]
    target_hosts: dict[str, set[str]] = {}
    if required_targets:
        emission_errors, target_hosts = verify_stig_emission(
            report_root,
            required_targets=required_targets,
            min_hosts_per_target=args.min_hosts_per_target,
        )
        errors.extend(emission_errors)

    if errors:
        print("Artifact verification FAILED:")
        for error in errors:
            print(f" - {error}")
        if required_targets:
            print("STIG emission host coverage (triage):")
            for target in sorted(required_targets):
                hosts = sorted(target_hosts.get(target, set()))
                host_list = ", ".join(hosts) if hosts else "<none>"
                print(f" - {target}: {len(hosts)} host(s) -> {host_list}")
            missing_targets = sorted([target for target in required_targets if not target_hosts.get(target)])
            print(f"Missing target types: {', '.join(missing_targets) if missing_targets else '<none>'}")
        missing_cklbs = _collect_missing_cklb_paths(report_root)
        if missing_cklbs:
            print("Missing CKLB paths:")
            for p in missing_cklbs:
                print(f" - {p}")
        missing_html = _collect_missing_host_html_paths(report_root)
        if missing_html:
            print("Missing STIG host HTML paths:")
            for p in missing_html:
                print(f" - {p}")
        return 1

    raw_count = len(list((report_root / "platform").rglob("raw_stig_*.yaml")))
    print(f"Artifact verification passed for {report_root}")
    print(f"Checked raw STIG artifacts: {raw_count}")
    if required_targets:
        print("STIG emission coverage:")
        for target in sorted(required_targets):
            hosts = sorted(target_hosts.get(target, set()))
            host_list = ", ".join(hosts) if hosts else "<none>"
            print(f" - {target}: {len(hosts)} host(s) -> {host_list}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
