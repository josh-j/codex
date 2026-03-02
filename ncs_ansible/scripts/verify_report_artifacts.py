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


def verify(report_root: Path) -> list[str]:
    errors: list[str] = []
    platform = report_root / "platform"
    cklb_dir = report_root / "cklb"

    _expect(report_root / "site_health_report.html", "site dashboard", errors)
    _expect(report_root / "stig_fleet_report.html", "stig fleet report", errors)
    _expect(report_root / "search_index.js", "search index", errors)

    fleet_candidates = [
        platform / "linux" / "ubuntu" / "linux_fleet_report.html",
        platform / "linux" / "photon" / "photon_fleet_report.html",
        platform / "vmware" / "vcenter" / "vcsa" / "vcsa_fleet_report.html",
        platform / "windows" / "windows_fleet_report.html",
    ]
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
    errors = verify(report_root)
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
