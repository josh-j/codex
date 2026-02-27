"""Tests for the _stig_apply module (break-glass ESXi STIG apply)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from ncs_reporter._stig_apply import (
    RuleMetadata,
    build_ansible_args,
    build_group_id_map,
    generate_all_disabled_vars,
    get_failing_rules,
    load_esxi_rule_metadata,
    rule_version_to_manage_var,
    _infer_rule_version,
)


class TestRuleVersionToManageVar(unittest.TestCase):
    def test_canonical(self) -> None:
        self.assertEqual(rule_version_to_manage_var("ESXI-70-000001"), "esxi_70_000001_Manage")

    def test_trailing_zeros(self) -> None:
        self.assertEqual(rule_version_to_manage_var("ESXI-70-000100"), "esxi_70_000100_Manage")

    def test_all_digits(self) -> None:
        # Ensure dashes become underscores and case is lowered before _Manage
        result = rule_version_to_manage_var("ESXI-70-000035")
        self.assertTrue(result.startswith("esxi_70_"))
        self.assertTrue(result.endswith("_Manage"))


class TestLoadEsxiRuleMetadata(unittest.TestCase):
    def test_loads_75_rules(self) -> None:
        meta = load_esxi_rule_metadata()
        self.assertEqual(len(meta), 75)

    def test_first_rule_fields(self) -> None:
        meta = load_esxi_rule_metadata()
        rule = meta["ESXI-70-000001"]
        self.assertIsInstance(rule, RuleMetadata)
        self.assertEqual(rule.rule_version, "ESXI-70-000001")
        self.assertIn("lockdown", rule.rule_title.lower())
        self.assertEqual(rule.manage_var, "esxi_70_000001_Manage")

    def test_severity_present(self) -> None:
        meta = load_esxi_rule_metadata()
        for rule in meta.values():
            self.assertIn(rule.severity, ("high", "medium", "low", "critical"))


class TestGenerateAllDisabledVars(unittest.TestCase):
    def test_all_false(self) -> None:
        meta = load_esxi_rule_metadata()
        disabled = generate_all_disabled_vars(meta)
        self.assertEqual(len(disabled), 75)
        self.assertTrue(all(v is False for v in disabled.values()))

    def test_keys_end_with_manage(self) -> None:
        meta = load_esxi_rule_metadata()
        disabled = generate_all_disabled_vars(meta)
        for key in disabled:
            self.assertTrue(key.endswith("_Manage"), f"Bad key: {key}")


class TestGetFailingRules(unittest.TestCase):
    def _write_artifact(self, tmp_dir: str, rows: list[dict]) -> Path:
        artifact = Path(tmp_dir) / "raw_stig_esxi.yaml"
        data = {
            "metadata": {"host": "esxi-01", "audit_type": "stig_esxi", "timestamp": "2026-02-27T00:00:00Z"},
            "data": rows,
            "target_type": "esxi",
        }
        with open(artifact, "w") as f:
            yaml.dump(data, f)
        return artifact

    def test_returns_only_open_rules(self) -> None:
        rows = [
            {"id": "V-256375", "rule_version": "ESXI-70-000001", "status": "failed", "severity": "medium", "title": "Lockdown"},
            {"id": "V-256376", "rule_version": "ESXI-70-000002", "status": "pass", "severity": "medium", "title": "Passed rule"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp, rows)
            failing = get_failing_rules(artifact)
        self.assertEqual(len(failing), 1)
        self.assertEqual(failing[0]["status"], "open")

    def test_empty_when_no_findings(self) -> None:
        rows = [
            {"id": "V-256375", "rule_version": "ESXI-70-000001", "status": "pass", "severity": "medium", "title": "OK"},
        ]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp, rows)
            failing = get_failing_rules(artifact)
        self.assertEqual(failing, [])

    def test_raises_on_non_mapping(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "bad.yaml"
            artifact.write_text("- just a list\n")
            with self.assertRaises(ValueError):
                get_failing_rules(artifact)


class TestBuildGroupIdMap(unittest.TestCase):
    def test_maps_v_number_to_rule_version(self) -> None:
        meta = load_esxi_rule_metadata()
        gmap = build_group_id_map(meta)
        self.assertEqual(gmap["V-256375"], "ESXI-70-000001")
        self.assertEqual(gmap["V-256376"], "ESXI-70-000002")

    def test_all_entries_have_v_prefix(self) -> None:
        meta = load_esxi_rule_metadata()
        gmap = build_group_id_map(meta)
        self.assertEqual(len(gmap), 75)
        for k in gmap:
            self.assertTrue(k.startswith("V-"), f"Unexpected key: {k}")


class TestInferRuleVersion(unittest.TestCase):
    def test_direct_key(self) -> None:
        row = {"rule_version": "ESXI-70-000005", "id": "V-256379"}
        self.assertEqual(_infer_rule_version(row), "ESXI-70-000005")

    def test_fallback_to_rule_id(self) -> None:
        row = {"rule_id": "ESXI-70-000035"}
        self.assertEqual(_infer_rule_version(row), "ESXI-70-000035")

    def test_fallback_to_id(self) -> None:
        row = {"id": "ESXI-70-000010"}
        self.assertEqual(_infer_rule_version(row), "ESXI-70-000010")

    def test_no_match_returns_empty_without_map(self) -> None:
        """Without a group_id_map, V-format IDs cannot be resolved."""
        row = {"id": "V-256375", "rule_id": "SV-256375r958398_rule"}
        self.assertEqual(_infer_rule_version(row), "")

    def test_v_number_resolved_via_group_id_map(self) -> None:
        """stig_xml callback produces V-format IDs; map resolves them to ESXI-70-*."""
        meta = load_esxi_rule_metadata()
        gmap = build_group_id_map(meta)
        row = {"id": "V-256375", "rule_id": "V-256375"}
        self.assertEqual(_infer_rule_version(row, gmap), "ESXI-70-000001")

    def test_v_number_in_rule_id_field(self) -> None:
        meta = load_esxi_rule_metadata()
        gmap = build_group_id_map(meta)
        row = {"rule_id": "V-256376", "name": "esxi-01.local"}
        self.assertEqual(_infer_rule_version(row, gmap), "ESXI-70-000002")

    def test_direct_key_takes_precedence_over_map(self) -> None:
        meta = load_esxi_rule_metadata()
        gmap = build_group_id_map(meta)
        row = {"rule_version": "ESXI-70-000005", "id": "V-256375"}
        self.assertEqual(_infer_rule_version(row, gmap), "ESXI-70-000005")


class TestBuildAnsibleArgs(unittest.TestCase):
    def test_basic_structure(self) -> None:
        args = build_ansible_args(
            playbook="playbooks/vmware_stig_remediate.yml",
            inventory="inventory/production/hosts.yaml",
            limit="vcenter1",
            manage_var="esxi_70_000001_Manage",
            all_disabled_file="/tmp/disabled.yaml",
            esxi_host="esxi-01.local",
        )
        self.assertIn("ansible-playbook", args)
        self.assertIn("playbooks/vmware_stig_remediate.yml", args)
        self.assertIn("-l", args)
        self.assertIn("vcenter1", args)
        self.assertIn("-e@/tmp/disabled.yaml", args)
        self.assertIn("-eesxi_70_000001_Manage=true", args)
        self.assertIn("-evmware_stig_enable_hardening=true", args)
        self.assertIn("-eesxi_stig_target_hosts=['esxi-01.local']", args)

    def test_skip_tags_included(self) -> None:
        args = build_ansible_args(
            playbook="p.yml",
            inventory="i.yaml",
            limit="vc1",
            manage_var="esxi_70_000001_Manage",
            all_disabled_file="/tmp/d.yaml",
            esxi_host="esxi-01.local",
            skip_tags=["snapshot", "vm"],
        )
        idx = args.index("--skip-tags")
        self.assertEqual(args[idx + 1], "snapshot,vm")

    def test_extra_vars_appended(self) -> None:
        args = build_ansible_args(
            playbook="p.yml",
            inventory="i.yaml",
            limit="vc1",
            manage_var="esxi_70_000001_Manage",
            all_disabled_file="/tmp/d.yaml",
            esxi_host="esxi-01.local",
            extra_vars=("foo=bar", "baz=qux"),
        )
        # Each extra var should appear after a '-e' flag
        pairs = [(args[i], args[i + 1]) for i in range(len(args) - 1) if args[i] == "-e"]
        extra_values = [v for _, v in pairs]
        self.assertIn("foo=bar", extra_values)
        self.assertIn("baz=qux", extra_values)

    def test_esxi_stig_target_hosts_in_args(self) -> None:
        args = build_ansible_args(
            playbook="p.yml",
            inventory="i.yaml",
            limit="vc1",
            manage_var="esxi_70_000035_Manage",
            all_disabled_file="/tmp/d.yaml",
            esxi_host="esxi-02.site1.local",
        )
        self.assertIn("-eesxi_stig_target_hosts=['esxi-02.site1.local']", args)


class TestStigApplyCLIDryRun(unittest.TestCase):
    """Integration-level test: run stig-apply --dry-run via Click test runner."""

    def _write_artifact(self, tmp_dir: str) -> Path:
        """Artifact with explicit rule_version (legacy / ncs_collector format)."""
        rows = [
            {
                "id": "V-256375",
                "rule_version": "ESXI-70-000001",
                "status": "failed",
                "severity": "medium",
                "title": "Lockdown Mode",
                "checktext": "Lockdown mode is disabled.",
            }
        ]
        artifact = Path(tmp_dir) / "raw_stig_esxi.yaml"
        data = {
            "metadata": {"host": "esxi-01", "audit_type": "stig_esxi", "timestamp": "2026-02-27T00:00:00Z"},
            "data": rows,
            "target_type": "esxi",
        }
        with open(artifact, "w") as f:
            yaml.dump(data, f)
        return artifact

    def _write_stig_xml_artifact(self, tmp_dir: str) -> Path:
        """Artifact produced by the stig_xml callback: V-format IDs, no rule_version."""
        rows = [
            {
                "id": "V-256375",
                "rule_id": "V-256375",
                "name": "esxi-01.local",
                "status": "failed",
                "severity": "medium",
                "title": "Lockdown Mode",
                "checktext": "Lockdown mode is disabled.",
                "fixtext": "",
            }
        ]
        artifact = Path(tmp_dir) / "raw_stig_esxi.yaml"
        data = {
            "metadata": {"host": "esxi-01", "audit_type": "stig_esxi", "timestamp": "2026-02-27T00:00:00Z"},
            "data": rows,
            "target_type": "esxi",
        }
        with open(artifact, "w") as f:
            yaml.dump(data, f)
        return artifact

    def test_dry_run_prints_commands(self) -> None:
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="y\ny\n",  # Apply? y, Continue? y
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("DRY-RUN", result.output)
        self.assertIn("ansible-playbook", result.output)
        self.assertIn("esxi_70_000001_Manage=true", result.output)
        self.assertIn("esxi_stig_target_hosts=['esxi-01.local']", result.output)
        self.assertIn("Summary:", result.output)
        # Post-remediation audit should be skipped by default
        self.assertIn("audit", result.output.lower())  # skip-tags line contains "audit"

    def test_stig_xml_v_format_artifact_resolves_rule_version(self) -> None:
        """stig_xml callback artifacts (V-format IDs, no rule_version) must resolve correctly."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_stig_xml_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="y\ny\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        # V-256375 maps to ESXI-70-000001 via the skeleton group_id map
        self.assertIn("esxi_70_000001_Manage=true", result.output)
        self.assertNotIn("Could not determine rule_version", result.output)

    def test_dry_run_skip_tags_exclude_audit_by_default(self) -> None:
        """Without --post-audit, the ansible command must skip the audit phase."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="y\ny\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        # The --skip-tags value in the dry-run output must include "audit"
        self.assertIn("snapshot,vm,audit", result.output)

    def test_dry_run_post_audit_includes_audit_phase(self) -> None:
        """With --post-audit, the ansible command must NOT skip the audit phase."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--post-audit",
                    "--dry-run",
                ],
                input="y\ny\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        # audit must NOT appear in skip-tags
        self.assertNotIn("snapshot,vm,audit", result.output)
        self.assertIn("snapshot,vm", result.output)

    def test_snapshot_note_shown_without_skip_snapshot(self) -> None:
        """Without --skip-snapshot, an informational note is printed."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--dry-run",
                ],
                input="y\ny\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("not applicable", result.output)

    def test_snapshot_note_suppressed_with_skip_snapshot(self) -> None:
        """With --skip-snapshot, the informational note is suppressed."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="y\ny\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertNotIn("not applicable", result.output)

    def test_dry_run_skip_rule(self) -> None:
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="n\n",  # Apply? n → skip
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("Skipped", result.output)
        self.assertIn("Summary:", result.output)

    def test_dry_run_abort(self) -> None:
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_artifact(tmp)
            result = runner.invoke(
                main,
                [
                    "stig-apply",
                    str(artifact),
                    "--limit", "vcenter1",
                    "--esxi-host", "esxi-01.local",
                    "--skip-snapshot",
                    "--dry-run",
                ],
                input="abort\n",
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("Aborted", result.output)

    def test_no_failing_rules(self) -> None:
        """When artifact has no open findings, the command exits cleanly."""
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        rows = [{"id": "V-256375", "rule_version": "ESXI-70-000001", "status": "pass", "severity": "medium", "title": "OK"}]
        with tempfile.TemporaryDirectory() as tmp:
            artifact = Path(tmp) / "raw_stig_esxi.yaml"
            data = {
                "metadata": {"host": "esxi-01", "audit_type": "stig_esxi", "timestamp": "2026-02-27T00:00:00Z"},
                "data": rows,
                "target_type": "esxi",
            }
            with open(artifact, "w") as f:
                yaml.dump(data, f)

            runner = CliRunner()
            result = runner.invoke(
                main,
                ["stig-apply", str(artifact), "--limit", "vcenter1", "--esxi-host", "esxi-01.local", "--skip-snapshot", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("No failing", result.output)
