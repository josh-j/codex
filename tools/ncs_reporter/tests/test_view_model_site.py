"""Tests for site dashboard view-model builder."""

from ncs_reporter.view_models.site import build_site_dashboard_view


def _linux_bundle(health="OK", alerts=None):
    return {
        "linux_system": {
            "health": health,
            "alerts": alerts or [],
            "summary": {"critical_count": 0, "warning_count": 0},
        }
    }


def _vmware_bundle(health="green", alerts=None):
    return {
        "vmware_vcenter": {
            "health": health,
            "alerts": alerts or [],
            "discovery": {
                "summary": {"clusters": 1, "hosts": 2, "vms": 10},
                "inventory": {"clusters": {"list": [{"name": "C1", "utilization": {"cpu_pct": 50, "memory_pct": 40}}]}},
            },
            "vcenter_health": {"health": health},
        }
    }


def _windows_bundle(health="OK", alerts=None):
    return {
        "windows_audit": {
            "health": health,
            "alerts": alerts or [],
            "summary": {},
        }
    }


class TestBuildSiteDashboardView:
    def test_basic_site_dashboard(self):
        hosts = {
            "hosts": {
                "linux-01": _linux_bundle(),
                "vc-01": _vmware_bundle(),
                "win-01": _windows_bundle(),
            }
        }
        groups = {"ubuntu_servers": ["linux-01"], "vcenters": ["vc-01"], "windows_servers": ["win-01"]}
        view = build_site_dashboard_view(hosts, inventory_groups=groups, report_stamp="20260226")

        assert view["meta"]["report_stamp"] == "20260226"
        assert view["platforms"]["linux"]["asset_count"] == 1
        assert view["platforms"]["vmware"]["asset_count"] == 1
        assert view["platforms"]["windows"]["asset_count"] == 1
        assert view["totals"]["total"] == 0  # no alerts

    def test_linux_critical_propagates(self):
        alerts = [{"severity": "CRITICAL", "category": "disk", "message": "Disk full"}]
        hosts = {"hosts": {"h1": _linux_bundle(health="CRITICAL", alerts=alerts)}}
        view = build_site_dashboard_view(hosts)
        assert view["platforms"]["linux"]["status"]["raw"] == "CRITICAL"
        assert view["totals"]["critical"] >= 1
        assert len(view["alerts"]) >= 1

    def test_vmware_warning_propagates(self):
        alerts = [{"severity": "WARNING", "category": "health", "message": "Memory degraded"}]
        hosts = {"hosts": {"vc1": _vmware_bundle(health="yellow", alerts=alerts)}}
        view = build_site_dashboard_view(hosts)
        assert view["platforms"]["vmware"]["status"]["raw"] == "WARNING"

    def test_windows_fallback_alert(self):
        # No explicit alerts but health is CRITICAL
        hosts = {"hosts": {"w1": _windows_bundle(health="CRITICAL")}}
        view = build_site_dashboard_view(hosts)
        assert view["platforms"]["windows"]["status"]["raw"] == "CRITICAL"
        assert len(view["alerts"]) >= 1
        assert view["alerts"][0]["audit_type"] == "schema_windows"

    def test_empty_hosts(self):
        view = build_site_dashboard_view({})
        assert view["totals"]["total"] == 0
        assert view["alerts"] == []
        assert view["compute"]["nodes"] == []

    def test_alerts_sorted_critical_first(self):
        hosts = {
            "hosts": {
                "h1": _linux_bundle(alerts=[{"severity": "WARNING", "category": "test", "message": "warn"}]),
                "h2": _linux_bundle(alerts=[{"severity": "CRITICAL", "category": "test", "message": "crit"}]),
            }
        }
        view = build_site_dashboard_view(hosts)
        # Critical alerts should come first
        assert view["alerts"][0]["severity"] == "CRITICAL"

    def test_stig_fleet_included(self):
        hosts = {
            "hosts": {
                "h1": {
                    "stig_esxi": {
                        "health": "WARNING",
                        "target_type": "esxi",
                        "full_audit": [{"id": "V-001", "status": "open", "severity": "CAT_I", "title": "Rule"}],
                        "alerts": [],
                    }
                }
            }
        }
        view = build_site_dashboard_view(hosts)
        assert "stig_fleet" in view["security"]
        assert view["security"]["stig_fleet"]["fleet"]["totals"]["hosts"] >= 1

    def test_compute_nodes_populated(self):
        hosts = {"hosts": {"vc1": _vmware_bundle()}}
        view = build_site_dashboard_view(hosts)
        assert len(view["compute"]["nodes"]) == 1
        assert view["compute"]["nodes"][0]["host"] == "vc1"

    def test_no_groups_defaults_to_zero(self):
        hosts = {"hosts": {"h1": _linux_bundle()}}
        view = build_site_dashboard_view(hosts)
        assert view["platforms"]["linux"]["asset_count"] == 0
        assert view["platforms"]["vmware"]["asset_count"] == 0
