"""Tests for ncs_reporter CLI commands and helpers."""

import os
import tempfile
import unittest

import yaml
from click.testing import CliRunner

from ncs_reporter.cli import get_jinja_env, main, status_badge_meta


# ---------------------------------------------------------------------------
# Minimal fixture data that satisfies view-model builders + Jinja templates
# ---------------------------------------------------------------------------

def _linux_host_bundle():
    return {
        "system": {
            "health": "OK",
            "distribution": "Ubuntu",
            "distribution_version": "24.04",
            "summary": {"critical_count": 0, "warning_count": 0},
            "alerts": [],
            "data": {
                "system": {
                    "services": {"failed_list": []},
                    "disks": [
                        {"mount": "/", "device": "/dev/sda1", "free_gb": 50, "total_gb": 100, "used_pct": 50},
                    ],
                }
            },
        },
    }


def _vmware_host_bundle():
    return {
        "discovery": {
            "summary": {"clusters": 1, "hosts": 2, "vms": 10},
            "health": {"appliance": {"info": {"version": "8.0.2"}}},
            "inventory": {
                "clusters": {
                    "list": [
                        {
                            "name": "Cluster-A",
                            "datacenter": "DC1",
                            "utilization": {"cpu_pct": 50.0, "mem_pct": 40.0},
                            "compliance": {"ha_enabled": True, "drs_enabled": True},
                        }
                    ]
                }
            },
        },
        "vcenter": {
            "alerts": [],
            "vcenter_health": {
                "health": "green",
                "data": {
                    "utilization": {
                        "cpu_total_mhz": 10000,
                        "cpu_used_mhz": 5000,
                        "mem_total_mb": 32000,
                        "mem_used_mb": 16000,
                    }
                },
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


def _write_aggregated_yaml(path, hosts_data):
    data = {
        "metadata": {
            "generated_at": "2025-01-01T00:00:00",
            "fleet_stats": {"total_hosts": len(hosts_data), "critical_alerts": 0, "warning_alerts": 0},
        },
        "hosts": hosts_data,
    }
    with open(path, "w") as f:
        yaml.dump(data, f, default_flow_style=False)


# ---------------------------------------------------------------------------
# status_badge_meta
# ---------------------------------------------------------------------------

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
        result = status_badge_meta("HEALTHY", preserve_label=True)
        self.assertEqual(result["label"], "HEALTHY")
        result = status_badge_meta("FAILED", preserve_label=True)
        self.assertEqual(result["label"], "FAILED")

    def test_none_input(self):
        result = status_badge_meta(None)
        self.assertEqual(result["css_class"], "status-warn")

    def test_case_insensitive(self):
        result = status_badge_meta("healthy")
        self.assertEqual(result["css_class"], "status-ok")


# ---------------------------------------------------------------------------
# get_jinja_env
# ---------------------------------------------------------------------------

class GetJinjaEnvTests(unittest.TestCase):

    def test_returns_environment_with_status_filter(self):
        env = get_jinja_env()
        self.assertIn("status_badge_meta", env.filters)

    def test_can_load_templates(self):
        env = get_jinja_env()
        # Should be able to list templates without error
        assert env.loader is not None
        tpl_names = env.loader.list_templates()
        self.assertTrue(len(tpl_names) > 0)

    def test_autoescape_enabled(self):
        env = get_jinja_env()
        self.assertTrue(env.autoescape)


# ---------------------------------------------------------------------------
# collect command
# ---------------------------------------------------------------------------

class CollectCommandTests(unittest.TestCase):

    def test_collect_aggregates_host_reports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create host report dirs
            host_dir = os.path.join(tmpdir, "reports", "host1")
            os.makedirs(host_dir)
            with open(os.path.join(host_dir, "audit.yaml"), "w") as f:
                yaml.dump({"data": {"audit_type": "audit", "status": "OK"}}, f)

            output_path = os.path.join(tmpdir, "output", "fleet_state.yaml")

            result = runner.invoke(main, ["collect", "--report-dir", os.path.join(tmpdir, "reports"), "--output", output_path])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("Success", result.output)
            self.assertTrue(os.path.exists(output_path))

            with open(output_path) as f:
                loaded = yaml.safe_load(f)
            self.assertIn("host1", loaded["hosts"])

    def test_collect_with_filter(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            host_dir = os.path.join(tmpdir, "reports", "host1")
            os.makedirs(host_dir)
            with open(os.path.join(host_dir, "discovery.yaml"), "w") as f:
                yaml.dump({"data": {"audit_type": "discovery", "found": True}}, f)
            with open(os.path.join(host_dir, "audit.yaml"), "w") as f:
                yaml.dump({"data": {"audit_type": "audit", "checked": True}}, f)

            output_path = os.path.join(tmpdir, "fleet.yaml")
            result = runner.invoke(main, [
                "collect", "--report-dir", os.path.join(tmpdir, "reports"),
                "--output", output_path, "--filter", "discovery",
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_collect_invalid_dir(self):
        runner = CliRunner()
        result = runner.invoke(main, ["collect", "--report-dir", "/tmp/nonexistent_ncs_test", "--output", "/tmp/out.yaml"])
        # Click should reject non-existent path
        self.assertNotEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# linux command
# ---------------------------------------------------------------------------

class LinuxCommandTests(unittest.TestCase):

    def test_linux_generates_reports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "linux_state.yaml")
            _write_aggregated_yaml(input_path, {"host1": _linux_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, ["linux", "-i", input_path, "-o", output_dir, "--report-stamp", "20250101"])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertIn("Done", result.output)

            # Fleet report should exist
            self.assertTrue(os.path.exists(os.path.join(output_dir, "linux_fleet_report_20250101.html")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "linux_fleet_report.html")))
            # Host report
            self.assertTrue(os.path.exists(os.path.join(output_dir, "host1", "health_report_20250101.html")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "host1", "health_report.html")))


# ---------------------------------------------------------------------------
# vmware command
# ---------------------------------------------------------------------------

class VmwareCommandTests(unittest.TestCase):

    def test_vmware_generates_reports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "vmware_state.yaml")
            _write_aggregated_yaml(input_path, {"vc01": _vmware_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, ["vmware", "-i", input_path, "-o", output_dir, "--report-stamp", "20250101"])
            self.assertEqual(result.exit_code, 0, msg=result.output)

            self.assertTrue(os.path.exists(os.path.join(output_dir, "vcenter_fleet_report_20250101.html")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "vc01", "health_report.html")))


# ---------------------------------------------------------------------------
# windows command
# ---------------------------------------------------------------------------

class WindowsCommandTests(unittest.TestCase):

    def test_windows_generates_reports(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "windows_state.yaml")
            _write_aggregated_yaml(input_path, {"win01": _windows_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, ["windows", "-i", input_path, "-o", output_dir, "--report-stamp", "20250101"])
            self.assertEqual(result.exit_code, 0, msg=result.output)

            self.assertTrue(os.path.exists(os.path.join(output_dir, "windows_fleet_report_20250101.html")))
            self.assertTrue(os.path.exists(os.path.join(output_dir, "win01", "health_report.html")))

    def test_windows_no_csv_flag(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "windows_state.yaml")
            _write_aggregated_yaml(input_path, {"win01": _windows_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "windows", "-i", input_path, "-o", output_dir, "--no-csv",
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)

    def test_windows_csv_export_with_data(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            bundle = _windows_host_bundle()
            bundle["windows_ctx"] = {
                "applications": {
                    "configmgr_apps": [
                        {"server": "win01", "app_name": "TestApp", "version": "1.0", "publisher": "Acme", "install_state": "Installed"},
                    ],
                }
            }
            input_path = os.path.join(tmpdir, "windows_state.yaml")
            _write_aggregated_yaml(input_path, {"win01": bundle})

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, ["windows", "-i", input_path, "-o", output_dir, "--csv"])
            self.assertEqual(result.exit_code, 0, msg=result.output)

            # CSV should be generated for the configmgr_apps definition
            csv_path = os.path.join(output_dir, "win01", "windows_configmgr_apps_win01.csv")
            self.assertTrue(os.path.exists(csv_path), f"Expected CSV at {csv_path}")


# ---------------------------------------------------------------------------
# site command
# ---------------------------------------------------------------------------

class SiteCommandTests(unittest.TestCase):

    def test_site_generates_dashboard(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a minimal aggregated state with all platforms
            all_data = {
                "metadata": {"fleet_stats": {"total_hosts": 2}},
                "hosts": {
                    "host1": _linux_host_bundle(),
                    "vc01": _vmware_host_bundle(),
                },
            }
            input_path = os.path.join(tmpdir, "all_hosts_state.yaml")
            with open(input_path, "w") as f:
                yaml.dump(all_data, f, default_flow_style=False)

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "site", "-i", input_path, "-o", output_dir, "--report-stamp", "20250101",
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "site_health_report.html")))

    def test_site_with_groups_file(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            all_data = {"hosts": {"host1": _linux_host_bundle()}}
            input_path = os.path.join(tmpdir, "state.yaml")
            with open(input_path, "w") as f:
                yaml.dump(all_data, f)

            groups_path = os.path.join(tmpdir, "groups.yaml")
            with open(groups_path, "w") as f:
                yaml.dump({"linux": {"hosts": ["host1"]}}, f)

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "site", "-i", input_path, "-g", groups_path, "-o", output_dir,
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)


# ---------------------------------------------------------------------------
# node command
# ---------------------------------------------------------------------------

class NodeCommandTests(unittest.TestCase):

    def test_node_linux(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "host1.yaml")
            with open(input_path, "w") as f:
                yaml.dump(_linux_host_bundle(), f)

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "node", "-p", "linux", "-i", input_path, "-n", "host1", "-o", output_dir,
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "host1_health_report.html")))

    def test_node_vmware(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "vc01.yaml")
            with open(input_path, "w") as f:
                yaml.dump(_vmware_host_bundle(), f)

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "node", "-p", "vmware", "-i", input_path, "-n", "vc01", "-o", output_dir,
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "vc01_health_report.html")))

    def test_node_windows(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "win01.yaml")
            with open(input_path, "w") as f:
                yaml.dump(_windows_host_bundle(), f)

            output_dir = os.path.join(tmpdir, "reports")
            result = runner.invoke(main, [
                "node", "-p", "windows", "-i", input_path, "-n", "win01", "-o", output_dir,
            ])
            self.assertEqual(result.exit_code, 0, msg=result.output)
            self.assertTrue(os.path.exists(os.path.join(output_dir, "win01_health_report.html")))

    def test_node_invalid_platform_rejected(self):
        runner = CliRunner()
        result = runner.invoke(main, [
            "node", "-p", "solaris", "-i", "/dev/null", "-n", "x", "-o", "/tmp",
        ])
        self.assertNotEqual(result.exit_code, 0)


# ---------------------------------------------------------------------------
# Report content validation
# ---------------------------------------------------------------------------

class ReportContentTests(unittest.TestCase):

    def test_linux_report_contains_hostname(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "state.yaml")
            _write_aggregated_yaml(input_path, {"mylinuxhost": _linux_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            runner.invoke(main, ["linux", "-i", input_path, "-o", output_dir])

            report = os.path.join(output_dir, "mylinuxhost", "health_report.html")
            with open(report) as f:
                content = f.read()
            self.assertIn("mylinuxhost", content)

    def test_vmware_report_contains_html_structure(self):
        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmpdir:
            input_path = os.path.join(tmpdir, "state.yaml")
            _write_aggregated_yaml(input_path, {"vc01": _vmware_host_bundle()})

            output_dir = os.path.join(tmpdir, "reports")
            runner.invoke(main, ["vmware", "-i", input_path, "-o", output_dir])

            report = os.path.join(output_dir, "vcenter_fleet_report.html")
            with open(report) as f:
                content = f.read()
            self.assertIn("<!DOCTYPE html>", content)
            self.assertIn("</html>", content)


if __name__ == "__main__":
    unittest.main()
