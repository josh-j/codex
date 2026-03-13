"""Integration test: stig_xml callback JSON artifact → normalize_stig → generate_cklb.

The stig_xml callback writes xccdf-results_<host>.json as a bare JSON list:

    [
        {
            "id": "V-256376",
            "rule_id": "V-256376",
            "name": "esxi-01",
            "status": "failed",
            "title": "stigrule_256376_dcui_access",
            "severity": "medium",
            "fixtext": "Fix text here",
            "checktext": "DCUI.Access must be set to root only."
        }
    ]

This format is distinct from the ncs_collector envelope (metadata + data dict). Both
inputs are supported by normalize_stig, but the stig_xml list path had no test coverage.

These tests verify the full path:
    stig_xml JSON list → normalize_stig → STIGAuditModel.full_audit → generate_cklb → .cklb
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any

from ncs_reporter.cklb_export import generate_cklb
from ncs_reporter.normalization.stig import normalize_stig


# ---------------------------------------------------------------------------
# Minimal skeleton that mirrors real CKLB skeleton rule structure.
# Rules use group_id = V-XXXXXX, matching stig_xml's id/rule_id field.
# ---------------------------------------------------------------------------


def _make_skeleton(*group_ids: str) -> dict[str, Any]:
    """Build a minimal CKLB skeleton with rules keyed by group_id (V-number)."""
    rules = [
        {
            "rule_id": f"SV-{gid[2:]}r1_rule",
            "rule_version": f"SV-{gid[2:]}r1",
            "group_id": gid,
            "severity": "medium",
            "group_title": f"Group for {gid}",
            "rule_title": f"Rule title for {gid}",
            "fix_text": f"Fix text for {gid}",
            "check_content": f"Check content for {gid}",
            "discussion": "",
            "ccis": ["CCI-000054"],
        }
        for gid in group_ids
    ]
    return {
        "title": "VMware vSphere 7.0 ESXi STIG",
        "id": "vsphere7-esxi",
        "cklb_version": "1.0",
        "stigs": [
            {
                "stig_name": "VMware_vSphere_7.0_ESXi_STIG",
                "display_name": "ESXi 7.0",
                "stig_id": "VMware_vSphere_7.0_ESXi",
                "release_info": "Release: 4",
                "version": "1",
                "uuid": "test-uuid",
                "size": len(rules),
                "rules": rules,
            }
        ],
    }


# ---------------------------------------------------------------------------
# Sample stig_xml JSON output (as _dump_json produces it)
# ---------------------------------------------------------------------------


def _stig_xml_row(
    rule_num: str,
    status: str,
    host: str = "esxi-01",
    checktext: str = "",
) -> dict[str, Any]:
    """Return a single row in the format stig_xml._dump_json emits."""
    return {
        "id": f"V-{rule_num}",
        "rule_id": f"V-{rule_num}",
        "name": host,
        "status": status,
        "title": f"stigrule_{rule_num}_check",
        "severity": "medium",
        "fixtext": f"Fix for {rule_num}",
        "checktext": checktext or f"Check text for {rule_num}",
    }


# ===========================================================================
# normalize_stig accepts the bare list format from stig_xml
# ===========================================================================


class TestNormalizeStigAcceptsStigXmlList(unittest.TestCase):
    """normalize_stig must handle the bare-list format written by stig_xml._dump_json."""

    def test_bare_list_is_accepted(self) -> None:
        rows = [_stig_xml_row("256376", "failed"), _stig_xml_row("256378", "pass")]
        model = normalize_stig(rows)
        self.assertIsNotNone(model)
        self.assertIsInstance(model.full_audit, list)
        self.assertEqual(len(model.full_audit), 2)

    def test_failed_row_becomes_open_status(self) -> None:
        rows = [_stig_xml_row("256376", "failed")]
        model = normalize_stig(rows)
        self.assertEqual(model.full_audit[0]["status"], "open")

    def test_pass_row_stays_pass(self) -> None:
        rows = [_stig_xml_row("256378", "pass")]
        model = normalize_stig(rows)
        self.assertEqual(model.full_audit[0]["status"], "pass")

    def test_na_row_stays_na(self) -> None:
        rows = [_stig_xml_row("256379", "na")]
        model = normalize_stig(rows)
        self.assertEqual(model.full_audit[0]["status"], "na")

    def test_fixed_maps_to_pass(self) -> None:
        """stig_xml emits 'fixed' for changed tasks in apply-mode; normalize_stig maps this to 'pass'."""
        rows = [_stig_xml_row("256380", "fixed")]
        model = normalize_stig(rows)
        self.assertEqual(model.full_audit[0]["status"], "pass")

    def test_health_warning_on_open_findings(self) -> None:
        rows = [_stig_xml_row("256376", "failed")]
        model = normalize_stig(rows)
        self.assertIn(model.health, ("WARNING", "CRITICAL"))

    def test_health_healthy_when_all_pass(self) -> None:
        rows = [_stig_xml_row("256376", "pass"), _stig_xml_row("256378", "pass")]
        model = normalize_stig(rows)
        self.assertEqual(model.health, "HEALTHY")

    def test_rule_id_field_preserved(self) -> None:
        rows = [_stig_xml_row("256376", "pass")]
        model = normalize_stig(rows)
        self.assertEqual(model.full_audit[0]["rule_id"], "V-256376")

    def test_checktext_preserved(self) -> None:
        rows = [_stig_xml_row("256376", "failed", checktext="DCUI.Access must be root.")]
        model = normalize_stig(rows)
        self.assertIn("DCUI.Access", model.full_audit[0]["description"] or model.full_audit[0].get("checktext", ""))

    def test_empty_list_produces_healthy_model(self) -> None:
        model = normalize_stig([])
        self.assertEqual(model.health, "HEALTHY")
        self.assertEqual(model.full_audit, [])
        self.assertEqual(model.alerts, [])


# ===========================================================================
# generate_cklb matches stig_xml output via group_id (V-number)
# ===========================================================================


class TestGenerateCklbFromStigXmlOutput(unittest.TestCase):
    """generate_cklb must match stig_xml rows against skeleton rules using group_id."""

    def setUp(self) -> None:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _run(self, rows: list[dict[str, Any]], *group_ids: str) -> dict[str, Any]:
        """Write skeleton, run generate_cklb, return parsed CKLB."""
        skel_path = self.tmp / "skeleton.json"
        skel_path.write_text(json.dumps(_make_skeleton(*group_ids)))
        out_path = self.tmp / "output.cklb"
        generate_cklb("esxi-01", rows, skel_path, out_path)
        return json.loads(out_path.read_text())

    def test_failed_rule_maps_to_open_in_cklb(self) -> None:
        rows = [_stig_xml_row("256376", "failed", checktext="Bad value found.")]
        cklb = self._run(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "open")
        self.assertIn("Bad value found.", rule["finding_details"])

    def test_pass_rule_maps_to_not_a_finding(self) -> None:
        rows = [_stig_xml_row("256376", "pass")]
        cklb = self._run(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "not_a_finding")

    def test_na_rule_leaves_not_reviewed(self) -> None:
        """'na' from stig_xml does not map to 'open' or 'not_a_finding'; rule stays not_reviewed."""
        rows = [_stig_xml_row("256376", "na")]
        cklb = self._run(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "not_reviewed")

    def test_unmatched_rule_in_skeleton_stays_not_reviewed(self) -> None:
        rows = [_stig_xml_row("256376", "failed")]
        # Skeleton has V-256999 but audit has V-256376 — no match
        cklb = self._run(rows, "V-256999")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "not_reviewed")

    def test_mixed_results_across_multiple_rules(self) -> None:
        rows = [
            _stig_xml_row("256376", "failed", checktext="Finding A"),
            _stig_xml_row("256378", "pass"),
            _stig_xml_row("256379", "pass"),
        ]
        cklb = self._run(rows, "V-256376", "V-256378", "V-256379")
        rules = {r["group_id"]: r for r in cklb["stigs"][0]["rules"]}
        self.assertEqual(rules["V-256376"]["status"], "open")
        self.assertEqual(rules["V-256378"]["status"], "not_a_finding")
        self.assertEqual(rules["V-256379"]["status"], "not_a_finding")

    def test_hostname_recorded_in_target_data(self) -> None:
        cklb = self._run([], "V-256376")
        self.assertEqual(cklb["target_data"]["host_name"], "esxi-01")
        self.assertEqual(cklb["target_data"]["fqdn"], "esxi-01")

    def test_fix_text_from_skeleton_passed_through(self) -> None:
        cklb = self._run([], "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["fix_text"], "Fix text for V-256376")


# ===========================================================================
# Full pipeline: stig_xml JSON → normalize_stig → generate_cklb
# ===========================================================================


class TestStigXmlToCklbPipeline(unittest.TestCase):
    """End-to-end: read stig_xml JSON list, normalize, then produce a CKLB file."""

    def setUp(self) -> None:
        import tempfile

        self._tmpdir = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmpdir.name)

    def tearDown(self) -> None:
        self._tmpdir.cleanup()

    def _write_stig_xml_json(self, rows: list[dict[str, Any]]) -> Path:
        """Write a stig_xml-format JSON file (bare list) as the callback would."""
        p = self.tmp / "xccdf-results_esxi-01.json"
        p.write_text(json.dumps(rows, indent=2))
        return p

    def _pipeline(self, rows: list[dict[str, Any]], *group_ids: str) -> dict[str, Any]:
        """Simulate reading the stig_xml artifact and producing a CKLB."""
        # Step 1: Read the JSON artifact (as a consumer of stig_xml output would)
        artifact_path = self._write_stig_xml_json(rows)
        raw_list: list[dict[str, Any]] = json.loads(artifact_path.read_text())

        # Step 2: Normalize (normalize_stig handles bare list)
        model = normalize_stig(raw_list, stig_target_type="esxi")

        # Step 3: Generate CKLB from normalized full_audit
        skel_path = self.tmp / "skeleton.json"
        skel_path.write_text(json.dumps(_make_skeleton(*group_ids)))
        out_path = self.tmp / "output.cklb"
        generate_cklb("esxi-01", model.full_audit, skel_path, out_path)

        return json.loads(out_path.read_text())

    def test_failed_finding_reaches_cklb_as_open(self) -> None:
        rows = [_stig_xml_row("256376", "failed", checktext="DCUI.Access is not restricted.")]
        cklb = self._pipeline(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "open")
        self.assertIn("DCUI.Access", rule["finding_details"])

    def test_passed_finding_reaches_cklb_as_not_a_finding(self) -> None:
        rows = [_stig_xml_row("256376", "pass", checktext="DCUI.Access is correctly set.")]
        cklb = self._pipeline(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "not_a_finding")

    def test_apply_mode_fixed_reaches_cklb_as_not_a_finding(self) -> None:
        """apply-mode 'fixed' status (changed=True in non-check-mode) must produce not_a_finding."""
        rows = [_stig_xml_row("256376", "fixed", checktext="Setting corrected by remediation.")]
        cklb = self._pipeline(rows, "V-256376")
        rule = cklb["stigs"][0]["rules"][0]
        self.assertEqual(rule["status"], "not_a_finding")

    def test_multi_host_stig_xml_output_for_one_host(self) -> None:
        """stig_xml emits separate JSON files per host; each file is a list for that host."""
        # Simulate two separate host files
        for host, status, gid in [
            ("esxi-01", "failed", "V-256376"),
            ("esxi-02", "pass", "V-256376"),
        ]:
            rows = [_stig_xml_row("256376", status, host=host)]
            artifact_path = self.tmp / f"xccdf-results_{host}.json"
            artifact_path.write_text(json.dumps(rows))

            raw_list = json.loads(artifact_path.read_text())
            model = normalize_stig(raw_list, stig_target_type="esxi")

            skel_path = self.tmp / "skeleton.json"
            skel_path.write_text(json.dumps(_make_skeleton("V-256376")))
            out_path = self.tmp / f"{host}.cklb"
            generate_cklb(host, model.full_audit, skel_path, out_path)

            cklb = json.loads(out_path.read_text())
            rule = cklb["stigs"][0]["rules"][0]

            expected = "open" if status == "failed" else "not_a_finding"
            self.assertEqual(
                rule["status"],
                expected,
                f"Host {host} with status={status!r} should produce {expected!r}",
            )

    def test_large_audit_all_statuses_roundtrip(self) -> None:
        """A realistic mixed-result audit roundtrips all status types correctly."""
        rule_data = [
            ("256376", "failed"),  # non-compliant → open
            ("256378", "pass"),  # compliant → not_a_finding
            ("256379", "pass"),  # compliant → not_a_finding
            ("256380", "fixed"),  # remediated → not_a_finding
            ("256381", "na"),  # not applicable → not_reviewed
        ]
        rows = [_stig_xml_row(num, status) for num, status in rule_data]
        group_ids = [f"V-{num}" for num, _ in rule_data]
        cklb = self._pipeline(rows, *group_ids)

        rules = {r["group_id"]: r for r in cklb["stigs"][0]["rules"]}
        self.assertEqual(rules["V-256376"]["status"], "open")
        self.assertEqual(rules["V-256378"]["status"], "not_a_finding")
        self.assertEqual(rules["V-256379"]["status"], "not_a_finding")
        self.assertEqual(rules["V-256380"]["status"], "not_a_finding")
        self.assertEqual(rules["V-256381"]["status"], "not_reviewed")


if __name__ == "__main__":
    unittest.main()
