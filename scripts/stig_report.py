#!/usr/bin/env python3
"""Report STIG compliance status from collector data against the CKLB skeleton.

Usage:
    stig_report.py <raw_stig_yaml> <cklb_skeleton>
    stig_report.py /srv/samba/reports/platform/linux/ubuntu/192.168.2.111/raw_stig_ubuntu.yaml

If the CKLB skeleton is omitted, the script searches for a matching skeleton
in files/ncs-reporter_configs/cklb_skeletons/ based on the target_type in the
raw STIG data.
"""

import json
import os
import re
import sys
from collections import Counter

import yaml

# Mapping from collector status to display label
STATUS_LABELS = {
    "pass": "Not a Finding",
    "failed": "Open",
    "fixed": "Not a Finding",
    "not_applicable": "Not Applicable",
    "na": "Not Reviewed",
}

SEVERITY_ORDER = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
STATUS_ORDER = {"Open": 0, "Not Reviewed": 1, "Not Applicable": 2, "Not a Finding": 3}

COLORS = {
    "Open": "\033[91m",         # red
    "Not a Finding": "\033[92m", # green
    "Not Reviewed": "\033[93m",  # yellow
    "Not Applicable": "\033[90m", # gray
    "RESET": "\033[0m",
    "BOLD": "\033[1m",
    "DIM": "\033[2m",
}


def load_raw_stig(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_cklb(path: str) -> dict:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def find_cklb_skeleton(target_type: str) -> str | None:
    """Search for a CKLB skeleton matching the target type."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    repo_root = os.path.dirname(script_dir)
    skeleton_dir = os.path.join(repo_root, "files", "ncs-reporter_configs", "cklb_skeletons")

    if not os.path.isdir(skeleton_dir):
        return None

    # Map common target types to CKLB filename patterns
    patterns = {
        "ubuntu": "Ubuntu",
        "photon": "Photon",
        "esxi": "ESXi",
        "vcenter": "vCenter",
        "windows": "Windows",
    }

    search = patterns.get(target_type, target_type)
    for f in os.listdir(skeleton_dir):
        if f.endswith(".cklb") and search.lower() in f.lower():
            return os.path.join(skeleton_dir, f)
    return None


def normalize_rule_id(rule_id: str) -> str:
    """Extract the numeric portion of a rule ID for matching."""
    m = re.search(r"(\d{5,})", str(rule_id))
    return m.group(1) if m else str(rule_id).strip()


def build_results_index(raw_data: dict) -> dict[str, dict]:
    """Build a lookup from rule number -> collector result.

    Indexes by both the normalized numeric ID and the raw rule_id string
    so that PREFIX-NN-NNNNNN style IDs (e.g. PHTN-30-000058) can be
    matched against CKLB rule_version fields.
    """
    index = {}
    for row in raw_data.get("data", []):
        rule_id = row.get("rule_id", row.get("id", ""))
        num = normalize_rule_id(rule_id)
        index[num] = row
        # Also index by the raw rule_id string for PREFIX-NN-NNNNNN matching
        raw_id = str(rule_id).strip()
        if raw_id:
            index[raw_id] = row
    return index


def build_cklb_index(cklb_data: dict) -> list[dict]:
    """Extract all rules from the CKLB skeleton."""
    rules = []
    for stig in cklb_data.get("stigs", []):
        for rule in stig.get("rules", []):
            rules.append(rule)
    return rules


def report(raw_path: str, cklb_path: str, use_color: bool = True):
    raw_data = load_raw_stig(raw_path)
    cklb_data = load_cklb(cklb_path)

    metadata = raw_data.get("metadata", {})
    host = metadata.get("host", "unknown")
    target_type = raw_data.get("target_type", metadata.get("raw_type", "unknown"))
    timestamp = metadata.get("timestamp", "")

    results = build_results_index(raw_data)
    cklb_rules = build_cklb_index(cklb_data)

    def c(label: str, text: str) -> str:
        if not use_color:
            return text
        return f"{COLORS.get(label, '')}{text}{COLORS['RESET']}"

    def bold(text: str) -> str:
        return f"{COLORS['BOLD']}{text}{COLORS['RESET']}" if use_color else text

    def dim(text: str) -> str:
        return f"{COLORS['DIM']}{text}{COLORS['RESET']}" if use_color else text

    # Build merged view: every CKLB rule + its collector result (if any)
    rows = []
    for cklb_rule in cklb_rules:
        vuln_id = cklb_rule.get("group_id_src", "")
        num = normalize_rule_id(vuln_id)
        severity = cklb_rule.get("severity", "unknown").lower()
        title = cklb_rule.get("group_title", "")
        rule_version = cklb_rule.get("rule_version", "")

        result = results.get(num) or results.get(rule_version)
        if result:
            raw_status = result.get("status", "na")
            display_status = STATUS_LABELS.get(raw_status, raw_status)
            reason = ""
            comments = result.get("comments", "")
            if "Reason: " in comments:
                reason = comments.split("Reason: ", 1)[1].rstrip(".")
        else:
            display_status = "Not Reviewed"
            reason = "No collector data"

        rows.append({
            "vuln_id": vuln_id,
            "rule_version": rule_version,
            "severity": severity,
            "title": title,
            "status": display_status,
            "reason": reason,
        })

    # Sort: Open first, then Not Reviewed, then Not Applicable, then Not a Finding
    # Within each status group, sort by severity (high > medium > low)
    rows.sort(key=lambda r: (
        STATUS_ORDER.get(r["status"], 99),
        SEVERITY_ORDER.get(r["severity"], 99),
        r["vuln_id"],
    ))

    # Summary counts
    status_counts = Counter(r["status"] for r in rows)
    severity_status = {}
    for r in rows:
        key = (r["severity"], r["status"])
        severity_status[key] = severity_status.get(key, 0) + 1

    # Print report
    print()
    print(bold(f"  STIG Compliance Report"))
    print(bold(f"  {'=' * 60}"))
    print(f"  Host:        {host}")
    print(f"  Target Type: {target_type}")
    print(f"  Timestamp:   {timestamp}")
    print(f"  CKLB:        {os.path.basename(cklb_path)}")
    print(f"  Total Rules: {len(rows)}")
    print()

    # Summary bar
    total = len(rows)
    naf = status_counts.get("Not a Finding", 0)
    opn = status_counts.get("Open", 0)
    nr = status_counts.get("Not Reviewed", 0)
    na = status_counts.get("Not Applicable", 0)

    pct_compliant = (naf / total * 100) if total else 0
    print(f"  {c('Not a Finding', f'Not a Finding:   {naf:>4}')}  ({naf/total*100:.1f}%)")
    print(f"  {c('Open',          f'Open:            {opn:>4}')}  ({opn/total*100:.1f}%)")
    print(f"  {c('Not Reviewed',  f'Not Reviewed:    {nr:>4}')}  ({nr/total*100:.1f}%)")
    print(f"  {c('Not Applicable',f'Not Applicable:  {na:>4}')}  ({na/total*100:.1f}%)")
    print()

    # Severity breakdown
    print(bold("  By Severity:"))
    for sev in ("high", "medium", "low"):
        sev_open = severity_status.get((sev, "Open"), 0)
        sev_naf = severity_status.get((sev, "Not a Finding"), 0)
        sev_nr = severity_status.get((sev, "Not Reviewed"), 0)
        sev_na = severity_status.get((sev, "Not Applicable"), 0)
        sev_total = sev_open + sev_naf + sev_nr + sev_na
        if sev_total == 0:
            continue
        print(f"    {sev.upper():>6}:  "
              f"{c('Open', f'{sev_open} Open')}  "
              f"{c('Not a Finding', f'{sev_naf} Pass')}  "
              f"{c('Not Reviewed', f'{sev_nr} NR')}  "
              f"{c('Not Applicable', f'{sev_na} NA')}  "
              f"({sev_total} total)")
    print()

    # Detail table — Open findings first, then Not Reviewed
    print(bold("  Open Findings:"))
    print(f"  {'Rule':<16} {'Sev':<8} {'Title':<58} {'Reason'}")
    print(f"  {'-'*15} {'-'*7} {'-'*57} {'-'*40}")
    open_rows = [r for r in rows if r["status"] == "Open"]
    if not open_rows:
        print(f"  {c('Not a Finding', 'None')}")
    for r in open_rows:
        title = r["title"][:57]
        reason = r["reason"][:60] if r["reason"] else ""
        print(c("Open", f"  {r['vuln_id']:<16} {r['severity']:<8} {title:<58} {reason}"))
    print()

    nr_rows = [r for r in rows if r["status"] == "Not Reviewed"]
    if nr_rows:
        print(bold("  Not Reviewed:"))
        print(f"  {'Rule':<16} {'Sev':<8} {'Title':<58} {'Reason'}")
        print(f"  {'-'*15} {'-'*7} {'-'*57} {'-'*40}")
        for r in nr_rows:
            title = r["title"][:57]
            reason = r["reason"][:60] if r["reason"] else ""
            print(c("Not Reviewed", f"  {r['vuln_id']:<16} {r['severity']:<8} {title:<58} {reason}"))
        print()

    na_rows = [r for r in rows if r["status"] == "Not Applicable"]
    if na_rows:
        print(bold("  Not Applicable:"))
        for r in na_rows:
            print(dim(f"  {r['vuln_id']:<16} {r['severity']:<8} {r['title'][:70]}"))
        print()

    # Passing rules (collapsed)
    pass_rows = [r for r in rows if r["status"] == "Not a Finding"]
    if pass_rows:
        print(bold(f"  Not a Finding: {len(pass_rows)} rules"))
        # Show first few
        for r in pass_rows[:5]:
            print(dim(f"  {r['vuln_id']:<16} {r['severity']:<8} {r['title'][:70]}"))
        if len(pass_rows) > 5:
            print(dim(f"  ... and {len(pass_rows) - 5} more"))
        print()

    print(bold(f"  Compliance: {pct_compliant:.1f}% ({naf}/{total} rules passing)"))
    print()


def main():
    if len(sys.argv) < 2:
        print(f"Usage: {sys.argv[0]} <raw_stig.yaml> [cklb_skeleton.cklb]", file=sys.stderr)
        sys.exit(1)

    raw_path = sys.argv[1]
    if not os.path.isfile(raw_path):
        print(f"Error: {raw_path} not found", file=sys.stderr)
        sys.exit(1)

    if len(sys.argv) >= 3:
        cklb_path = sys.argv[2]
    else:
        # Auto-detect from raw data
        with open(raw_path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        target_type = raw.get("target_type", raw.get("metadata", {}).get("raw_type", ""))
        if target_type.startswith("stig_"):
            target_type = target_type[5:]
        cklb_path = find_cklb_skeleton(target_type)
        if not cklb_path:
            print(f"Error: Could not find CKLB skeleton for target_type '{target_type}'", file=sys.stderr)
            print(f"Provide the path as the second argument.", file=sys.stderr)
            sys.exit(1)

    use_color = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None
    report(raw_path, cklb_path, use_color=use_color)


if __name__ == "__main__":
    main()
