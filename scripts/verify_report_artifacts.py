#!/usr/bin/env python3
"""Verify that report generation produced the expected artifacts."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def _find_html(root: Path) -> list[Path]:
    return sorted(root.rglob("*.html"))


def _find_yaml(root: Path) -> list[Path]:
    return sorted(root.rglob("*.yaml"))


def _find_cklb(root: Path) -> list[Path]:
    return sorted(root.rglob("*.cklb"))


def verify_basic(report_root: Path) -> list[str]:
    """Check that core report artifacts exist."""
    errors: list[str] = []

    site_dashboard = report_root / "site_health_report.html"
    if not site_dashboard.is_file():
        errors.append(f"Missing site dashboard: {site_dashboard}")

    search_index = report_root / "search_index.js"
    if not search_index.is_file():
        errors.append(f"Missing search index: {search_index}")

    platform_dir = report_root / "platform"
    if not platform_dir.is_dir():
        errors.append(f"Missing platform directory: {platform_dir}")

    html_files = _find_html(report_root)
    if not html_files:
        errors.append("No HTML reports found anywhere under report root")

    return errors


def verify_stig_targets(
    report_root: Path,
    required_targets: list[str],
    min_hosts: int,
) -> list[str]:
    """Check that STIG artifacts exist for each required target type."""
    errors: list[str] = []

    # STIG fleet report
    stig_fleet = list(report_root.glob("stig_fleet_report*.html"))
    if not stig_fleet:
        errors.append("Missing STIG fleet report")

    # Scan for raw_stig_*.yaml files to build a map of target_type -> hostnames
    platform_dir = report_root / "platform"
    target_hosts: dict[str, set[str]] = {}

    for raw_stig in platform_dir.rglob("raw_stig_*.yaml"):
        # Filename pattern: raw_stig_{target_type}.yaml
        target_type = raw_stig.stem.removeprefix("raw_stig_")
        hostname = raw_stig.parent.name
        target_hosts.setdefault(target_type, set()).add(hostname)

    for target in required_targets:
        hosts = target_hosts.get(target, set())
        if len(hosts) < min_hosts:
            errors.append(
                f"Target '{target}': found {len(hosts)} host(s), "
                f"need at least {min_hosts}"
            )

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify report artifacts")
    parser.add_argument("--report-root", required=True, type=Path)
    parser.add_argument("--require-targets", type=str, default="")
    parser.add_argument("--min-hosts-per-target", type=int, default=1)
    args = parser.parse_args()

    report_root: Path = args.report_root.resolve()
    if not report_root.is_dir():
        print(f"FAIL: report root does not exist: {report_root}")
        sys.exit(1)

    errors = verify_basic(report_root)

    if args.require_targets:
        targets = [t.strip() for t in args.require_targets.split(",") if t.strip()]
        errors.extend(verify_stig_targets(report_root, targets, args.min_hosts_per_target))

    if errors:
        print(f"FAIL: {len(errors)} verification error(s):")
        for e in errors:
            print(f"  - {e}")
        sys.exit(1)

    # Summary
    html_count = len(_find_html(report_root))
    yaml_count = len(_find_yaml(report_root))
    cklb_count = len(_find_cklb(report_root))
    print(f"OK: {html_count} HTML, {yaml_count} YAML, {cklb_count} CKLB artifacts verified in {report_root}")


if __name__ == "__main__":
    main()
