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
    / "discovery.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("vmware_discovery_filter", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class NormalizeComputeInventoryTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_single_cluster_with_hosts(self):
        results = [
            {
                "clusters": {
                    "prod-cluster": {
                        "resource_summary": {
                            "cpuCapacityMHz": 20000,
                            "cpuUsedMHz": 10000,
                            "memCapacityMB": 65536,
                            "memUsedMB": 32768,
                        },
                        "datacenter": "DC1",
                        "hosts": [{"name": "esxi01"}, {"name": "esxi02"}],
                        "ha_enabled": True,
                        "drs_enabled": True,
                        "vsan_enabled": False,
                    }
                }
            }
        ]
        out = self.module.normalize_compute_inventory(results)

        self.assertIn("prod-cluster", out["clusters_by_name"])
        cluster = out["clusters_by_name"]["prod-cluster"]
        self.assertEqual(cluster["utilization"]["cpu_pct"], 50.0)
        self.assertEqual(cluster["utilization"]["mem_pct"], 50.0)
        self.assertTrue(cluster["compliance"]["ha_enabled"])
        self.assertEqual(len(out["hosts_list"]), 2)
        self.assertEqual(out["hosts_list"][0]["cluster"], "prod-cluster")
        self.assertEqual(out["hosts_list"][0]["datacenter"], "DC1")

    def test_multiple_results_merged(self):
        results = [
            {"clusters": {"c1": {"resource_summary": {}, "datacenter": "DC1", "hosts": []}}},
            {"clusters": {"c2": {"resource_summary": {}, "datacenter": "DC2", "hosts": ["h1"]}}},
        ]
        out = self.module.normalize_compute_inventory(results)
        self.assertEqual(len(out["clusters_list"]), 2)
        # String host should be converted to dict with name
        self.assertEqual(out["hosts_list"][0]["name"], "h1")

    def test_empty_input(self):
        out = self.module.normalize_compute_inventory([])
        self.assertEqual(out["clusters_list"], [])
        self.assertEqual(out["hosts_list"], [])

    def test_non_dict_items_skipped(self):
        out = self.module.normalize_compute_inventory([None, "bad", 42])
        self.assertEqual(out["clusters_list"], [])


class NormalizeDatastoresTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_basic_normalization(self):
        raw = [
            {
                "name": "ds1",
                "type": "VMFS",
                "capacity": 1073741824,  # 1 GB
                "freeSpace": 536870912,  # 0.5 GB
                "accessible": True,
                "maintenanceMode": "normal",
            }
        ]
        out = self.module.normalize_datastores(raw)
        self.assertEqual(len(out["list"]), 1)
        ds = out["list"][0]
        self.assertEqual(ds["name"], "ds1")
        self.assertAlmostEqual(ds["capacity_gb"], 1.0, places=1)
        self.assertAlmostEqual(ds["free_gb"], 0.5, places=1)
        self.assertAlmostEqual(ds["free_pct"], 50.0, places=1)
        self.assertTrue(ds["accessible"])

    def test_inaccessible_datastore(self):
        raw = [{"name": "ds_bad", "accessible": False, "capacity": 1000, "freeSpace": 500}]
        out = self.module.normalize_datastores(raw)
        ds = out["list"][0]
        self.assertFalse(ds["accessible"])
        self.assertEqual(ds["free_pct"], 0.0)
        self.assertEqual(out["summary"]["inaccessible_count"], 1)

    def test_low_space_counted(self):
        raw = [
            {"name": "full", "accessible": True, "capacity": 1073741824, "freeSpace": 53687091}  # ~5%
        ]
        out = self.module.normalize_datastores(raw, low_space_pct=10)
        self.assertEqual(out["summary"]["low_space_count"], 1)

    def test_empty_input(self):
        out = self.module.normalize_datastores([])
        self.assertEqual(out["list"], [])
        self.assertEqual(out["summary"]["total_count"], 0)


class AnalyzeWorkloadVmsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_basic_vm_normalization(self):
        vms = [
            {
                "guest_name": "web01",
                "uuid": "u1",
                "power_state": "poweredOn",
                "cluster": "prod",
                "tools_status": "toolsOk",
                "tools_version": "12345",
                "guest_id": "ubuntu64Guest",
                "memory_mb": 4096,
                "num_cpu": 2,
                "attributes": {"Owner Email": "admin@test.com"},
            }
        ]
        out = self.module.analyze_workload_vms(vms, 1700000000)
        self.assertEqual(len(out["list"]), 1)
        vm = out["list"][0]
        self.assertEqual(vm["name"], "web01")
        self.assertEqual(vm["owner_email"], "admin@test.com")
        self.assertEqual(vm["power_state"], "POWEREDON")
        self.assertFalse(vm["is_system_vm"])
        self.assertEqual(vm["last_backup"], "NEVER")
        self.assertTrue(vm["backup_overdue"])

    def test_system_vm_detected(self):
        vms = [{"guest_name": "vCLS-abc123", "attributes": {}}]
        out = self.module.analyze_workload_vms(vms, 1700000000)
        self.assertTrue(out["list"][0]["is_system_vm"])

    def test_template_is_system_vm(self):
        vms = [{"guest_name": "template-vm", "is_template": True, "attributes": {}}]
        out = self.module.analyze_workload_vms(vms, 1700000000)
        self.assertTrue(out["list"][0]["is_system_vm"])

    def test_backup_timestamp_parsing(self):
        vms = [
            {
                "guest_name": "db01",
                "attributes": {
                    "Last Dell PowerProtect Backup": "EndTime=2025-01-01T00:00:00Z, Status=OK"
                },
            }
        ]
        out = self.module.analyze_workload_vms(vms, 1735689600)  # 2025-01-01 epoch
        vm = out["list"][0]
        self.assertTrue(vm["has_backup"])
        self.assertEqual(vm["days_since"], 0)
        self.assertFalse(vm["backup_overdue"])

    def test_summary_counts(self):
        vms = [
            {"guest_name": "vm1", "power_state": "poweredOff", "attributes": {"Owner Email": "a@x.com"}},
            {"guest_name": "vm2", "power_state": "poweredOn", "attributes": {}},
        ]
        out = self.module.analyze_workload_vms(vms, 1700000000)
        self.assertEqual(out["summary"]["total_vms"], 2)
        self.assertEqual(out["summary"]["unprotected"], 2)
        self.assertEqual(out["summary"]["missing_owners"], 1)  # vm2 has no owner (not system)
        self.assertEqual(out["metrics"]["powered_off_count"], 1)
        self.assertAlmostEqual(out["metrics"]["powered_off_pct"], 50.0, places=1)

    def test_empty_input(self):
        out = self.module.analyze_workload_vms([], 0)
        self.assertEqual(out["list"], [])
        self.assertEqual(out["summary"]["total_vms"], 0)


class ParseEsxiSshFactsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_parses_all_sections(self):
        raw = (
            "===SSHD===\n"
            "PermitRootLogin no\n"
            "PasswordAuthentication yes\n"
            "===ISSUE===\n"
            "Authorized users only\n"
            "===FIREWALL===\n"
            "sshServer  true\n"
        )
        out = self.module.parse_esxi_ssh_facts(raw)
        self.assertIn("PermitRootLogin no", out["sshd_config"])
        self.assertEqual(out["banner_content"], "Authorized users only")
        self.assertIn("sshServer", out["firewall_raw"])

    def test_empty_input(self):
        out = self.module.parse_esxi_ssh_facts("")
        self.assertEqual(out["sshd_config"], "")
        self.assertEqual(out["banner_content"], "")
        self.assertEqual(out["firewall_raw"], "")


class NormalizeAlarmResultTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_successful_script_result(self):
        parsed = {
            "script_valid": True,
            "payload": {
                "success": True,
                "alarms": [
                    {"alarm_name": "Host disconnected", "entity": "esxi01", "severity": "critical", "status": "red"},
                    {"alarm_name": "Low disk", "entity": "ds1", "severity": "warning", "status": "yellow"},
                ],
            },
        }
        out = self.module.normalize_alarm_result(parsed, "site1", collected_at="2025-01-01")
        self.assertEqual(out["status"], "CRITICAL")
        self.assertEqual(len(out["list"]), 2)
        self.assertEqual(out["metrics"]["critical_count"], 1)
        self.assertEqual(out["metrics"]["warning_count"], 1)
        self.assertEqual(out["list"][0]["site"], "site1")

    def test_failed_script_result(self):
        parsed = {"script_valid": False, "rc": 1, "payload": None, "stderr": "timeout"}
        out = self.module.normalize_alarm_result(parsed, "site1")
        self.assertEqual(out["status"], "SCRIPT_ERROR")

    def test_native_module_result(self):
        parsed = {"failed": False, "alarms": [{"alarm_name": "test", "severity": "info"}]}
        out = self.module.normalize_alarm_result(parsed, "site1")
        self.assertEqual(out["status"], "SUCCESS")
        self.assertEqual(len(out["list"]), 1)


class SnapshotHelpersTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_snapshot_owner_map(self):
        vms = {"list": [{"name": "vm1", "owner_email": "a@x.com"}, {"name": "vm2", "owner_email": "b@x.com"}]}
        out = self.module.snapshot_owner_map(vms)
        self.assertEqual(out["vm1"], "a@x.com")
        self.assertEqual(out["vm2"], "b@x.com")

    def test_snapshot_no_datacenter_result(self):
        out = self.module.snapshot_no_datacenter_result(collected_at="2025-01-01")
        self.assertEqual(out["status"], "NO_DATACENTER")
        self.assertEqual(out["summary"]["total_count"], 0)

    def test_normalize_snapshots_result_success(self):
        raw = {"failed": False}
        all_snaps = [{"vm_name": "vm1", "size_gb": 10, "days_old": 14}]
        aged = [{"vm_name": "vm1", "size_gb": 10, "days_old": 14}]
        out = self.module.normalize_snapshots_result(raw, all_snaps, aged)
        self.assertEqual(out["status"], "SUCCESS")
        self.assertEqual(out["summary"]["total_count"], 1)
        self.assertEqual(out["summary"]["aged_count"], 1)
        self.assertEqual(out["summary"]["oldest_days"], 14)

    def test_normalize_snapshots_result_large_snapshots(self):
        raw = {"failed": False}
        aged = [{"vm_name": "big", "size_gb": 200, "days_old": 10}]
        out = self.module.normalize_snapshots_result(raw, aged, aged, size_warning_gb=100)
        self.assertEqual(len(out["summary"]["large_snapshots"]), 1)


class SeedAndCtxHelpersTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_seed_vmware_ctx(self):
        out = self.module.seed_vmware_ctx({}, "vc01.lab", "vcenter.local")
        self.assertEqual(out["audit_type"], "vcenter_health")
        self.assertFalse(out["checks_failed"])
        self.assertEqual(out["system"]["name"], "vc01.lab")
        self.assertEqual(out["system"]["hostname"], "vcenter.local")
        self.assertEqual(out["system"]["status"], "INITIALIZING")

    def test_append_vmware_ctx_alert(self):
        ctx: dict[str, Any] = {"alerts": [{"existing": True}]}
        out = self.module.append_vmware_ctx_alert(ctx, {"severity": "WARNING", "message": "test"})
        self.assertEqual(len(out["alerts"]), 2)

    def test_append_vmware_ctx_alert_ignores_empty(self):
        ctx: dict[str, Any] = {"alerts": []}
        out = self.module.append_vmware_ctx_alert(ctx, {})
        self.assertEqual(len(out["alerts"]), 0)

    def test_mark_vmware_ctx_unreachable(self):
        ctx: dict[str, Any] = {"system": {"status": "INITIALIZING"}}
        out = self.module.mark_vmware_ctx_unreachable(ctx)
        self.assertTrue(out["checks_failed"])
        self.assertEqual(out["system"]["status"], "UNREACHABLE")


class BuildDiscoveryCtxTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_successful_discovery_sets_complete_status(self):
        disc = {
            "datacenters": {"list": ["DC1"], "status": "SUCCESS"},
        }
        out = self.module.build_discovery_ctx({}, disc, collected_at="2025-01-01")
        self.assertEqual(out["system"]["status"], "DISCOVERY_COMPLETE")
        self.assertIn("inventory", out)
        self.assertIn("health", out)

    def test_dc_query_error_sets_error_status_and_alert(self):
        disc = {
            "datacenters": {"list": [], "status": "QUERY_ERROR", "error": "timeout"},
        }
        out = self.module.build_discovery_ctx({}, disc)
        self.assertEqual(out["system"]["status"], "DISCOVERY_ERROR_DATACENTERS")
        self.assertTrue(any(a["severity"] == "CRITICAL" for a in out["alerts"]))

    def test_zero_datacenters_sets_not_found_status(self):
        disc = {"datacenters": {"list": [], "status": "SUCCESS"}}
        out = self.module.build_discovery_ctx({}, disc)
        self.assertEqual(out["system"]["status"], "NO_DATACENTERS_FOUND")

    def test_defaults_populated_for_missing_sections(self):
        out = self.module.build_discovery_ctx({}, {})
        inv = out["inventory"]
        self.assertIn("clusters", inv)
        self.assertIn("hosts", inv)
        self.assertIn("datastores", inv)
        self.assertIn("vms", inv)
        self.assertIn("snapshots", inv)
        self.assertIn("appliance", out["health"])
        self.assertIn("alarms", out["health"])


class NormalizeApplianceTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_normalize_appliance_backup_active_schedule(self):
        raw = {
            "schedules": [
                {
                    "enabled": True,
                    "location": "sftp://backup.local/path",
                    "schedule": {"days_of_week": ["MONDAY", "WEDNESDAY", "FRIDAY"]},
                }
            ]
        }
        out = self.module.normalize_appliance_backup_result(raw)
        self.assertTrue(out["enabled"])
        self.assertTrue(out["configured"])
        self.assertEqual(out["protocol"], "SFTP")
        self.assertEqual(out["recurrence"], "MONDAY, WEDNESDAY, FRIDAY")

    def test_normalize_appliance_backup_daily(self):
        raw = {
            "schedules": [
                {
                    "enabled": True,
                    "location": "nfs://store",
                    "schedule": {"days_of_week": ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]},
                }
            ]
        }
        out = self.module.normalize_appliance_backup_result(raw)
        self.assertEqual(out["recurrence"], "Daily")

    def test_normalize_appliance_backup_no_schedules(self):
        out = self.module.normalize_appliance_backup_result({})
        self.assertFalse(out["configured"])
        self.assertFalse(out["enabled"])

    def test_normalize_appliance_health(self):
        raw = {
            "appliance": {
                "summary": {
                    "health": {"overall": "green", "cpu": "green", "memory": "green"},
                    "product": "vCenter Server",
                    "version": "8.0.2",
                    "build_number": "22385739",
                    "uptime": 172800,
                },
                "access": {"ssh": True, "shell": {"enabled": False}},
                "time": {"time_sync": {"servers": ["ntp.local"], "mode": "NTP"}, "time_zone": "UTC"},
            }
        }
        out = self.module.normalize_appliance_health_result(raw)
        self.assertEqual(out["info"]["version"], "8.0.2")
        self.assertEqual(out["info"]["uptime_days"], 2)
        self.assertEqual(out["health"]["overall"], "green")
        self.assertTrue(out["config"]["ssh_enabled"])
        self.assertEqual(out["config"]["ntp_mode"], "NTP")


if __name__ == "__main__":
    unittest.main()
