"""Tests for ncs_reporter CLI commands and helpers."""

from pathlib import Path
import tempfile
import unittest

import yaml
from click.testing import CliRunner

from ncs_reporter._report_context import get_jinja_env
from ncs_reporter.cli import main
from ncs_reporter.view_models.common import status_badge_meta


def _linux_host_bundle():
    return {
        "system": {
            "health": "OK",
            "distribution": "Ubuntu",
            "distribution_version": "24.04",
            "summary": {"critical_count": 0, "warning_count": 0},
            "alerts": [],
            "data": {"system": {"services": {"failed_list": []}, "disks": []}},
        },
    }


def _vmware_host_bundle():
    return {
        "raw_vcsa": {
            "metadata": {"host": "vc01", "timestamp": "2025-01-01T00:00:00Z"},
            "data": {
                "appliance_version": "8.0.2",
                "appliance_build": "23319199",
                "appliance_uptime_seconds": 864000,
                "appliance_health_overall": "green",
                "appliance_health_cpu": "green",
                "appliance_health_memory": "green",
                "appliance_health_database": "green",
                "appliance_health_storage": "green",
                "ssh_enabled": False,
                "shell_enabled": False,
                "ntp_mode": "NTP",
                "backup_schedules": [],
                "backup_schedule_count": 0,
                "active_alarms": [],
                "alarm_count": 0,
                "vcenter_count": 1,
                "datacenter_count": 1,
                "cluster_count": 1,
                "esxi_host_count": 2,
                "datastore_count": 0,
                "clusters": [],
                "datastores": [],
            },
        },
    }


def _windows_host_bundle():
    return {
        "system": {
            "health": "OK",
            "hostname": "win01",
            "os_name": "Windows Server 2022",
            "summary": {"critical_count": 0, "warning_count": 0},
            "alerts": [],
        },
    }


class StatusBadgeMetaTests(unittest.TestCase):
    def test_ok_values(self):
        for val in ("OK", "HEALTHY", "GREEN", "PASS", "RUNNING"):
            result = status_badge_meta(val)
            self.assertEqual(result["css_class"], "status-ok")
            self.assertEqual(result["label"], "OK")

    def test_fail_values(self):
        for val in ("CRITICAL", "RED", "FAILED", "FAIL", "STOPPED"):
            result = status_badge_meta(val)
            self.assertEqual(result["css_class"], "status-fail")
            self.assertEqual(result["label"], "CRITICAL")

    def test_warn_values(self):
        for val in ("WARNING", "YELLOW", "DEGRADED", "UNKNOWN"):
            result = status_badge_meta(val)
            self.assertEqual(result["css_class"], "status-warn")

    def test_preserve_label(self):
        self.assertEqual(status_badge_meta("HEALTHY", preserve_label=True)["label"], "HEALTHY")
        self.assertEqual(status_badge_meta("FAILED", preserve_label=True)["label"], "FAILED")

    def test_none_input(self):
        self.assertEqual(status_badge_meta(None)["css_class"], "status-warn")

    def test_case_insensitive(self):
        self.assertEqual(status_badge_meta("healthy")["css_class"], "status-ok")


class GetJinjaEnvTests(unittest.TestCase):
    def test_returns_environment_with_status_filter(self):
        self.assertIn("status_badge_meta", get_jinja_env().filters)

    def test_can_load_templates(self):
        env = get_jinja_env()
        assert env.loader is not None
        self.assertTrue(len(env.loader.list_templates()) > 0)

    def test_autoescape_enabled(self):
        self.assertTrue(get_jinja_env().autoescape)


class SiteCommandTests(unittest.TestCase):
    def test_site_generates_dashboard(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            all_data = {
                "metadata": {"fleet_stats": {"total_hosts": 2}},
                "hosts": {
                    "host1": _linux_host_bundle(),
                    "vc01": _vmware_host_bundle(),
                },
            }
            input_path = Path(tmpdir) / "all_hosts_state.yaml"
            input_path.write_text(yaml.dump(all_data, default_flow_style=False))

            output_dir = Path(tmpdir) / "reports"
            result = runner.invoke(
                main,
                ["site", "-i", str(input_path), "-o", str(output_dir), "--report-stamp", "20250101"],
            )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue((output_dir / "site.html").exists())


class NodeCommandTests(unittest.TestCase):
    def test_node_linux(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "host1.yaml"
            input_path.write_text(yaml.dump(_linux_host_bundle()))

            output_dir = Path(tmpdir) / "reports"
            result = runner.invoke(
                main,
                ["node", "-p", "linux", "-i", str(input_path), "-n", "host1", "-o", str(output_dir)],
            )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue((output_dir / "host1.html").exists())

    def test_node_vmware(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "vc01.yaml"
            input_path.write_text(yaml.dump(_vmware_host_bundle()))

            output_dir = Path(tmpdir) / "reports"
            result = runner.invoke(
                main,
                ["node", "-p", "vmware", "-i", str(input_path), "-n", "vc01", "-o", str(output_dir)],
            )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue((output_dir / "vc01.html").exists())

    def test_node_windows(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = Path(tmpdir) / "win01.yaml"
            input_path.write_text(yaml.dump(_windows_host_bundle()))

            output_dir = Path(tmpdir) / "reports"
            result = runner.invoke(
                main,
                ["node", "-p", "windows", "-i", str(input_path), "-n", "win01", "-o", str(output_dir)],
            )
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue((output_dir / "win01.html").exists())

    def test_node_invalid_platform_rejected(self):
        runner = CliRunner()
        result = runner.invoke(
            main,
            ["node", "-p", "solaris", "-i", "/dev/null", "-n", "x", "-o", "/tmp"],
        )
        self.assertNotEqual(result.exit_code, 0)


if __name__ == "__main__":
    unittest.main()
