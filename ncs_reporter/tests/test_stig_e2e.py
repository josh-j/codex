"""End-to-End tests for STIG audit and remediation pipeline."""

import json
import tempfile
import unittest
from pathlib import Path

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import main


class TestStigE2E(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Setup structure
        self.platform_root = self.root / "platform"
        self.reports_root = self.root / "reports"
        self.host_dir = self.platform_root / "vmware" / "esxi-01"
        self.host_dir.mkdir(parents=True)
        self.reports_root.mkdir(parents=True)

        # Skeleton dir (actual repo path)
        self.skeleton_dir = Path(__file__).parent.parent / "src" / "ncs_reporter" / "cklb_skeletons"

    def tearDown(self):
        self.test_dir.cleanup()

    def _write_raw_data(self, status="failed"):
        raw_data = {
            "metadata": {
                "host": "esxi-01",
                "audit_type": "stig_esxi",
                "timestamp": "2026-02-26T23:00:00Z",
                "engine": "ncs_collector_callback",
            },
            "data": [
                {
                    "id": "V-256379",
                    "status": status,
                    "severity": "medium",
                    "title": "stigrule_256379_account_lock_failures",
                    "checktext": f"Rule Requirement: Security.AccountLockFailures must be set to 3. Status: {status}",
                }
            ],
            "target_type": "esxi",
        }
        with open(self.host_dir / "raw_stig_esxi.yaml", "w") as f:
            yaml.dump(raw_data, f)

    def _write_groups(self):
        groups = {"all": ["esxi-01"], "vcenters": [], "esxi_hosts": ["esxi-01"]}
        groups_path = self.platform_root / "inventory_groups.json"
        with open(groups_path, "w") as f:
            json.dump(groups, f)
        return groups_path

    def test_stig_audit_and_remediation_lifecycle(self):
        # 1. Simulate Audit Phase (Finding exists)
        self._write_raw_data(status="failed")
        groups_path = self._write_groups()

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(groups_path),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        # Verify Finding in aggregated state
        fleet_state_path = self.platform_root / "all_hosts_state.yaml"
        self.assertTrue(fleet_state_path.exists())
        with open(fleet_state_path) as f:
            state = yaml.safe_load(f)

        host_stig = state["hosts"]["esxi-01"]["stig_esxi"]
        self.assertEqual(host_stig["health"], "WARNING")
        self.assertEqual(host_stig["summary"]["warning_count"], 1)
        self.assertEqual(host_stig["full_audit"][0]["status"], "open")

        # Verify CKLB generation
        cklb_path = self.reports_root / "cklb" / "esxi-01_esxi.cklb"
        self.assertTrue(cklb_path.exists())
        with open(cklb_path) as f:
            cklb = json.load(f)
            # Find the rule in the skeleton-based CKLB by matching the group_id (V-number)
            rule = next(r for s in cklb["stigs"] for r in s["rules"] if r["group_id"] == "V-256379")
            self.assertEqual(rule["status"], "open")

        # 2. Simulate Remediation Phase (Finding fixed)
        self._write_raw_data(status="pass")

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(groups_path),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0)

        # Verify Clean state
        with open(fleet_state_path) as f:
            state = yaml.safe_load(f)

        host_stig = state["hosts"]["esxi-01"]["stig_esxi"]
        self.assertEqual(host_stig["health"], "HEALTHY")
        self.assertEqual(host_stig["summary"]["warning_count"], 0)
        self.assertEqual(host_stig["full_audit"][0]["status"], "pass")

        # Verify CKLB flipped to not_a_finding
        with open(cklb_path) as f:
            cklb = json.load(f)
            rule = next(r for s in cklb["stigs"] for r in s["rules"] if r["group_id"] == "V-256379")
            self.assertEqual(rule["status"], "not_a_finding")

    def test_stig_html_report_content(self):
        """Verify STIG HTML reports are generated with expected content."""
        self._write_raw_data(status="failed")
        groups_path = self._write_groups()

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(groups_path),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        # Fleet report
        fleet_report = self.reports_root / "stig_fleet_report.html"
        self.assertTrue(fleet_report.exists(), "STIG fleet report should exist")
        fleet_content = fleet_report.read_text()
        self.assertIn("esxi-01", fleet_content)

        # Host report: reports_root/platform/vmware/esxi/esxi-01/esxi-01_stig_esxi.html
        host_report = self.reports_root / "platform" / "vmware" / "esxi" / "esxi-01" / "esxi-01_stig_esxi.html"

        self.assertTrue(host_report.exists(), "STIG host report should exist")
        host_content = host_report.read_text()
        self.assertIn("esxi-01", host_content)
        self.assertTrue(
            "open" in host_content or "not_a_finding" in host_content,
            "Host STIG report should contain status indicators",
        )


class TestVmStigE2E(unittest.TestCase):
    def setUp(self):
        self.runner = CliRunner()
        self.test_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.test_dir.name)

        # Setup structure
        self.platform_root = self.root / "platform"
        self.reports_root = self.root / "reports"
        self.host_dir = self.platform_root / "vmware" / "vc-01"
        self.host_dir.mkdir(parents=True)
        self.reports_root.mkdir(parents=True)

    def tearDown(self):
        self.test_dir.cleanup()

    def _write_raw_data(self, status="failed"):
        raw_data = {
            "metadata": {
                "host": "vc-01",
                "audit_type": "stig_vm",
                "timestamp": "2026-02-26T23:00:00Z",
                "engine": "ncs_collector_callback",
            },
            "data": [
                {
                    "id": "V-256450",
                    "status": status,
                    "severity": "medium",
                    "title": "stigrule_256450_copy_disabled",
                    "checktext": f"Rule Requirement: Copy operations must be disabled. Status: {status}",
                }
            ],
            "target_type": "vm",
        }
        # In actual telemetry, VM results are emitted by the vCenter that manages them
        with open(self.host_dir / "raw_stig_vm.yaml", "w") as f:
            yaml.dump(raw_data, f)

    def _write_groups(self):
        groups = {"all": ["vc-01"], "vcenters": ["vc-01"], "esxi_hosts": []}
        groups_path = self.platform_root / "inventory_groups.json"
        with open(groups_path, "w") as f:
            json.dump(groups, f)
        return groups_path

    def test_vm_stig_audit_and_remediation_lifecycle(self):
        # 1. Simulate Audit Phase (Finding exists)
        self._write_raw_data(status="failed")
        groups_path = self._write_groups()

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(groups_path),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0, f"CLI failed: {result.output}")

        # Verify Finding in aggregated state
        fleet_state_path = self.platform_root / "all_hosts_state.yaml"
        self.assertTrue(fleet_state_path.exists())
        with open(fleet_state_path) as f:
            state = yaml.safe_load(f)

        host_stig = state["hosts"]["vc-01"]["stig_vm"]
        self.assertEqual(host_stig["health"], "WARNING")
        self.assertEqual(host_stig["full_audit"][0]["status"], "open")

        # Verify CKLB generation
        cklb_path = self.reports_root / "cklb" / "vc-01_vm.cklb"
        self.assertTrue(cklb_path.exists())
        with open(cklb_path) as f:
            cklb = json.load(f)
            rule = next(r for s in cklb["stigs"] for r in s["rules"] if r["group_id"] == "V-256450")
            self.assertEqual(rule["status"], "open")

        # 2. Simulate Remediation Phase (Finding fixed)
        self._write_raw_data(status="pass")

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.reports_root),
                "--groups",
                str(groups_path),
                "--report-stamp",
                "20260226",
            ],
        )

        self.assertEqual(result.exit_code, 0)

        # Verify Clean state
        with open(fleet_state_path) as f:
            state = yaml.safe_load(f)

        host_stig = state["hosts"]["vc-01"]["stig_vm"]
        self.assertEqual(host_stig["health"], "HEALTHY")
        self.assertEqual(host_stig["full_audit"][0]["status"], "pass")

        # Verify CKLB flipped to not_a_finding
        with open(cklb_path) as f:
            cklb = json.load(f)
            rule = next(r for s in cklb["stigs"] for r in s["rules"] if r["group_id"] == "V-256450")
            self.assertEqual(rule["status"], "not_a_finding")
