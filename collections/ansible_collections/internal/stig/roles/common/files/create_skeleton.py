import json
import sys
import xml.etree.ElementTree as ET

# Usage: python3 create_skeleton.py <path_to_STIG.xml>
# Output: cklb_skeleton_vsphere7_vms_V1R4.json


def parse_xccdf(xml_path):
    tree = ET.parse(xml_path)
    root = tree.getroot()
    ns = {"xccdf": "http://checklists.nist.gov/xccdf/1.1"}

    rules_list = []

    # Iterate through all Groups (Rules are inside Groups in STIG XML)
    for group in root.findall(".//xccdf:Group", ns):
        rule = group.find("./xccdf:Rule", ns)
        if rule is None:
            continue

        rule_id = rule.get("id")  # SV-XXXX
        version = rule.find("./xccdf:version", ns).text  # VMCH-70-XXXX
        title = rule.find("./xccdf:title", ns).text

        # Extract Fix Text & Discussion
        fix = rule.find(".//xccdf:fixtext", ns)
        fix_text = fix.text if fix is not None else ""

        desc = rule.find(".//xccdf:description", ns)
        discussion = desc.text if desc is not None else ""

        check = rule.find(".//xccdf:check-content", ns)
        check_text = check.text if check is not None else ""

        # Minimal CCIs
        ident = rule.find(".//xccdf:ident", ns)
        cci = ident.text if ident is not None else ""

        rules_list.append(
            {
                "rule_id": rule_id,
                "rule_version": version,
                "severity": rule.get("severity"),
                "group_title": group.find("./xccdf:title", ns).text,
                "rule_title": title,
                "fix_text": fix_text,
                "check_content": check_text,
                "discussion": discussion,
                "ccis": [cci],
            }
        )

    skeleton = {
        "title": "VMware vSphere 7.0 Virtual Machine",
        "id": "U_VMware_vSphere_7.0_VM_V1R3_STIG",
        "cklb_version": "1.0",
        "stigs": [
            {
                "stig_name": "VMware vSphere 7.0 VM Security Technical Implementation Guide",
                "display_name": "VMware vSphere 7.0 VM",
                "stig_id": "U_VMware_vSphere_7.0_VM_V1R3_STIG",
                "release_info": "Release: 1 Benchmark Date: 2023",
                "version": "1",
                "uuid": "auto-generated-uuid",
                "size": len(rules_list),
                "rules": rules_list,
            }
        ],
    }

    with open("cklb_skeleton_vsphere7_vms_V1R4.json", "w") as f:
        json.dump(skeleton, f, indent=2)
    print("Skeleton generated successfully.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 create_skeleton.py <path_to_STIG.xml>")
    else:
        parse_xccdf(sys.argv[1])
