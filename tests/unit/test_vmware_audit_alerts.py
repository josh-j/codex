import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "plugins"
    / "filter"
    / "audit.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("vmware_audit_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AuditHealthAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    # -- audit_health_alerts --------------------------------------------------

    def test_healthy_vcsa_returns_no_alerts(self):
        ctx = {
            "health": {
                "appliance": {
                    "health": {"overall": "green"},
                    "backup": {"enabled": True},
                    "config": {"ssh_enabled": False},
                }
            },
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        self.assertEqual(alerts, [])

    def test_red_overall_emits_critical(self):
        ctx = {
            "health": {"appliance": {"health": {"overall": "red"}, "backup": {"enabled": True}, "config": {}}},
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        sevs = [a["severity"] for a in alerts]
        self.assertIn("CRITICAL", sevs)
        self.assertTrue(any("Component Failure" in a["message"] for a in alerts))

    def test_yellow_overall_emits_warning(self):
        ctx = {
            "health": {"appliance": {"health": {"overall": "yellow"}, "backup": {"enabled": True}, "config": {}}},
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        sevs = [a["severity"] for a in alerts]
        self.assertIn("WARNING", sevs)
        self.assertTrue(any("Degraded" in a["message"] for a in alerts))

    def test_gray_overall_emits_data_quality_warning(self):
        ctx = {
            "health": {"appliance": {"health": {"overall": "gray"}, "backup": {"enabled": True}, "config": {}}},
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        cats = [a["category"] for a in alerts]
        self.assertIn("data_quality", cats)

    def test_zero_datacenters_emits_critical_infrastructure(self):
        ctx = {
            "health": {"appliance": {"health": {"overall": "green"}, "backup": {"enabled": True}, "config": {}}},
            "summary": {"datacenter_count": 0},
        }
        alerts = self.module.audit_health_alerts(ctx)
        self.assertTrue(any(a["category"] == "infrastructure" for a in alerts))
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in alerts))

    def test_ssh_enabled_emits_security_warning(self):
        ctx = {
            "health": {
                "appliance": {
                    "health": {"overall": "green"},
                    "backup": {"enabled": True},
                    "config": {"ssh_enabled": True},
                }
            },
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        self.assertTrue(any(a["category"] == "security" for a in alerts))

    def test_backup_disabled_emits_critical_data_protection(self):
        ctx = {
            "health": {
                "appliance": {
                    "health": {"overall": "green"},
                    "backup": {"enabled": False},
                    "config": {},
                }
            },
            "summary": {"datacenter_count": 1},
        }
        alerts = self.module.audit_health_alerts(ctx)
        self.assertTrue(any(a["category"] == "data_protection" for a in alerts))
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in alerts))

    def test_empty_ctx_returns_backup_and_gray_alerts(self):
        alerts = self.module.audit_health_alerts({})
        # gray overall + backup disabled at minimum
        self.assertTrue(len(alerts) >= 2)

    # -- audit_alarm_alerts ---------------------------------------------------

    def test_no_alarms_success_returns_empty(self):
        ctx = {
            "health": {
                "alarms": {
                    "status": "SUCCESS",
                    "list": [],
                    "metrics": {"total": 0, "critical_count": 0, "warning_count": 0},
                }
            }
        }
        alerts = self.module.audit_alarm_alerts(ctx)
        self.assertEqual(alerts, [])

    def test_critical_alarms_generate_critical_alert(self):
        ctx = {
            "health": {
                "alarms": {
                    "status": "SUCCESS",
                    "list": [
                        {"severity": "critical", "alarm_name": "Host Disconnected"},
                        {"severity": "warning", "alarm_name": "Low disk"},
                    ],
                    "metrics": {"total": 2, "critical_count": 1, "warning_count": 1},
                }
            }
        }
        alerts = self.module.audit_alarm_alerts(ctx)
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in alerts))

    def test_warning_alarms_only_generate_warning(self):
        ctx = {
            "health": {
                "alarms": {
                    "status": "SUCCESS",
                    "list": [{"severity": "warning", "alarm_name": "Low disk"}],
                    "metrics": {"total": 1, "critical_count": 0, "warning_count": 1},
                }
            }
        }
        alerts = self.module.audit_alarm_alerts(ctx)
        sevs = [a["severity"] for a in alerts]
        self.assertNotIn("CRITICAL", sevs)
        self.assertIn("WARNING", sevs)

    def test_non_success_status_emits_status_alert(self):
        ctx = {
            "health": {
                "alarms": {
                    "status": "SCRIPT_ERROR",
                    "list": [],
                    "metrics": {"total": 0, "critical_count": 0, "warning_count": 0},
                }
            }
        }
        alerts = self.module.audit_alarm_alerts(ctx)
        self.assertTrue(any("SCRIPT_ERROR" in a["message"] for a in alerts))

    def test_max_items_truncates_affected_items(self):
        alarm_list = [{"severity": "critical", "alarm_name": f"a{i}"} for i in range(10)]
        ctx = {
            "health": {
                "alarms": {
                    "status": "SUCCESS",
                    "list": alarm_list,
                    "metrics": {"total": 10, "critical_count": 10, "warning_count": 0},
                }
            }
        }
        alerts = self.module.audit_alarm_alerts(ctx, max_items=3)
        crit_alert = next(a for a in alerts if a["severity"] == "CRITICAL")
        self.assertLessEqual(len(crit_alert.get("affected_items", [])), 3)


class AuditClusterAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_compliant_clusters_no_alerts(self):
        clusters = [
            {
                "name": "prod",
                "compliance": {"ha_enabled": True, "drs_enabled": True},
                "utilization": {"cpu_pct": 50, "memory_pct": 60},
            }
        ]
        result = self.module.audit_cluster_configuration_alerts(clusters)
        self.assertEqual(result["cluster_alerts"], [])
        self.assertEqual(result["rollup_alerts"], [])

    def test_ha_disabled_emits_compliance_warning_and_rollup(self):
        clusters = [
            {
                "name": "dev",
                "compliance": {"ha_enabled": False, "drs_enabled": True},
                "utilization": {"cpu_pct": 10, "memory_pct": 10},
            }
        ]
        result = self.module.audit_cluster_configuration_alerts(clusters)
        self.assertTrue(any(a["category"] == "cluster_compliance" for a in result["cluster_alerts"]))
        self.assertEqual(len(result["rollup_alerts"]), 1)

    def test_cpu_saturation_emits_capacity_warning(self):
        clusters = [
            {
                "name": "hot",
                "compliance": {"ha_enabled": True, "drs_enabled": True},
                "utilization": {"cpu_pct": 95, "memory_pct": 50},
            }
        ]
        result = self.module.audit_cluster_configuration_alerts(clusters)
        self.assertTrue(any("CPU Saturation" in a["message"] for a in result["cluster_alerts"]))

    def test_mem_saturation_emits_capacity_warning(self):
        clusters = [
            {
                "name": "bloat",
                "compliance": {"ha_enabled": True, "drs_enabled": True},
                "utilization": {"cpu_pct": 50, "memory_pct": 95},
            }
        ]
        result = self.module.audit_cluster_configuration_alerts(clusters)
        self.assertTrue(any("Memory Saturation" in a["message"] for a in result["cluster_alerts"]))

    def test_empty_clusters_returns_empty(self):
        result = self.module.audit_cluster_configuration_alerts([])
        self.assertEqual(result["cluster_alerts"], [])
        self.assertEqual(result["rollup_alerts"], [])


class AuditStorageAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    # -- audit_storage_rollup_alerts ------------------------------------------

    def test_healthy_datastores_returns_empty(self):
        ds = [{"name": "ds1", "free_pct": 80, "accessible": True, "maintenance_mode": "normal"}]
        alerts = self.module.audit_storage_rollup_alerts(ds)
        self.assertEqual(alerts, [])

    def test_critical_low_space_emits_critical(self):
        ds = [{"name": "ds1", "free_pct": 5, "accessible": True, "maintenance_mode": "normal"}]
        alerts = self.module.audit_storage_rollup_alerts(ds, crit_pct=10, warn_pct=15)
        self.assertTrue(any(a["severity"] == "CRITICAL" and a["category"] == "storage_capacity" for a in alerts))

    def test_warning_low_space_emits_warning(self):
        ds = [{"name": "ds1", "free_pct": 12, "accessible": True, "maintenance_mode": "normal"}]
        alerts = self.module.audit_storage_rollup_alerts(ds, crit_pct=10, warn_pct=15)
        self.assertTrue(any(a["severity"] == "WARNING" and a["category"] == "storage_capacity" for a in alerts))

    def test_inaccessible_emits_critical_connectivity(self):
        ds = [{"name": "ds1", "free_pct": 80, "accessible": False, "maintenance_mode": "normal"}]
        alerts = self.module.audit_storage_rollup_alerts(ds)
        self.assertTrue(any(a["category"] == "storage_connectivity" for a in alerts))

    def test_maintenance_mode_emits_warning(self):
        ds = [{"name": "ds1", "free_pct": 80, "accessible": True, "maintenance_mode": "inMaintenance"}]
        alerts = self.module.audit_storage_rollup_alerts(ds)
        self.assertTrue(any(a["category"] == "storage_configuration" for a in alerts))

    # -- audit_storage_object_alerts ------------------------------------------

    def test_object_healthy_returns_empty(self):
        ds = [{"name": "ds1", "free_pct": 50, "accessible": True}]
        alerts = self.module.audit_storage_object_alerts(ds)
        self.assertEqual(alerts, [])

    def test_object_inaccessible_emits_critical(self):
        ds = [{"name": "bad_ds", "free_pct": 50, "accessible": False}]
        alerts = self.module.audit_storage_object_alerts(ds)
        self.assertTrue(any("INACCESSIBLE" in a["message"] for a in alerts))

    def test_object_critical_low_space(self):
        ds = [{"name": "full_ds", "free_pct": 5, "accessible": True}]
        alerts = self.module.audit_storage_object_alerts(ds, crit_pct=10, warn_pct=15)
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in alerts))

    def test_object_warning_low_space(self):
        ds = [{"name": "low_ds", "free_pct": 12, "accessible": True}]
        alerts = self.module.audit_storage_object_alerts(ds, crit_pct=10, warn_pct=15)
        self.assertTrue(any(a["severity"] == "WARNING" for a in alerts))


class AuditSnapshotAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_no_snapshots_returns_empty(self):
        ctx = {"inventory": {"snapshots": {"summary": {"aged_count": 0, "total_size_gb": 0, "oldest_days": 0}}}}
        alerts = self.module.audit_snapshot_alerts(ctx)
        self.assertEqual(alerts, [])

    def test_aged_snapshots_emit_warning(self):
        ctx = {
            "inventory": {
                "snapshots": {
                    "summary": {"aged_count": 3, "total_size_gb": 50, "oldest_days": 30}
                }
            }
        }
        alerts = self.module.audit_snapshot_alerts(ctx)
        self.assertTrue(any(a["category"] == "snapshots" for a in alerts))
        self.assertTrue(any("3 snapshot" in a["message"] for a in alerts))

    def test_large_snapshots_emit_warning(self):
        ctx = {
            "inventory": {
                "snapshots": {
                    "summary": {
                        "aged_count": 0,
                        "total_size_gb": 200,
                        "oldest_days": 0,
                        "large_snapshots": [{"vm": "big_vm", "size_gb": 150}],
                    }
                }
            }
        }
        alerts = self.module.audit_snapshot_alerts(ctx)
        self.assertTrue(any("oversized" in a["message"] for a in alerts))

    def test_empty_ctx_returns_empty(self):
        alerts = self.module.audit_snapshot_alerts({})
        self.assertEqual(alerts, [])


class AuditToolsAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_all_healthy_returns_empty(self):
        ctx = {
            "inventory": {
                "vms": {
                    "list": [
                        {"name": "vm1", "power_state": "poweredOn", "tools_status": "toolsOk"},
                        {"name": "vm2", "power_state": "poweredOn", "tools_status": "toolsOld"},
                    ]
                }
            }
        }
        alerts = self.module.audit_tools_alerts(ctx)
        self.assertEqual(alerts, [])

    def test_unhealthy_tools_emit_warning(self):
        ctx = {
            "inventory": {
                "vms": {
                    "list": [
                        {"name": "vm1", "power_state": "poweredOn", "tools_status": "toolsNotInstalled"},
                        {"name": "vm2", "power_state": "poweredOn", "tools_status": "toolsNotRunning"},
                    ]
                }
            }
        }
        alerts = self.module.audit_tools_alerts(ctx)
        self.assertEqual(len(alerts), 1)
        self.assertIn("2 powered-on VM", alerts[0]["message"])

    def test_powered_off_vms_are_skipped(self):
        ctx = {
            "inventory": {
                "vms": {
                    "list": [
                        {"name": "vm1", "power_state": "poweredOff", "tools_status": "toolsNotInstalled"},
                    ]
                }
            }
        }
        alerts = self.module.audit_tools_alerts(ctx)
        self.assertEqual(alerts, [])

    def test_none_tools_status_counts_as_unhealthy(self):
        ctx = {
            "inventory": {
                "vms": {
                    "list": [
                        {"name": "vm1", "power_state": "poweredOn"},
                    ]
                }
            }
        }
        alerts = self.module.audit_tools_alerts(ctx)
        self.assertEqual(len(alerts), 1)

    def test_max_items_limits_affected_items(self):
        vms = [{"name": f"vm{i}", "power_state": "poweredOn", "tools_status": "toolsNotInstalled"} for i in range(10)]
        ctx = {"inventory": {"vms": {"list": vms}}}
        alerts = self.module.audit_tools_alerts(ctx, max_items=3)
        self.assertLessEqual(len(alerts[0].get("affected_items", [])), 3)


class AuditResourceRollupTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_normal_utilization_returns_no_alerts(self):
        clusters = [
            {
                "utilization": {
                    "cpu_total_mhz": 10000,
                    "cpu_used_mhz": 5000,
                    "memory_total_mb": 32000,
                    "memory_used_mb": 16000,
                }
            }
        ]
        result = self.module.audit_resource_rollup(clusters)
        self.assertEqual(result["alerts"], [])
        self.assertEqual(result["utilization"]["cpu_pct"], 50.0)
        self.assertEqual(result["utilization"]["memory_pct"], 50.0)

    def test_high_cpu_emits_alert(self):
        clusters = [
            {
                "utilization": {
                    "cpu_total_mhz": 10000,
                    "cpu_used_mhz": 9500,
                    "memory_total_mb": 32000,
                    "memory_used_mb": 16000,
                }
            }
        ]
        result = self.module.audit_resource_rollup(clusters)
        self.assertTrue(any("CPU" in a["message"] for a in result["alerts"]))

    def test_high_mem_emits_alert(self):
        clusters = [
            {
                "utilization": {
                    "cpu_total_mhz": 10000,
                    "cpu_used_mhz": 5000,
                    "memory_total_mb": 32000,
                    "memory_used_mb": 30000,
                }
            }
        ]
        result = self.module.audit_resource_rollup(clusters)
        self.assertTrue(any("Memory Saturation" in a["message"] for a in result["alerts"]))

    def test_multiple_clusters_aggregated(self):
        _util = {"cpu_total_mhz": 5000, "cpu_used_mhz": 2000, "memory_total_mb": 16000, "memory_used_mb": 8000}
        clusters = [
            {"utilization": _util},
            {"utilization": _util},
        ]
        result = self.module.audit_resource_rollup(clusters)
        self.assertEqual(result["utilization"]["cpu_total_mhz"], 10000)
        self.assertEqual(result["utilization"]["cpu_used_mhz"], 4000)
        self.assertEqual(result["utilization"]["memory_total_mb"], 32000)
        self.assertEqual(result["utilization"]["memory_used_mb"], 16000)

    def test_empty_clusters_returns_zero_utilization(self):
        result = self.module.audit_resource_rollup([])
        self.assertEqual(result["utilization"]["cpu_pct"], 0.0)
        self.assertEqual(result["utilization"]["memory_pct"], 0.0)
        self.assertEqual(result["alerts"], [])


class AttachAuditUtilizationTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_attaches_utilization_to_vmware_vcenter_data(self):
        ctx = {"vmware_vcenter": {"data": {"existing": True}}}
        util = {"cpu_pct": 45.0, "memory_pct": 60.0}
        out = self.module.attach_audit_utilization(ctx, util)
        self.assertEqual(out["vmware_vcenter"]["data"]["utilization"], util)
        self.assertTrue(out["vmware_vcenter"]["data"]["existing"])

    def test_creates_nested_structure_from_empty(self):
        out = self.module.attach_audit_utilization({}, {"cpu_pct": 10.0})
        self.assertEqual(out["vmware_vcenter"]["data"]["utilization"]["cpu_pct"], 10.0)

    def test_deep_copies_input(self):
        ctx: dict[str, Any] = {"vmware_vcenter": {"data": {}}}
        out = self.module.attach_audit_utilization(ctx, {"cpu_pct": 10.0})
        self.assertIsNot(out, ctx)
        self.assertNotIn("utilization", ctx["vmware_vcenter"]["data"])


class BuildAuditExportPayloadTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_basic_payload_structure(self):
        out = self.module.build_audit_export_payload(
            vmware_alerts=[{"severity": "WARNING"}],
            vmware_ctx={"vmware_vcenter": {"data": {"some": "value"}}},
            audit_failed=True,
            health="CRITICAL",
            summary={"total": 1, "critical_count": 1, "warning_count": 0, "info_count": 0, "by_category": {}},
            timestamp="2025-01-01T00:00:00",
            thresholds={"cpu": 90},
        )
        self.assertEqual(out["audit_type"], "vmware_vcenter")
        self.assertTrue(out["audit_failed"])
        self.assertEqual(len(out["alerts"]), 1)
        self.assertEqual(out["vmware_vcenter"]["health"], "CRITICAL")
        self.assertEqual(out["vmware_vcenter"]["summary"]["total"], 1)
        self.assertEqual(out["check_metadata"]["engine"], "ansible-ncs-vmware")

    def test_enforces_summary_defaults(self):
        out = self.module.build_audit_export_payload(
            vmware_alerts=[], vmware_ctx={}, audit_failed=False,
            health=None, summary=None, timestamp="", thresholds=None,
        )
        s = out["vmware_vcenter"]["summary"]
        self.assertEqual(s["total"], 0)
        self.assertEqual(s["critical_count"], 0)
        self.assertIsInstance(s["by_category"], dict)

    def test_none_inputs_handled_safely(self):
        out = self.module.build_audit_export_payload(
            vmware_alerts=None, vmware_ctx=None, audit_failed=False,
            health=None, summary="not_a_dict", timestamp=None, thresholds=None,
        )
        self.assertEqual(out["alerts"], [])
        self.assertEqual(out["vmware_vcenter"]["health"], "UNKNOWN")
        self.assertIsInstance(out["vmware_vcenter"]["summary"]["by_category"], dict)


if __name__ == "__main__":
    unittest.main()
