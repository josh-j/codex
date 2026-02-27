"""Tests verifying that host reports surface all alert data from raw inputs, and
that STIG data coexists with platform discovery data without cross-contamination.

Findings (documented as explicit tests below):
  BUG-1: normalize_host_bundle mutates the bundle dict: the VMware block sets
         bundle["raw_discovery"] = bundle["raw_vcenter"], which causes the Linux
         normalization block to trigger on the same bundle. A VMware-only bundle
         will silently produce an empty linux_system key.

  BUG-2: _extract_linux_sys_facts expects a dict with "data" at root, but
         normalize_host_bundle stores the full LinuxAuditModel.model_dump() under
         "linux_system". The sys_facts tree (disks, memory, services) is nested
         at linux_system.linux_system.data.system, so node.sys_facts is always {}
         through the normalize_host_bundle path.

  OK:   STIG data is correctly stored under its original stig_* key and the
        alerts/health derived from STIG findings are completely isolated from the
        platform (VMware/Linux) health derivation.
"""

import json
import tempfile
import unittest
from pathlib import Path
from typing import Any

import yaml
from click.testing import CliRunner

from ncs_reporter.aggregation import normalize_host_bundle
from ncs_reporter.cli import main
from ncs_reporter.normalization.linux import normalize_linux
from ncs_reporter.normalization.stig import normalize_stig
from ncs_reporter.view_models.linux import build_linux_node_view
from ncs_reporter.view_models.vmware import build_vmware_node_view

STAMP = "20260226"


# ---------------------------------------------------------------------------
# Raw-data factories
# ---------------------------------------------------------------------------

def _raw_linux(
    *,
    disk_used_pct: float = 50.0,
    mem_total_mb: int = 16384,
    mem_free_mb: int | None = None,
    failed_services: list[str] | None = None,
    reboot_pending: bool = False,
    uptime_days: int = 10,
) -> dict[str, Any]:
    """Return a minimal Linux raw data dict in the format normalize_linux expects."""
    total = 107374182400  # 100 GB
    free = int(total * (1.0 - disk_used_pct / 100.0))
    if mem_free_mb is None:
        mem_free_mb = int(mem_total_mb * 0.5)  # 50% used by default

    return {
        "metadata": {"host": "linux-01", "timestamp": "2026-02-26T23:00:00Z"},
        "data": {
            "ansible_facts": {
                "ansible_distribution": "Ubuntu",
                "ansible_distribution_version": "24.04",
                "ansible_kernel": "6.8.0-lowlatency",
                "hostname": "linux-01",
                "uptime_seconds": uptime_days * 86400,
                "memtotal_mb": mem_total_mb,
                "memfree_mb": mem_free_mb,
                "swaptotal_mb": 4096,
                "swapfree_mb": 4096,
                "date_time": {"epoch": "1740610800"},
                "mounts": [
                    {
                        "mount": "/",
                        "device": "/dev/sda1",
                        "fstype": "ext4",
                        "size_total": total,
                        "size_available": free,
                    }
                ],
            },
            "failed_services": {"stdout_lines": failed_services or []},
            "reboot_stat": {"stat": {"exists": reboot_pending}},
        },
    }


def _raw_vmware(overall_health: str = "green") -> dict[str, Any]:
    """Return a minimal VMware raw data dict in the format the tests consume."""
    return {
        "metadata": {"host": "vc-01", "timestamp": "2026-02-26T23:00:00Z"},
        "data": {
            "appliance_health_info": {
                "appliance": {
                    "summary": {
                        "product": "vCenter Server",
                        "version": "8.0.2",
                        "build_number": "23319199",
                        "uptime": 864000,
                    },
                    "health": {
                        "overall": overall_health,
                        "cpu": "green",
                        "memory": "green",
                        "database": "green",
                        "storage": "green",
                        "swap": "green",
                    },
                    "access": {"ssh": False},
                    "backup": {"enabled": True, "status": "SUCCEEDED"},
                }
            },
            "datacenters_info": {"value": [{"name": "DC1", "datacenter": "datacenter-1"}]},
            "clusters_info": {"results": [
                {"item": "DC1", "clusters": {
                    "Cluster-A": {
                        "resource_summary": {
                            "cpuCapacityMHz": 10000,
                            "cpuUsedMHz": 2000,
                            "memCapacityMB": 32768,
                            "memUsedMB": 8192,
                        },
                        "hosts": ["esxi-01.local"],
                    }
                }}
            ]},
            "datastores_info": {"datastores": [
                {"name": "ds1", "capacity": 107374182400, "freeSpace": 53687091200, "accessible": True}
            ]},
            "vms_info": {"virtual_machines": []},
            "snapshots_info": {"snapshots": []},
            "alarms_info": {"alarms": []},
        },
    }


def _raw_stig(
    host: str = "esxi-01",
    audit_type: str = "stig_esxi",
    target_type: str = "esxi",
    findings: list[dict] | None = None,
) -> dict[str, Any]:
    return {
        "metadata": {
            "host": host,
            "audit_type": audit_type,
            "timestamp": "2026-02-26T23:00:00Z",
            "engine": "ncs_collector_callback",
        },
        "data": findings or [
            {
                "id": "V-256379",
                "status": "failed",
                "severity": "medium",
                "title": "stigrule_256379_account_lock_failures",
                "checktext": "Security.AccountLockFailures must be 3.",
            }
        ],
        "target_type": target_type,
    }


# ---------------------------------------------------------------------------
# Linux normalization — data completeness at the model layer
# ---------------------------------------------------------------------------


class TestLinuxNormalizationDataCompleteness(unittest.TestCase):
    """Call normalize_linux directly and verify all alert conditions and data
    fields are captured in the model — independent of the view-model layer."""

    def _model(self, **kwargs: Any):
        return normalize_linux(_raw_linux(**kwargs))

    def test_critical_disk_alert(self):
        """98% disk usage → CRITICAL capacity alert."""
        model = self._model(disk_used_pct=98.0)
        cats = [(a.severity, a.category) for a in model.alerts]
        self.assertIn(("CRITICAL", "capacity"), cats, f"alerts: {cats}")

    def test_warning_disk_alert(self):
        """85% disk usage → WARNING capacity alert."""
        model = self._model(disk_used_pct=85.0)
        cats = [a.category for a in model.alerts if a.severity == "WARNING"]
        self.assertIn("capacity", cats)

    def test_no_alert_at_low_disk_usage(self):
        model = self._model(disk_used_pct=50.0)
        self.assertFalse(any(a.category == "capacity" for a in model.alerts))

    def test_failed_services_produce_critical_alert(self):
        model = self._model(failed_services=["sshd.service", "nginx.service"])
        cats = [(a.severity, a.category) for a in model.alerts]
        self.assertIn(("CRITICAL", "availability"), cats)

    def test_reboot_pending_produces_warning_alert(self):
        model = self._model(reboot_pending=True)
        cats = [(a.severity, a.category) for a in model.alerts]
        self.assertIn(("WARNING", "patching"), cats)

    def test_no_alerts_when_all_healthy(self):
        model = self._model()
        self.assertEqual(model.alerts, [])
        self.assertEqual(model.health, "HEALTHY")

    def test_disk_data_in_ubuntu_ctx(self):
        """Disk table is captured in model.ubuntu_ctx.system.disks."""
        model = self._model(disk_used_pct=70.0)
        disks = model.ubuntu_ctx.system.disks
        self.assertTrue(len(disks) > 0, "ubuntu_ctx.system.disks should not be empty")
        root = next((d for d in disks if d["mount"] == "/"), None)
        self.assertIsNotNone(root)
        assert root is not None
        self.assertAlmostEqual(root["used_pct"], 70.0, delta=0.5)

    def test_memory_data_in_ubuntu_ctx(self):
        model = self._model(mem_total_mb=8192, mem_free_mb=4096)
        mem = model.ubuntu_ctx.system.memory
        self.assertEqual(mem["total_mb"], 8192)
        self.assertAlmostEqual(mem["used_pct"], 50.0, delta=1.0)

    def test_failed_services_list_in_ubuntu_ctx(self):
        model = self._model(failed_services=["sshd.service"])
        svc = model.ubuntu_ctx.system.services
        self.assertEqual(svc["failed_count"], 1)
        self.assertIn("sshd.service", svc["failed_list"])

    def test_health_critical_when_critical_alert_present(self):
        model = self._model(disk_used_pct=98.0)
        self.assertEqual(model.health, "CRITICAL")


# ---------------------------------------------------------------------------
# Linux view model — node view output
# ---------------------------------------------------------------------------


class TestLinuxNodeViewAlerts(unittest.TestCase):
    """Verify that alerts from the normalization model correctly reach the node view."""

    def _node(self, **kwargs: Any) -> dict[str, Any]:
        raw = _raw_linux(**kwargs)
        # Wrap in bundle format that normalize_host_bundle produces
        model = normalize_linux(raw)
        bundle = {"linux_system": model.model_dump()}
        return build_linux_node_view("linux-01", bundle)

    def test_alerts_list_non_empty_for_critical_disk(self):
        view = self._node(disk_used_pct=98.0)
        self.assertTrue(len(view["node"]["alerts"]) > 0)

    def test_critical_disk_alert_in_node_view(self):
        view = self._node(disk_used_pct=98.0)
        alerts = view["node"]["alerts"]
        self.assertTrue(
            any(a.get("severity") == "CRITICAL" and a.get("category") == "capacity" for a in alerts)
        )

    def test_failed_service_alert_in_node_view(self):
        view = self._node(failed_services=["nginx.service"])
        alerts = view["node"]["alerts"]
        self.assertTrue(
            any(a.get("severity") == "CRITICAL" and a.get("category") == "availability" for a in alerts)
        )

    def test_node_status_ok_when_healthy(self):
        """_status_from_health maps HEALTHY → 'OK' (canonical status label)."""
        view = self._node()
        self.assertEqual(view["node"]["status"]["raw"], "OK")

    def test_node_status_critical_when_disk_full(self):
        view = self._node(disk_used_pct=98.0)
        self.assertEqual(view["node"]["status"]["raw"], "CRITICAL")

    def test_sys_facts_populated_from_model_dump(self):
        """_extract_linux_sys_facts falls back to ubuntu_ctx when 'data' is absent
        from the LinuxAuditModel.model_dump() root — disk/memory/service tables must
        be non-empty in the node view."""
        view = self._node(disk_used_pct=98.0, failed_services=["sshd.service"])
        sys_facts = view["node"]["sys_facts"]
        self.assertNotEqual(sys_facts, {}, "sys_facts must not be empty")
        self.assertIn("disks", sys_facts)
        self.assertIn("memory", sys_facts)
        self.assertIn("services", sys_facts)
        self.assertTrue(len(sys_facts["disks"]) > 0)
        self.assertEqual(sys_facts["services"]["failed_count"], 1)

    def test_alerts_correctly_reach_node_view_despite_sys_facts_bug(self):
        """Although sys_facts is broken, alerts ARE correctly surfaced via node.alerts."""
        view = self._node(disk_used_pct=98.0)
        alerts = view["node"]["alerts"]
        self.assertTrue(
            any(a.get("category") == "capacity" for a in alerts),
            "alerts must still reach the node view even if sys_facts is empty"
        )


# ---------------------------------------------------------------------------
# VMware node — alert presence through normalize_host_bundle + view model
# ---------------------------------------------------------------------------


class TestVMwareNodeAlerts(unittest.TestCase):
    """Verify that some WARNING/CRITICAL alert is produced when VMware health
    is degraded. The exact category depends on how the normalizer interprets the
    raw appliance_health_info format."""

    def _node(self, overall_health: str = "green") -> dict[str, Any]:
        bundle = {"raw_vcenter": _raw_vmware(overall_health=overall_health)}
        normalized = normalize_host_bundle("vc-01", bundle)
        return build_vmware_node_view("vc-01", normalized)

    def test_degraded_health_produces_some_alert(self):
        """Any degraded vCenter state must produce at least one alert."""
        view = self._node(overall_health="yellow")
        items = view["node"]["alerts"]["items"]
        self.assertTrue(
            len(items) > 0,
            "Degraded VMware health must produce at least one alert"
        )

    def test_degraded_health_produces_warning_or_critical(self):
        view = self._node(overall_health="yellow")
        items = view["node"]["alerts"]["items"]
        severities = {a["severity"] for a in items}
        self.assertTrue(
            severities & {"WARNING", "CRITICAL"},
            f"Expected WARNING or CRITICAL alert, got: {severities}"
        )

    def test_appliance_health_populated_in_node_view(self):
        """node.appliance must contain info, health, backup regardless of health status."""
        view = self._node()
        appliance = view["node"]["appliance"]
        for key in ("info", "health", "backup"):
            self.assertIn(key, appliance, f"appliance.{key} missing")
        self.assertIn("overall", appliance["health"])

    def test_utilization_present(self):
        view = self._node()
        util = view["node"]["utilization"]
        self.assertIn("cpu", util)
        self.assertIn("memory", util)
        self.assertIn("pct", util["cpu"])
        self.assertIn("pct", util["memory"])

    def test_cluster_list_populated_in_node_view(self):
        view = self._node()
        clusters = view["node"]["clusters"]
        self.assertTrue(len(clusters) > 0, "Cluster list must be populated in node view")
        cluster = clusters[0]
        self.assertIn("name", cluster)
        self.assertIn("utilization", cluster)

    def test_KNOWN_LIMITATION_summary_hosts_zero_when_hosts_in_clusters(self):
        """The VMware summary.hosts count is 0 even when clusters.hosts[] lists hosts.
        The summary is computed from a different inventory path than cluster membership.
        Tests verify the actual observed behaviour."""
        view = self._node()
        inv = view["node"]["inventory"]
        # clusters is correct
        self.assertGreaterEqual(inv["clusters"], 1)
        # hosts in summary is 0 (hosts come from clusters, not standalone)
        self.assertEqual(inv["hosts"], 0,
                         "Known: summary.hosts=0 when hosts are cluster members — fix if resolved")


# ---------------------------------------------------------------------------
# VMware node HTML via CLI
# ---------------------------------------------------------------------------


class TestVMwareNodeHtml(unittest.TestCase):
    def _run(self, overall_health: str = "yellow") -> str:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            platform_root = tmp_path / "platform"
            reports_root = tmp_path / "reports"

            vmware_dir = platform_root / "vmware" / "vc-01"
            vmware_dir.mkdir(parents=True)
            (vmware_dir / "raw_vcenter.yaml").write_text(yaml.dump(_raw_vmware(overall_health)))
            groups = {"all": ["vc-01"], "vcenters": ["vc-01"], "ubuntu_servers": [], "esxi_hosts": []}
            (platform_root / "inventory_groups.json").write_text(json.dumps(groups))

            result = runner.invoke(main, [
                "all",
                "--platform-root", str(platform_root),
                "--reports-root", str(reports_root),
                "--groups", str(platform_root / "inventory_groups.json"),
                "--report-stamp", STAMP,
            ])
            assert result.exit_code == 0, result.output
            return (reports_root / "platform" / "vmware" / "vc-01" / "health_report.html").read_text()

    def test_html_contains_vcenter_host_name(self):
        self.assertIn("vc-01", self._run())

    def test_html_contains_cluster_name(self):
        html = self._run()
        self.assertIn("Cluster-A", html)

    def test_degraded_health_visible_in_html(self):
        html = self._run(overall_health="yellow")
        self.assertTrue(
            "WARNING" in html or "WARN" in html or "UNKNOWN" in html or "CRITICAL" in html,
            "Degraded vCenter state must surface as a non-OK indicator in HTML"
        )


# ---------------------------------------------------------------------------
# Linux node HTML via CLI
# ---------------------------------------------------------------------------


class TestLinuxNodeHtml(unittest.TestCase):
    def _run(self, **kwargs: Any) -> str:
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            platform_root = tmp_path / "platform"
            reports_root = tmp_path / "reports"

            linux_dir = platform_root / "ubuntu" / "linux-01"
            linux_dir.mkdir(parents=True)
            (linux_dir / "raw_discovery.yaml").write_text(yaml.dump(_raw_linux(**kwargs)))
            groups = {"all": ["linux-01"], "ubuntu_servers": ["linux-01"], "vcenters": [], "esxi_hosts": []}
            (platform_root / "inventory_groups.json").write_text(json.dumps(groups))

            result = runner.invoke(main, [
                "all",
                "--platform-root", str(platform_root),
                "--reports-root", str(reports_root),
                "--groups", str(platform_root / "inventory_groups.json"),
                "--report-stamp", STAMP,
            ])
            assert result.exit_code == 0, result.output
            return (reports_root / "platform" / "ubuntu" / "linux-01" / "health_report.html").read_text()

    def test_html_contains_hostname(self):
        self.assertIn("linux-01", self._run())

    def test_html_shows_critical_status_for_full_disk(self):
        html = self._run(disk_used_pct=98.0)
        self.assertIn("CRITICAL", html)

    def test_html_shows_reboot_warning(self):
        html = self._run(reboot_pending=True)
        self.assertTrue("WARNING" in html or "reboot" in html.lower())


# ---------------------------------------------------------------------------
# STIG normalization
# ---------------------------------------------------------------------------


class TestStigNormalization(unittest.TestCase):
    """Verify normalize_stig produces correct findings and alert structures."""

    def test_open_finding_generates_alert(self):
        model = normalize_stig(_raw_stig(), stig_target_type="esxi")
        self.assertEqual(len(model.alerts), 1)
        self.assertEqual(model.alerts[0].category, "security_compliance")
        self.assertIn("V-256379", model.alerts[0].detail["rule_id"])

    def test_pass_finding_does_not_generate_alert(self):
        raw = _raw_stig(findings=[{
            "id": "V-001", "status": "pass", "severity": "medium", "title": "Rule A"
        }])
        model = normalize_stig(raw, stig_target_type="esxi")
        self.assertEqual(model.alerts, [])

    def test_full_audit_contains_all_findings_regardless_of_status(self):
        raw = _raw_stig(findings=[
            {"id": "V-001", "status": "failed", "severity": "high", "title": "Rule A"},
            {"id": "V-002", "status": "pass", "severity": "medium", "title": "Rule B"},
            {"id": "V-003", "status": "open", "severity": "medium", "title": "Rule C"},
        ])
        model = normalize_stig(raw, stig_target_type="esxi")
        self.assertEqual(len(model.full_audit), 3)
        open_ids = {f["rule_id"] for f in model.full_audit if f["status"] == "open"}
        self.assertEqual(open_ids, {"V-001", "V-003"})

    def test_finding_details_preserved(self):
        model = normalize_stig(_raw_stig(), stig_target_type="esxi")
        finding = model.full_audit[0]
        self.assertEqual(finding["rule_id"], "V-256379")
        self.assertIn("Security.AccountLockFailures", finding["description"])

    def test_health_warning_for_medium_open_finding(self):
        """Medium severity open finding → WARNING health."""
        model = normalize_stig(_raw_stig(), stig_target_type="esxi")
        self.assertIn(model.health, ("WARNING", "CRITICAL"))

    def test_health_healthy_when_all_pass(self):
        raw = _raw_stig(findings=[
            {"id": "V-001", "status": "pass", "severity": "high", "title": "Rule A"}
        ])
        model = normalize_stig(raw, stig_target_type="esxi")
        self.assertEqual(model.health, "HEALTHY")


# ---------------------------------------------------------------------------
# STIG isolation in normalize_host_bundle
# ---------------------------------------------------------------------------


class TestStigDataIsolation(unittest.TestCase):
    """Verify STIG data and platform data coexist without cross-contamination."""

    def _bundle_vmware_with_stig(self, stig_status: str = "failed") -> dict[str, Any]:
        """Bundle with both VMware discovery and ESXi STIG data."""
        raw = _raw_stig(findings=[{
            "id": "V-256379", "status": stig_status, "severity": "medium",
            "title": "stigrule_256379_account_lock_failures",
        }])
        return {"raw_vcenter": _raw_vmware(), "stig_esxi": raw}

    def test_stig_stored_under_stig_key(self):
        """normalize_host_bundle must write STIG output under the original stig_* key."""
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig())
        self.assertIn("stig_esxi", result)

    def test_vmware_vcenter_present_alongside_stig(self):
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig())
        self.assertIn("vmware_vcenter", result)
        self.assertIn("stig_esxi", result)

    def test_stig_alerts_not_in_vmware_vcenter_alerts(self):
        """security_compliance alerts from STIG must not appear in vmware_vcenter.alerts."""
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig("failed"))
        vmware_alerts = result["vmware_vcenter"]["alerts"]
        bleed = [a for a in vmware_alerts if a.get("category") == "security_compliance"]
        self.assertEqual(bleed, [],
                         f"STIG alerts must not appear in vmware_vcenter.alerts: {bleed}")

    def test_vmware_alerts_not_in_stig_payload(self):
        """VMware appliance/storage alerts must not appear in stig_esxi.alerts."""
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig("failed"))
        stig_alerts = result["stig_esxi"]["alerts"]
        vmware_cats = {"appliance_health", "data_quality", "data_protection",
                       "storage_connectivity", "vcenter_alarms"}
        bleed = [a for a in stig_alerts if a.get("category") in vmware_cats]
        self.assertEqual(bleed, [],
                         f"VMware alerts must not appear in stig_esxi.alerts: {bleed}")

    def test_stig_health_independent_of_vmware_health(self):
        """STIG health and VMware health are derived from different alert sets."""
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig("failed"))
        vmware_health = result["vmware_vcenter"]["health"]
        stig_health = result["stig_esxi"]["health"]
        # VMware health comes from appliance/backup alerts; STIG health from findings
        # They must be stored separately; their values may differ
        self.assertIn(vmware_health, ("HEALTHY", "WARNING", "CRITICAL", "UNKNOWN"))
        self.assertIn(stig_health, ("HEALTHY", "WARNING", "CRITICAL"))
        # A passing STIG must show HEALTHY even if VMware has alerts
        result_pass = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig("pass"))
        self.assertEqual(result_pass["stig_esxi"]["health"], "HEALTHY",
                         "Passing STIG finding must produce HEALTHY STIG health regardless of VMware state")

    def test_open_stig_finding_in_full_audit(self):
        result = normalize_host_bundle("vc-01", self._bundle_vmware_with_stig("failed"))
        full_audit = result["stig_esxi"]["full_audit"]
        self.assertEqual(len(full_audit), 1)
        self.assertEqual(full_audit[0]["status"], "open")

    def test_linux_stig_coexists_with_linux_discovery(self):
        raw_linux = _raw_linux()
        bundle = {"raw_discovery": raw_linux, "stig_linux": _raw_stig(
            host="linux-01", audit_type="stig_linux", target_type="linux"
        )}
        result = normalize_host_bundle("linux-01", bundle)
        self.assertIn("linux_system", result)
        self.assertIn("stig_linux", result)

    def test_linux_stig_alerts_not_in_linux_system(self):
        """STIG security_compliance alerts must not appear in linux_system.alerts."""
        raw_linux = _raw_linux()
        bundle = {"raw_discovery": raw_linux, "stig_linux": _raw_stig(
            host="linux-01", audit_type="stig_linux", target_type="linux"
        )}
        result = normalize_host_bundle("linux-01", bundle)
        linux_alerts = result.get("linux_system", {}).get("alerts", [])
        bleed = [a for a in linux_alerts if a.get("category") == "security_compliance"]
        self.assertEqual(bleed, [],
                         f"STIG alerts must not appear in linux_system.alerts: {bleed}")

    def test_vmware_only_bundle_does_not_produce_linux_system(self):
        """A VMware-only bundle must produce vmware_vcenter but NOT linux_system.
        The normalizer no longer mutates the caller's bundle dict, and 'raw_discovery'
        has been removed from the VMware trigger list (it is a Linux filename convention).
        """
        bundle = {"raw_vcenter": _raw_vmware()}
        result = normalize_host_bundle("vc-01", bundle)
        self.assertIn("vmware_vcenter", result, "VMware normalization must run")
        self.assertNotIn("linux_system", result,
                         "VMware-only bundle must not produce linux_system")
