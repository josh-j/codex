#!/usr/bin/env python3
import csv
import re
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
TASK_DIR = ROOT / "ubuntu2404_stigs"
XML_PATH = ROOT / "U_CAN_Ubuntu_24-04_LTS_V1R4_STIG" / "U_CAN_Ubuntu_24-04_LTS_V1R4_Manual_STIG" / "U_CAN_Ubuntu_24-04_LTS_STIG_V1R4_Manual-xccdf.xml"
OUT_PATH = TASK_DIR / "coverage_gaps.csv"
NS = {"xccdf": "http://checklists.nist.gov/xccdf/1.1"}


def normalized_text(elem):
    if elem is None:
        return ""
    return re.sub(r"\s+", " ", "".join(elem.itertext())).strip()


def xccdf_rules():
    root = ET.parse(XML_PATH).getroot()
    rules = {}
    for rule in root.findall(".//xccdf:Rule", NS):
        match = re.search(r"SV-(\d+)", rule.attrib.get("id", ""))
        if not match:
            continue
        stig_id = match.group(1)
        check = rule.find("xccdf:check/xccdf:check-content", NS)
        if check is None:
            for elem in rule.iter():
                if elem.tag.split("}")[-1] == "check-content":
                    check = elem
                    break
        rules[stig_id] = {
            "check_text": normalized_text(check),
            "fix_text": normalized_text(rule.find("xccdf:fixtext", NS)),
        }
    return dict(sorted(rules.items(), key=lambda item: int(item[0])))


def task_coverage():
    status = {}
    locations = defaultdict(list)
    for path in sorted(TASK_DIR.glob("*.yaml")):
        lines = path.read_text().splitlines()
        starts = [i for i, line in enumerate(lines) if line.startswith("- name: ")]
        starts.append(len(lines))
        for start, end in zip(starts, starts[1:]):
            block = lines[start:end]
            body = "\n".join(block)
            refs = sorted(set(re.findall(r"ubuntu2404STIG_stigrule_(\d+)_manage", body)), key=int)
            if not refs:
                continue
            name = block[0].split(": ", 1)[1].strip().strip('"').lower()
            audit = (
                "assert" in name
                or "_check" in name
                or ("ansible_check_mode | default(false)" in body and "not (ansible_check_mode | default(false))" not in body)
            )
            remediate = False
            if "not (ansible_check_mode | default(false))" in body:
                remediate = True
            elif not audit and any(
                module in body
                for module in [
                    "ansible.builtin.lineinfile:",
                    "ansible.builtin.copy:",
                    "ansible.builtin.file:",
                    "ansible.builtin.systemd_service:",
                    "ansible.posix.sysctl:",
                    "community.general.ini_file:",
                    "ansible.builtin.apt:",
                    "ansible.builtin.blockinfile:",
                    "ansible.builtin.replace:",
                    "ansible.builtin.service:",
                    "community.general.ufw:",
                    "ansible.builtin.shell:",
                ]
            ):
                remediate = True
            span = f"{path.as_posix()}:{start + 1}-{end}"
            for stig_id in refs:
                status.setdefault(stig_id, {"audit": False, "remediate": False})
                status[stig_id]["audit"] |= audit
                status[stig_id]["remediate"] |= remediate
                locations[stig_id].append(span)
    return status, locations


def main():
    rules = xccdf_rules()
    status, locations = task_coverage()
    rows = []
    for stig_id, texts in rules.items():
        audited = status.get(stig_id, {}).get("audit", False)
        remediated = status.get(stig_id, {}).get("remediate", False)
        if audited and remediated:
            continue
        rows.append(
            {
                "stig_id": stig_id,
                "audited": str(audited).lower(),
                "remediated": str(remediated).lower(),
                "location": "; ".join(locations.get(stig_id, [])),
                "automation_gap": "No. This STIG is absent from ubuntu2404_stigs and can be automated by adding both audit and remediation tasks." if not audited and not remediated else "",
                "notes": "High risk gap: this STIG is not implemented in ubuntu2404_stigs, so both audit and remediation are missing." if not audited and not remediated else "",
                "check_text": texts["check_text"],
                "fix_text": texts["fix_text"],
            }
        )
    with OUT_PATH.open("w", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["stig_id", "audited", "remediated", "location", "automation_gap", "notes", "check_text", "fix_text"],
        )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} rows to {OUT_PATH}")


if __name__ == "__main__":
    main()
