"""Tests for normalization functions given missing or malformed input.

Real infrastructure regularly produces incomplete data: a collection task
times out leaving keys absent, a module returns null for a field it usually
populates, or data arrives in the wrong type. These tests assert that
normalize_linux, normalize_vmware, and normalize_windows never raise an
exception under such conditions and always return a structurally valid model.

Valid model invariants (asserted on every bad-input case):
  - model is not None
  - model.health is one of HEALTHY / WARNING / CRITICAL / UNKNOWN
  - model.alerts is a list (possibly empty)
  - model.metadata is present
"""

from __future__ import annotations

import unittest
from typing import Any

from ncs_reporter.normalization.linux import normalize_linux
from ncs_reporter.normalization.vmware import normalize_vmware
from ncs_reporter.normalization.windows import normalize_windows

VALID_HEALTH_VALUES = {"HEALTHY", "WARNING", "CRITICAL", "UNKNOWN"}


def _assert_valid(tc: unittest.TestCase, model: Any, label: str) -> None:
    tc.assertIsNotNone(model, f"{label}: model is None")
    tc.assertIn(
        model.health,
        VALID_HEALTH_VALUES,
        f"{label}: health={model.health!r} is not a valid value",
    )
    tc.assertIsInstance(model.alerts, list, f"{label}: alerts must be a list")
    tc.assertIsNotNone(model.metadata, f"{label}: metadata is None")


# ===========================================================================
# normalize_linux
# ===========================================================================


class TestNormalizeLinuxBadInput(unittest.TestCase):
    """normalize_linux must not raise on malformed or sparse raw bundles."""

    def _ok(self, bundle: dict[str, Any], label: str) -> Any:
        try:
            model = normalize_linux(bundle)
        except Exception as exc:
            self.fail(f"normalize_linux raised {type(exc).__name__} on {label!r}: {exc}")
        _assert_valid(self, model, label)
        return model

    def test_empty_bundle(self) -> None:
        self._ok({}, "empty bundle")

    def test_envelope_with_empty_data(self) -> None:
        self._ok({"metadata": {}, "data": {}}, "envelope with empty data")

    def test_raw_discovery_key_present_but_empty(self) -> None:
        self._ok({"raw_discovery": {}}, "raw_discovery is empty dict")

    def test_raw_discovery_is_envelope_with_empty_data(self) -> None:
        self._ok(
            {"raw_discovery": {"metadata": {"host": "h", "timestamp": ""}, "data": {}}},
            "raw_discovery envelope with empty data",
        )

    def test_ansible_facts_is_empty_dict(self) -> None:
        self._ok({"data": {"ansible_facts": {}}}, "empty ansible_facts")

    def test_mounts_is_empty_list(self) -> None:
        self._ok({"data": {"ansible_facts": {"mounts": []}}}, "empty mounts")

    def test_mounts_contains_none_entries(self) -> None:
        self._ok(
            {"data": {"ansible_facts": {"mounts": [None, None]}}},
            "mounts list with None entries",
        )

    def test_mounts_contains_non_dict_entries(self) -> None:
        self._ok(
            {"data": {"ansible_facts": {"mounts": ["string", 42, True]}}},
            "mounts list with non-dict entries",
        )

    def test_failed_services_key_absent(self) -> None:
        self._ok({"data": {}}, "failed_services key absent")

    def test_reboot_stat_absent(self) -> None:
        self._ok({"data": {}}, "reboot_stat absent")

    def test_memtotal_mb_absent(self) -> None:
        model = self._ok({"data": {"ansible_facts": {}}}, "memtotal_mb absent")
        self.assertEqual(model.ubuntu_ctx.system.memory["total_mb"], 0)

    def test_uptime_seconds_absent(self) -> None:
        model = self._ok({"data": {"ansible_facts": {}}}, "uptime_seconds absent")
        self.assertEqual(model.ubuntu_ctx.system.uptime_days, 0)

    def test_disk_with_zero_size_total(self) -> None:
        """size_total=0 must not cause division by zero."""
        bundle = {
            "data": {
                "ansible_facts": {
                    "mounts": [
                        {
                            "mount": "/",
                            "device": "/dev/sda1",
                            "fstype": "ext4",
                            "size_total": 0,
                            "size_available": 0,
                        }
                    ]
                }
            }
        }
        model = self._ok(bundle, "disk with size_total=0")
        disks = model.ubuntu_ctx.system.disks
        self.assertEqual(len(disks), 1)
        self.assertEqual(disks[0]["used_pct"], 0.0)

    def test_loop_device_filtered_from_disks(self) -> None:
        bundle = {
            "data": {
                "ansible_facts": {
                    "mounts": [
                        {
                            "mount": "/snap/core",
                            "device": "/dev/loop0",
                            "fstype": "squashfs",
                            "size_total": 1000000,
                            "size_available": 0,
                        }
                    ]
                }
            }
        }
        model = self._ok(bundle, "loop device in mounts")
        self.assertEqual(model.ubuntu_ctx.system.disks, [], "loop devices must be filtered out")

    def test_healthy_model_when_all_healthy(self) -> None:
        bundle: dict[str, Any] = {}
        model = self._ok(bundle, "all healthy")
        self.assertEqual(model.health, "HEALTHY")
        self.assertEqual(model.alerts, [])


# ===========================================================================
# normalize_vmware
# ===========================================================================


class TestNormalizeVmwareBadInput(unittest.TestCase):
    """normalize_vmware must not raise on malformed or sparse raw bundles."""

    def _ok(self, bundle: dict[str, Any], label: str) -> Any:
        try:
            model = normalize_vmware(bundle)
        except Exception as exc:
            self.fail(f"normalize_vmware raised {type(exc).__name__} on {label!r}: {exc}")
        _assert_valid(self, model, label)
        return model

    def test_empty_bundle(self) -> None:
        self._ok({}, "empty bundle")

    def test_envelope_with_empty_data(self) -> None:
        self._ok({"metadata": {}, "data": {}}, "envelope with empty data")

    def test_datacenters_info_absent(self) -> None:
        self._ok({"data": {}}, "datacenters_info absent")

    def test_clusters_info_absent(self) -> None:
        self._ok({"data": {}}, "clusters_info absent")

    def test_clusters_info_empty_dict(self) -> None:
        self._ok({"data": {"clusters_info": {}}}, "clusters_info empty dict")

    def test_clusters_results_is_empty_list(self) -> None:
        self._ok({"data": {"clusters_info": {"results": []}}}, "clusters results empty")

    def test_clusters_results_contains_non_dict(self) -> None:
        self._ok(
            {"data": {"clusters_info": {"results": [None, "bad", 42]}}},
            "clusters results with non-dict entries",
        )

    def test_datastores_info_absent(self) -> None:
        self._ok({"data": {}}, "datastores_info absent")

    def test_datastores_list_empty(self) -> None:
        self._ok({"data": {"datastores_info": {"datastores": []}}}, "empty datastores")

    def test_datastores_list_contains_non_dict(self) -> None:
        self._ok(
            {"data": {"datastores_info": {"datastores": [None, "bad"]}}},
            "non-dict datastore entries",
        )

    def test_appliance_health_info_absent(self) -> None:
        self._ok({"data": {}}, "appliance_health_info absent")

    def test_vms_info_absent(self) -> None:
        self._ok({"data": {}}, "vms_info absent")

    def test_snapshots_info_absent(self) -> None:
        self._ok({"data": {}}, "snapshots_info absent")

    def test_alarms_info_absent(self) -> None:
        self._ok({"data": {}}, "alarms_info absent")

    def test_empty_bundle_produces_critical_alert(self) -> None:
        """No datacenters detected → CRITICAL infrastructure alert."""
        model = self._ok({}, "empty bundle alert check")
        categories = [a.category for a in model.alerts]
        self.assertIn(
            "infrastructure",
            categories,
            "Empty bundle (0 datacenters) must produce an infrastructure alert",
        )

    def test_datastore_with_zero_capacity(self) -> None:
        """Datastore with capacity=0 must not cause division by zero."""
        bundle = {
            "data": {
                "datastores_info": {
                    "datastores": [
                        {"name": "ds1", "capacity": 0, "freeSpace": 0, "accessible": True}
                    ]
                }
            }
        }
        self._ok(bundle, "datastore with capacity=0")

    def test_inaccessible_datastore_produces_alert(self) -> None:
        bundle = {
            "data": {
                "datastores_info": {
                    "datastores": [
                        {"name": "ds1", "capacity": 1000, "freeSpace": 500, "accessible": False}
                    ]
                }
            }
        }
        model = self._ok(bundle, "inaccessible datastore")
        categories = [a.category for a in model.alerts]
        self.assertIn("storage_connectivity", categories)

    def test_cluster_with_zero_cpu_capacity(self) -> None:
        """cpuCapacityMHz=0 must not cause division by zero."""
        bundle = {
            "data": {
                "clusters_info": {
                    "results": [
                        {
                            "item": "DC1",
                            "clusters": {
                                "Cluster-A": {
                                    "resource_summary": {
                                        "cpuCapacityMHz": 0,
                                        "cpuUsedMHz": 0,
                                        "memCapacityMB": 0,
                                        "memUsedMB": 0,
                                    }
                                }
                            },
                        }
                    ]
                }
            }
        }
        self._ok(bundle, "cluster with zero CPU/memory capacity")


# ===========================================================================
# normalize_windows
# ===========================================================================


class TestNormalizeWindowsBadInput(unittest.TestCase):
    """normalize_windows must not raise on malformed or sparse raw bundles."""

    def _ok(self, bundle: dict[str, Any], label: str) -> Any:
        try:
            model = normalize_windows(bundle)
        except Exception as exc:
            self.fail(f"normalize_windows raised {type(exc).__name__} on {label!r}: {exc}")
        _assert_valid(self, model, label)
        return model

    def test_empty_bundle(self) -> None:
        self._ok({}, "empty bundle")

    def test_envelope_with_empty_data(self) -> None:
        self._ok({"metadata": {}, "data": {}}, "envelope with empty data")

    def test_ccm_service_key_absent(self) -> None:
        model = self._ok({"data": {}}, "ccm_service absent")
        cats = [a["category"] for a in model.windows_audit["alerts"]]
        self.assertIn("services", cats, "Absent CCMExec service must trigger a services alert")

    def test_ccm_service_state_stopped(self) -> None:
        bundle = {"data": {"ccm_service": {"state": "stopped"}}}
        model = self._ok(bundle, "ccm_service stopped")
        cats = [a["category"] for a in model.windows_audit["alerts"]]
        self.assertIn("services", cats)

    def test_ccm_service_state_running_no_services_alert(self) -> None:
        bundle = {"data": {"ccm_service": {"state": "running"}}}
        model = self._ok(bundle, "ccm_service running")
        cats = [a["category"] for a in model.windows_audit["alerts"]]
        self.assertNotIn("services", cats)

    def test_configmgr_apps_absent(self) -> None:
        self._ok({"data": {}}, "configmgr_apps absent")

    def test_installed_apps_absent(self) -> None:
        self._ok({"data": {}}, "installed_apps absent")

    def test_update_results_absent(self) -> None:
        self._ok({"data": {}}, "update_results absent")

    def test_update_results_is_empty_list(self) -> None:
        self._ok({"data": {"update_results": []}}, "update_results empty list")

    def test_failed_update_produces_patching_alert(self) -> None:
        bundle = {
            "data": {
                "ccm_service": {"state": "running"},
                "update_results": [{"name": "App1", "failed": True, "msg": "timeout"}],
            }
        }
        model = self._ok(bundle, "one failed update")
        cats = [a["category"] for a in model.windows_audit["alerts"]]
        self.assertIn("patching", cats)

    def test_empty_bundle_produces_warning_health(self) -> None:
        """No CCMExec → WARNING (not CRITICAL, not HEALTHY)."""
        model = self._ok({}, "empty bundle health check")
        self.assertIn(model.health, ("WARNING", "CRITICAL"))

    def test_healthy_when_service_running_no_failed_updates(self) -> None:
        bundle = {
            "data": {
                "ccm_service": {"state": "running"},
                "update_results": [],
            }
        }
        model = self._ok(bundle, "healthy windows host")
        self.assertEqual(model.health, "HEALTHY")


if __name__ == "__main__":
    unittest.main()
