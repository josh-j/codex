#!/usr/bin/env python3
# internal.core.stig : files/create_skeleton.py
#
# Parses a DISA STIG XCCDF XML file and generates a CKLB skeleton JSON.
# Usage: python3 create_skeleton.py <path_to_STIG.xml> [output_path]

import json
import sys
import uuid
import xml.etree.ElementTree as ET

NS = {"xccdf": "http://checklists.nist.gov/xccdf/1.1"}


def text(element, path):
    """Safe text extraction from an XML element."""
    found = element.find(path, NS)
    return found.text.strip() if found is not None and found.text else ""


def parse_xccdf(xml_path):
    try:
        tree = ET.parse(xml_path)
    except (ET.ParseError, FileNotFoundError) as e:
        print(f"Error reading {xml_path}: {e}")
        sys.exit(1)

    root = tree.getroot()
    rules = []

    for group in root.findall(".//xccdf:Group", NS):
        rule = group.find("./xccdf:Rule", NS)
        if rule is None:
            continue

        ident = rule.find(".//xccdf:ident", NS)
        rules.append(
            {
                "rule_id": rule.get("id", ""),
                "rule_version": text(rule, "./xccdf:version"),
                "severity": rule.get("severity", ""),
                "group_title": text(group, "./xccdf:title"),
                "rule_title": text(rule, "./xccdf:title"),
                "fix_text": text(rule, ".//xccdf:fixtext"),
                "check_content": text(rule, ".//xccdf:check-content"),
                "discussion": text(rule, ".//xccdf:description"),
                "ccis": [ident.text.strip()]
                if ident is not None and ident.text
                else [],
            }
        )

    return rules


def build_skeleton(rules, title, stig_id, release_info):
    return {
        "title": title,
        "id": stig_id,
        "cklb_version": "1.0",
        "stigs": [
            {
                "stig_name": f"{title} Security Technical Implementation Guide",
                "display_name": title,
                "stig_id": stig_id,
                "release_info": release_info,
                "version": "1",
                "uuid": str(uuid.uuid4()),
                "size": len(rules),
                "rules": rules,
            }
        ],
    }


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 create_skeleton.py <path_to_STIG.xml> [output_path]")
        sys.exit(1)

    xml_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "cklb_skeleton.json"

    rules = parse_xccdf(xml_path)
    skeleton = build_skeleton(
        rules=rules,
        title="VMware vSphere 7.0 Virtual Machine",
        stig_id="U_VMware_vSphere_7.0_VM_V1R3_STIG",
        release_info="Release: 1 Benchmark Date: 2023",
    )

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(skeleton, f, indent=2)
        print(f"Skeleton written to {output_path} ({len(rules)} rules)")
    except OSError as e:
        print(f"Error writing {output_path}: {e}")
        sys.exit(1)
