"""Tests for Windows view-model builders."""

from ncs_reporter.view_models.windows import (
    _coerce_windows_audit,
    build_windows_fleet_view,
    build_windows_node_view,
)


def _windows_bundle(health="OK", alerts=None):
    return {
        "windows_audit": {
            "health": health,
            "summary": {
                "applications": {"configmgr_count": 5, "installed_count": 10},
                "updates": {"results_count": 3, "failed_count": 0},
            },
            "alerts": alerts or [],
        }
    }


class TestCoerceWindowsAudit:
    def test_standard_key(self):
        audit = _coerce_windows_audit({"windows_audit": {"health": "OK"}})
        assert audit["health"] == "OK"

    def test_windows_key(self):
        audit = _coerce_windows_audit({"windows": {"health": "WARNING"}})
        assert audit["health"] == "WARNING"

    def test_flat_bundle(self):
        audit = _coerce_windows_audit({"health": "OK", "data": {}})
        assert audit["health"] == "OK"

    def test_empty_bundle(self):
        audit = _coerce_windows_audit({})
        assert audit == {}

    def test_none_bundle(self):
        audit = _coerce_windows_audit(None)
        assert audit == {}


class TestBuildWindowsFleetView:
    def test_basic_fleet(self):
        hosts = {"win01": _windows_bundle(), "win02": _windows_bundle(health="WARNING")}
        view = build_windows_fleet_view(hosts, report_stamp="20260226")
        assert view["meta"]["report_stamp"] == "20260226"
        assert view["fleet"]["asset_count"] == 2
        assert len(view["rows"]) == 2
        # Rows should be sorted by name
        assert view["rows"][0]["name"] == "win01"

    def test_fleet_with_alerts(self):
        alerts = [
            {"severity": "CRITICAL", "category": "services", "message": "CCMExec down"},
            {"severity": "WARNING", "category": "patching", "message": "Updates failed"},
        ]
        hosts = {"win01": _windows_bundle(health="CRITICAL", alerts=alerts)}
        view = build_windows_fleet_view(hosts)
        assert len(view["active_alerts"]) == 2
        assert view["active_alerts"][0]["severity"] == "CRITICAL"

    def test_empty_hosts(self):
        view = build_windows_fleet_view({})
        assert view["fleet"]["asset_count"] == 0
        assert view["rows"] == []
        assert view["active_alerts"] == []

    def test_skip_keys_excluded(self):
        hosts = {"win01": _windows_bundle(), "summary": {"should": "skip"}}
        view = build_windows_fleet_view(hosts)
        assert view["fleet"]["asset_count"] == 1

    def test_alert_counts_in_row(self):
        alerts = [{"severity": "CRITICAL", "category": "x", "message": "y"}]
        hosts = {"win01": _windows_bundle(alerts=alerts)}
        view = build_windows_fleet_view(hosts)
        row = view["rows"][0]
        assert row["summary"]["alerts"]["critical"] == 1
        assert row["summary"]["alerts"]["total"] == 1


class TestBuildWindowsNodeView:
    def test_basic_node(self):
        view = build_windows_node_view(
            _windows_bundle(), hostname="win01", report_stamp="20260226"
        )
        assert view["node"]["name"] == "win01"
        assert view["meta"]["report_stamp"] == "20260226"
        assert view["node"]["status"]["raw"] == "OK"

    def test_node_with_alerts(self):
        alerts = [{"severity": "WARNING", "category": "test", "message": "test"}]
        view = build_windows_node_view(_windows_bundle(alerts=alerts), hostname="win01")
        assert len(view["node"]["alerts"]) == 1

    def test_node_unknown_hostname(self):
        view = build_windows_node_view(_windows_bundle())
        assert view["node"]["name"] == "unknown"
