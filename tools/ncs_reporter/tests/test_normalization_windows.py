"""Tests for Windows normalization logic."""

from typing import Any

from ncs_reporter.normalization.windows import normalize_windows


def _minimal_bundle(**overrides):
    base: dict[str, Any] = {
        "metadata": {"timestamp": "2026-02-26T12:00:00Z"},
        "data": {
            "ccm_service": {"state": "running"},
            "configmgr_apps": [],
            "installed_apps": [],
            "update_results": [],
        },
    }
    base["data"].update(overrides)
    return base


class TestNormalizeWindowsBasic:
    def test_healthy_baseline(self):
        result = normalize_windows(_minimal_bundle())
        assert result.health == "HEALTHY"
        assert len(result.alerts) == 0

    def test_ccmexec_not_running_generates_warning(self):
        result = normalize_windows(_minimal_bundle(ccm_service={"state": "stopped"}))
        assert result.health == "WARNING"
        assert len(result.alerts) == 1
        alert = result.alerts[0]
        assert alert.severity == "WARNING"
        assert alert.category == "services"
        assert "CCMExec" in alert.message

    def test_ccmexec_unknown_state(self):
        result = normalize_windows(_minimal_bundle(ccm_service={"state": "unknown"}))
        assert len(result.alerts) >= 1
        assert any("CCMExec" in a.message for a in result.alerts)

    def test_failed_updates_generate_warning(self):
        updates = [
            {"name": "App1", "failed": True},
            {"name": "App2", "failed": True},
            {"name": "App3", "failed": False},
        ]
        result = normalize_windows(_minimal_bundle(update_results=updates))
        assert any("failed" in a.message.lower() for a in result.alerts)
        # Should report 2 failed
        failed_alert = [a for a in result.alerts if "failed" in a.message.lower()][0]
        assert "2" in failed_alert.message

    def test_configmgr_apps_parsed(self):
        apps = {"AllApps": [{"name": "App1"}, {"name": "App2"}], "AppsToUpdate": [{"name": "App1"}]}
        result = normalize_windows(_minimal_bundle(configmgr_apps=apps))
        summary = result.windows_audit["summary"]
        assert summary["applications"]["configmgr_count"] == 2
        assert summary["applications"]["apps_to_update_count"] == 1

    def test_installed_apps_counted(self):
        result = normalize_windows(_minimal_bundle(installed_apps=[{"name": "7zip"}, {"name": "Chrome"}]))
        summary = result.windows_audit["summary"]
        assert summary["applications"]["installed_count"] == 2


class TestNormalizeWindowsEdgeCases:
    def test_empty_bundle(self):
        result = normalize_windows({})
        # Empty bundle means CCMExec is not running -> WARNING
        assert result.health == "WARNING"
        assert result.metadata.audit_type == "windows_audit"

    def test_missing_ccm_service_key(self):
        result = normalize_windows({"data": {}})
        # CCMExec not running (missing = not running)
        assert any("CCMExec" in a.message for a in result.alerts)

    def test_none_values_in_payload(self):
        result = normalize_windows({
            "data": {
                "ccm_service": None,
                "configmgr_apps": None,
                "installed_apps": None,
                "update_results": None,
            }
        })
        # Should not crash
        assert result.metadata.audit_type == "windows_audit"

    def test_both_ccmexec_and_updates_failures(self):
        result = normalize_windows(_minimal_bundle(
            ccm_service={"state": "stopped"},
            update_results=[{"name": "patch1", "failed": True}],
        ))
        assert len(result.alerts) == 2
        categories = {a.category for a in result.alerts}
        assert "services" in categories
        assert "patching" in categories
