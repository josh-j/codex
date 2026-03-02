"""Integration test for deterministic full-production STIG simulation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from click.testing import CliRunner

from _paths import NCS_ANSIBLE_ROOT, SCHEMAS_DIR

try:
    from ncs_reporter.cli import main
except ModuleNotFoundError:
    repo_root = NCS_ANSIBLE_ROOT.parent
    reporter_src = repo_root / "ncs_reporter" / "src"
    core_src = repo_root / "libs" / "ncs_core" / "src"
    for path in (reporter_src, core_src):
        if path.exists():
            sys.path.insert(0, str(path))
    from ncs_reporter.cli import main

REQUIRED_TARGETS = (
    "vcsa,esxi,vm,windows,ubuntu,photon,"
    "vami,eam,lookup_svc,perfcharts,vcsa_photon_os,postgresql,rhttpproxy,sts,ui"
)
VCSA_COMPONENTS = [
    "vami",
    "eam",
    "lookup_svc",
    "perfcharts",
    "vcsa_photon_os",
    "postgresql",
    "rhttpproxy",
    "sts",
    "ui",
]


class TestSimulatedProductionStigRun(unittest.TestCase):
    def setUp(self) -> None:
        self.runner = CliRunner()
        self.tmp = tempfile.TemporaryDirectory()
        self.out_root = Path(self.tmp.name) / "mock_production_run"
        self.platform_root = self.out_root / "platform"
        self.groups_json = self.platform_root / "inventory_groups.json"
        self.inventory = NCS_ANSIBLE_ROOT / "inventory" / "production" / "hosts.yaml"

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_full_simulation_pipeline_with_vcsa_components(self) -> None:
        generator = NCS_ANSIBLE_ROOT / "scripts" / "generate_mock_production_stig_run.py"
        verifier = NCS_ANSIBLE_ROOT / "scripts" / "verify_report_artifacts.py"

        subprocess.run(
            [
                sys.executable,
                str(generator),
                "--inventory",
                str(self.inventory),
                "--out-root",
                str(self.out_root),
                "--stamp",
                "20260302",
            ],
            check=True,
            cwd=NCS_ANSIBLE_ROOT,
        )

        result = self.runner.invoke(
            main,
            [
                "all",
                "--platform-root",
                str(self.platform_root),
                "--reports-root",
                str(self.out_root),
                "--groups",
                str(self.groups_json),
                "--config-dir",
                str(SCHEMAS_DIR),
                "--report-stamp",
                "20260302",
            ],
        )
        self.assertEqual(result.exit_code, 0, f"ncs-reporter all failed:\n{result.output}")

        subprocess.run(
            [
                sys.executable,
                str(verifier),
                "--report-root",
                str(self.out_root),
            ],
            check=True,
            cwd=NCS_ANSIBLE_ROOT,
        )

        subprocess.run(
            [
                sys.executable,
                str(verifier),
                "--report-root",
                str(self.out_root),
                "--require-targets",
                REQUIRED_TARGETS,
                "--min-hosts-per-target",
                "1",
            ],
            check=True,
            cwd=NCS_ANSIBLE_ROOT,
        )

        self.assertTrue((self.out_root / "site_health_report.html").exists())
        self.assertTrue((self.out_root / "stig_fleet_report.html").exists())

        groups = json.loads(self.groups_json.read_text(encoding="utf-8"))
        vcenters = groups.get("vcenters", [])
        self.assertGreaterEqual(len(vcenters), 1, "Expected at least one vCenter host from inventory")

        cklb_dir = self.out_root / "cklb"
        for vc in vcenters:
            for component in VCSA_COMPONENTS:
                cklb_path = cklb_dir / f"{vc}_{component}.cklb"
                self.assertTrue(cklb_path.exists(), f"Missing VCSA component CKLB: {cklb_path}")


if __name__ == "__main__":
    unittest.main()
