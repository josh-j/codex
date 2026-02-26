"""Integration tests for Ubuntu system audit check.yaml."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestUbuntuAuditHealthy:
    """Healthy ubuntu_ctx should produce no alerts."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture):
        fixture = load_fixture("ubuntu_ctx_healthy.yaml")
        self.result = run_playbook(
            "ubuntu_audit_check.yaml",
            extravars={"ubuntu_ctx": fixture["ubuntu_ctx"]},
        )

    def test_health_is_healthy(self):
        assert self.result["health"] == "HEALTHY"

    def test_no_alerts(self):
        assert len(self.result["ubuntu_alerts"]) == 0


class TestUbuntuAuditCritical:
    """Critical ubuntu_ctx should produce multiple alerts."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture):
        fixture = load_fixture("ubuntu_ctx_critical.yaml")
        self.result = run_playbook(
            "ubuntu_audit_check.yaml",
            extravars={"ubuntu_ctx": fixture["ubuntu_ctx"]},
        )

    def test_health_is_critical(self):
        assert self.result["health"] == "CRITICAL"

    def test_memory_alert_present(self):
        msgs = [a["message"] for a in self.result["ubuntu_alerts"]]
        assert any("Memory" in m or "99" in m for m in msgs)

    def test_service_alert_is_critical(self):
        svc_alerts = [a for a in self.result["ubuntu_alerts"] if a.get("category") == "availability"]
        assert len(svc_alerts) > 0
        assert svc_alerts[0]["severity"] == "CRITICAL"

    def test_reboot_warning_present(self):
        msgs = [a["message"] for a in self.result["ubuntu_alerts"]]
        assert any("reboot" in m.lower() for m in msgs)

    def test_storage_alerts_present(self):
        storage = [a for a in self.result["ubuntu_alerts"] if "Storage" in a.get("message", "")]
        assert len(storage) >= 1

    def test_uptime_warning_present(self):
        msgs = [a["message"] for a in self.result["ubuntu_alerts"]]
        assert any("Uptime" in m for m in msgs)


class TestUbuntuAuditThresholdOverride:
    """Lowered storage threshold triggers additional alert on healthy data."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture):
        fixture = load_fixture("ubuntu_ctx_healthy.yaml")
        self.result = run_playbook(
            "ubuntu_audit_check.yaml",
            extravars={
                "ubuntu_ctx": fixture["ubuntu_ctx"],
                # Lower storage threshold so 55% triggers
                "ubuntu_storage_warning_pct": 50.0,
            },
        )

    def test_storage_alert_triggered(self):
        storage = [a for a in self.result["ubuntu_alerts"] if "Storage" in a.get("message", "")]
        assert len(storage) >= 1
