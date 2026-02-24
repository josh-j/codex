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


class VmwareAuditFilterTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_attach_audit_results_updates_nested_vcenter_health_and_preserves_data(self):
        base: dict[str, Any] = {
            "alerts": [{"message": "old"}],
            "vcenter_health": {"data": {"utilization": {"cpu_pct": 50.0}}},
        }
        alerts = [{"severity": "WARNING", "message": "new"}]
        health = {"raw": "WARNING", "label": "Warning"}
        summary = {"total": 1, "critical": 0, "warning": 1}

        out = self.module.attach_audit_results(base, alerts, True, health, summary)

        self.assertIsNot(out, base)
        self.assertEqual(out["alerts"], alerts)
        self.assertEqual(out["vcenter_health"]["alerts"], alerts)
        self.assertEqual(out["vcenter_health"]["health"], health)
        self.assertEqual(out["vcenter_health"]["summary"], summary)
        self.assertTrue(out["vcenter_health"]["audit_failed"])
        self.assertEqual(out["vcenter_health"]["data"]["utilization"]["cpu_pct"], 50.0)
        self.assertEqual(base["alerts"][0]["message"], "old")

    def test_append_alerts_handles_list_none_and_single_item(self):
        self.assertEqual(
            self.module.append_alerts([{"m": 1}], [{"m": 2}, {"m": 3}]),
            [{"m": 1}, {"m": 2}, {"m": 3}],
        )
        self.assertEqual(self.module.append_alerts([{"m": 1}], None), [{"m": 1}])
        self.assertEqual(
            self.module.append_alerts([{"m": 1}], {"m": 2}),
            [{"m": 1}, {"m": 2}],
        )

    def test_compute_audit_rollups_returns_summary_and_health(self):
        alerts = [
            {"severity": "warning", "category": "capacity"},
            {"severity": "CRITICAL", "category": "capacity"},
            {"severity": "INFO", "category": "inventory"},
        ]

        out = self.module.compute_audit_rollups(alerts)

        self.assertEqual(out["health"], "CRITICAL")
        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["critical_count"], 1)
        self.assertEqual(out["summary"]["warning_count"], 1)
        self.assertEqual(out["summary"]["info_count"], 1)
        self.assertEqual(out["summary"]["by_category"]["capacity"], 2)
        self.assertEqual(out["summary"]["by_category"]["inventory"], 1)

    def test_build_owner_notification_context_buckets_by_owner(self):
        ctx = {
            "inventory": {
                "vms": {
                    "list": [
                        {"name": "vm1", "owner_email": "a@example.com", "power_state": "POWEREDOFF"},
                        {"name": "vm2", "owner_email": "a@example.com", "power_state": "POWEREDON"},
                        {"name": "vm3", "owner_email": "b@example.com", "power_state": "POWEREDOFF"},
                    ],
                    "never_backed_up": [{"name": "vm1"}, {"name": "vm3"}],
                    "without_backup_tags": [{"name": "vm2"}],
                    "with_overdue_backup": [{"name": "vm2"}, {"name": "vm3"}],
                },
                "snapshots": {
                    "aged": [{"vm_name": "vm2"}, {"vm_name": "vm3"}],
                },
            }
        }

        out = self.module.build_owner_notification_context(ctx, "a@example.com")

        self.assertEqual(out["my_names"], ["vm1", "vm2"])
        self.assertEqual(len(out["my_vms"]), 2)
        self.assertEqual([i["name"] for i in out["my_issues"]["no_backup"]], ["vm1"])
        self.assertEqual([i["name"] for i in out["my_issues"]["no_backup_tags"]], ["vm2"])
        self.assertEqual([i["name"] for i in out["my_issues"]["overdue_backup"]], ["vm2"])
        self.assertEqual([i["vm_name"] for i in out["my_issues"]["aged_snapshots"]], ["vm2"])
        self.assertEqual([i["name"] for i in out["my_issues"]["powered_off"]], ["vm1"])

    def test_normalize_esxi_stig_facts_maps_advanced_settings_to_config_list(self):
        raw_api = {
            "name": "esxi01",
            "uuid": "uuid-123",
            "advanced_settings": {
                "Net.BlockGuestBPDU": 1,
                "Config.HostAgent.log.level": "info",
            },
            "system": {"acceptance_level": "VMwareAccepted"},
        }
        identity = {"version": "7.0.3", "build": "12345"}
        services = {"TSM-SSH": {"running": True}}
        ssh = {"sshd_config": "PermitRootLogin no"}

        out = self.module.normalize_esxi_stig_facts(raw_api, identity, services, ssh)

        self.assertEqual(out["name"], "esxi01")
        self.assertEqual(out["identity"]["version"], "7.0.3")
        # Check dict to list conversion for templates
        self.assertIn({"key": "Net.BlockGuestBPDU", "value": "1"}, out["config"]["option_value"])
        self.assertIn(
            {"key": "Config.HostAgent.log.level", "value": "info"},
            out["config"]["option_value"],
        )
        self.assertEqual(out["services"]["TSM-SSH"]["running"], True)
        self.assertEqual(out["ssh"]["sshd_config"], "PermitRootLogin no")
        self.assertEqual(out["advanced_settings_map"]["Net.BlockGuestBPDU"], 1)

    def test_normalize_vm_stig_facts_merges_multiple_sources_per_vm(self):
        raw_vms = [
            {"name": "vm1", "uuid": "u1", "advanced_settings": {"key1": "val1"}},
            {"name": "vm2", "uuid": "u2", "logging_enabled": False},
        ]
        inv_map = {
            "vm1": {"guest_id": "rhel8", "tools_status": "toolsOk"},
            "vm2": {"guest_id": "win2019", "tools_status": "toolsOld"},
        }
        sec_map = {"vm1": {"encryption": "Encrypted", "vmotion_encryption": "required"}}

        out = self.module.normalize_vm_stig_facts(raw_vms, inv_map, sec_map)

        self.assertEqual(len(out), 2)

        # VM1 checks
        vm1 = next(v for v in out if v["name"] == "vm1")
        self.assertEqual(vm1["identity"]["guest_id"], "rhel8")
        self.assertEqual(vm1["security"]["encryption"], "Encrypted")
        self.assertEqual(vm1["security"]["vmotion_encryption"], "required")
        self.assertEqual(vm1["advanced_settings"]["key1"], "val1")
        self.assertEqual(vm1["tools_status"], "toolsOk")  # Alias check

        # VM2 checks
        vm2 = next(v for v in out if v["name"] == "vm2")
        self.assertEqual(vm2["identity"]["guest_id"], "win2019")
        self.assertEqual(vm2["security"]["encryption"], "None")  # Default
        self.assertEqual(vm2["security"]["logging_enabled"], False)  # From raw_vms
        self.assertEqual(vm2["tools_status"], "toolsOld")


if __name__ == "__main__":
    unittest.main()
