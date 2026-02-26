"""Integration tests for core state export role."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestStateExport:
    """Test the state export role writes correct YAML structure."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, tmp_path):
        export_path = tmp_path / "state" / "host_state.yaml"
        self.result = run_playbook(
            "state_export.yaml",
            extravars={
                "_state_export_path": str(export_path),
                "export_data": {
                    "audit_type": "vmware_vcenter",
                    "audit_failed": False,
                    "health": "HEALTHY",
                    "summary": {"total": 5, "critical_count": 0},
                    "alerts": [],
                },
            },
        )

    def test_exported_yaml_has_metadata(self):
        exported = self.result["exported_yaml"]
        assert "metadata" in exported
        assert "host" in exported["metadata"]
        assert "audit_type" in exported["metadata"]
        assert "timestamp" in exported["metadata"]

    def test_exported_yaml_has_health(self):
        exported = self.result["exported_yaml"]
        assert exported["health"] == "HEALTHY"

    def test_exported_yaml_has_summary(self):
        exported = self.result["exported_yaml"]
        assert "summary" in exported
        assert exported["summary"]["total"] == 5

    def test_exported_yaml_has_data(self):
        exported = self.result["exported_yaml"]
        assert "data" in exported
        assert exported["data"]["audit_type"] == "vmware_vcenter"

    def test_metadata_host_is_localhost(self):
        exported = self.result["exported_yaml"]
        assert exported["metadata"]["host"] == "localhost"
