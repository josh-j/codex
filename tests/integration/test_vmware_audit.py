"""Integration tests for the VMware audit role (init → checks → finalize)."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestVmwareAuditHealthy:
    """Healthy vmware_ctx should produce no critical alerts."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture, tmp_path):
        fixture = load_fixture("vmware_ctx_healthy.yaml")
        self.result = run_playbook(
            "vmware_audit.yaml",
            extravars={
                "vmware_ctx": fixture["vmware_ctx"],
                "_state_output_dir": str(tmp_path / "state"),
            },
        )

    def test_health_is_healthy(self):
        assert self.result["health"] == "HEALTHY"

    def test_no_critical_alerts(self):
        critical = [a for a in self.result["vmware_alerts"] if a.get("severity") == "CRITICAL"]
        assert len(critical) == 0

    def test_summary_critical_count_zero(self):
        assert self.result["summary"]["critical_count"] == 0

    def test_export_has_required_keys(self):
        export = self.result["export"]
        assert "audit_type" in export
        assert "vmware_vcenter" in export
        assert "check_metadata" in export
        assert export["audit_type"] == "vmware_vcenter"

    def test_export_vmware_vcenter_summary_shape(self):
        summary = self.result["export"]["vmware_vcenter"]["summary"]
        for key in ("total", "critical_count", "warning_count", "info_count", "by_category"):
            assert key in summary

    def test_export_alerts_empty(self):
        assert self.result["export"]["alerts"] == []


class TestVmwareAuditDegraded:
    """Degraded vmware_ctx should produce CRITICAL alerts across multiple categories."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture, tmp_path):
        fixture = load_fixture("vmware_ctx_degraded.yaml")
        self.result = run_playbook(
            "vmware_audit.yaml",
            extravars={
                "vmware_ctx": fixture["vmware_ctx"],
                "_state_output_dir": str(tmp_path / "state"),
            },
        )

    def test_health_is_critical(self):
        assert self.result["health"] == "CRITICAL"

    def test_has_critical_alerts(self):
        critical = [a for a in self.result["vmware_alerts"] if a.get("severity") == "CRITICAL"]
        assert len(critical) > 0

    def test_summary_critical_count(self):
        assert self.result["summary"]["critical_count"] > 0

    def test_alerts_span_multiple_categories(self):
        categories = {a["category"] for a in self.result["vmware_alerts"]}
        # Expect at least: appliance_health, data_protection, storage_capacity, vcenter_alarms
        assert len(categories) >= 3

    def test_ssh_warning_present(self):
        msgs = [a["message"] for a in self.result["vmware_alerts"]]
        assert any("SSH" in m for m in msgs)

    def test_backup_critical_present(self):
        msgs = [a["message"] for a in self.result["vmware_alerts"]]
        assert any("Backup" in m for m in msgs)

    def test_appliance_health_critical(self):
        health_alerts = [a for a in self.result["vmware_alerts"] if a.get("category") == "appliance_health"]
        assert len(health_alerts) > 0
        assert health_alerts[0]["severity"] == "CRITICAL"

    def test_storage_critical_present(self):
        storage = [a for a in self.result["vmware_alerts"] if a.get("category") == "storage_capacity"]
        assert len(storage) > 0

    def test_snapshot_warning_present(self):
        snap = [a for a in self.result["vmware_alerts"] if a.get("category") == "snapshots"]
        assert len(snap) > 0

    def test_tools_warning_present(self):
        tools = [a for a in self.result["vmware_alerts"] if a.get("category") == "workload_compliance"]
        assert len(tools) > 0

    def test_export_health_matches(self):
        assert self.result["export"]["vmware_vcenter"]["health"] == "CRITICAL"

    def test_export_alerts_match_vmware_alerts(self):
        assert len(self.result["export"]["alerts"]) == len(self.result["vmware_alerts"])


class TestVmwareAuditThresholdOverride:
    """Lowered thresholds should trigger capacity alerts on healthy data."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture, tmp_path):
        fixture = load_fixture("vmware_ctx_healthy.yaml")
        self.result = run_playbook(
            "vmware_audit.yaml",
            extravars={
                "vmware_ctx": fixture["vmware_ctx"],
                "_state_output_dir": str(tmp_path / "state"),
                # Lower cluster thresholds so 45% CPU and 55% mem trigger
                "vmware_cluster_cpu_warning_pct": 40.0,
                "vmware_cluster_memory_warning_pct": 50.0,
            },
        )

    def test_cluster_capacity_alerts_triggered(self):
        capacity = [a for a in self.result["vmware_alerts"] if a.get("category") == "cluster_capacity"]
        assert len(capacity) >= 1
