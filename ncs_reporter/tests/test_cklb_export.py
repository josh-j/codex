"""Tests for CKLB export logic."""

import json
import re

import pytest
from ncs_reporter.cklb_export import generate_cklb


def _skeleton():
    return {
        "title": "Test STIG",
        "id": "test-id",
        "cklb_version": "1.0",
        "stigs": [
            {
                "stig_name": "Test STIG Profile",
                "display_name": "Test",
                "stig_id": "stig-001",
                "release_info": "R1",
                "version": "1",
                "uuid": "uuid-001",
                "size": 3,
                "rules": [
                    {
                        "rule_id": "SV-001",
                        "rule_version": "V-001",
                        "group_id": "G-001",
                        "severity": "high",
                        "group_title": "Group 1",
                        "rule_title": "Rule One",
                        "fix_text": "Fix it",
                        "check_content": "Check it",
                        "discussion": "Discussion",
                        "ccis": ["CCI-001"],
                    },
                    {
                        "rule_id": "SV-002",
                        "rule_version": "V-002",
                        "group_id": "G-002",
                        "severity": "medium",
                        "group_title": "Group 2",
                        "rule_title": "Rule Two",
                        "fix_text": "Fix 2",
                        "check_content": "Check 2",
                        "discussion": "Discussion 2",
                        "ccis": ["CCI-002"],
                    },
                    {
                        "rule_id": "SV-003",
                        "rule_version": "V-003",
                        "group_id": "G-003",
                        "severity": "low",
                        "group_title": "Group 3",
                        "rule_title": "Rule Three",
                        "fix_text": "Fix 3",
                        "check_content": "Check 3",
                        "discussion": "Discussion 3",
                        "ccis": ["CCI-003"],
                    },
                ],
            }
        ],
    }


class TestGenerateCklb:
    def test_basic_generation(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        audit_data = [
            {"rule_id": "V-001", "status": "open", "checktext": "Failed check"},
            {"rule_id": "V-002", "status": "pass", "checktext": "Passed check"},
        ]

        generate_cklb("test-host", audit_data, skeleton_path, output_path)

        assert output_path.exists()
        result = json.loads(output_path.read_text())
        assert result["target_data"]["host_name"] == "test-host"
        assert result["title"] == "Test STIG"

        rules = result["stigs"][0]["rules"]
        assert len(rules) == 3

        # V-001 should be open
        r1 = rules[0]
        assert r1["status"] == "open"
        assert r1["finding_details"] == "Failed check"

        # V-002 should be not_a_finding
        r2 = rules[1]
        assert r2["status"] == "not_a_finding"

        # V-003 has no audit data, should be not_reviewed
        r3 = rules[2]
        assert r3["status"] == "not_reviewed"

    def test_empty_audit_data(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        generate_cklb("host1", [], skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        rules = result["stigs"][0]["rules"]
        # All should be not_reviewed
        assert all(r["status"] == "not_reviewed" for r in rules)

    def test_missing_skeleton_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            generate_cklb("host1", [], tmp_path / "missing.json", tmp_path / "out.cklb")

    def test_target_data_fields(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        generate_cklb("myhost.example.com", [], skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        td = result["target_data"]
        assert td["host_name"] == "myhost.example.com"
        assert td["fqdn"] == "myhost.example.com"
        assert td["target_type"] == "Computing"

    def test_matching_by_group_id(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        # Match by group_id instead of rule_version
        audit_data = [{"rule_id": "G-003", "status": "pass", "checktext": "Good"}]
        generate_cklb("host1", audit_data, skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        rules = result["stigs"][0]["rules"]
        # G-003 should match the third rule
        assert rules[2]["status"] == "not_a_finding"

    def test_no_html_tags_in_finding_details(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        audit_data = [
            {"rule_id": "V-001", "status": "open", "checktext": "<b>Failed</b> check: value is <em>wrong</em>."},
        ]
        generate_cklb("host1", audit_data, skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        details = result["stigs"][0]["rules"][0]["finding_details"]
        assert re.search(r"<[^>]+>", details) is None
        assert "Failed" in details
        assert "wrong" in details

    def test_comments_populated_for_matched_rules(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        audit_data = [
            {"rule_id": "V-001", "status": "open", "checktext": "A finding"},
            {"rule_id": "V-002", "status": "pass", "checktext": "All good"},
        ]
        generate_cklb("host1", audit_data, skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        rules = result["stigs"][0]["rules"]
        assert rules[0]["comments"] and len(rules[0]["comments"]) > 0
        assert rules[1]["comments"] and len(rules[1]["comments"]) > 0

    def test_fix_text_passed_through_from_skeleton(self, tmp_path):
        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(_skeleton()))
        output_path = tmp_path / "output.cklb"

        generate_cklb("host1", [], skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        rules = result["stigs"][0]["rules"]
        assert rules[0]["fix_text"] == "Fix it"
        assert rules[1]["fix_text"] == "Fix 2"
        assert rules[2]["fix_text"] == "Fix 3"

    def test_all_status_variants_mapped_correctly(self, tmp_path):
        skeleton = _skeleton()
        # Expand skeleton to have enough rules for all variants
        extra_rules = []
        for i in range(4, 8):
            extra_rules.append(
                {
                    "rule_id": f"SV-00{i}",
                    "rule_version": f"V-00{i}",
                    "group_id": f"G-00{i}",
                    "severity": "medium",
                    "group_title": f"Group {i}",
                    "rule_title": f"Rule {i}",
                    "fix_text": f"Fix {i}",
                    "check_content": f"Check {i}",
                    "discussion": f"Discussion {i}",
                    "ccis": [f"CCI-00{i}"],
                }
            )
        skeleton["stigs"][0]["rules"].extend(extra_rules)

        skeleton_path = tmp_path / "skeleton.json"
        skeleton_path.write_text(json.dumps(skeleton))
        output_path = tmp_path / "output.cklb"

        audit_data = [
            {"rule_id": "V-001", "status": "failed", "checktext": "x"},
            {"rule_id": "V-002", "status": "fail", "checktext": "x"},
            {"rule_id": "V-003", "status": "open", "checktext": "x"},
            {"rule_id": "V-004", "status": "passed", "checktext": "x"},
            {"rule_id": "V-005", "status": "pass", "checktext": "x"},
            {"rule_id": "V-006", "status": "not_a_finding", "checktext": "x"},
            {"rule_id": "V-007", "status": "notafinding", "checktext": "x"},
        ]
        generate_cklb("host1", audit_data, skeleton_path, output_path)

        result = json.loads(output_path.read_text())
        rules = {r["rule_version"]: r for r in result["stigs"][0]["rules"]}
        assert rules["V-001"]["status"] == "open"
        assert rules["V-002"]["status"] == "open"
        assert rules["V-003"]["status"] == "open"
        assert rules["V-004"]["status"] == "not_a_finding"
        assert rules["V-005"]["status"] == "not_a_finding"
        assert rules["V-006"]["status"] == "not_a_finding"
        assert rules["V-007"]["status"] == "not_a_finding"
