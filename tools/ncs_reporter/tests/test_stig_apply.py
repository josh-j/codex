"""Tests for the _stig_apply module (break-glass ESXi STIG apply)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from ncs_reporter._stig_apply import (
    RULE_REQUIRED_VARS,
    RuleMetadata,
    build_ansible_args,
    build_group_id_map,
    build_interactive_playbook,
    check_rule_config_vars,
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


class TestCheckRuleConfigVars(unittest.TestCase):
    def test_no_warnings_for_rules_without_requirements(self) -> None:
        # ESXI-70-000001 has no required config var
        result = check_rule_config_vars(["ESXI-70-000001"])
        self.assertEqual(result, [])

    def test_warns_when_config_var_not_in_extra_vars(self) -> None:
        result = check_rule_config_vars(["ESXI-70-000004"])
        self.assertEqual(len(result), 1)
        rv, var = result[0]
        self.assertEqual(rv, "ESXI-70-000004")
        self.assertEqual(var, "esxi_stig_syslog_host")

    def test_suppressed_when_var_in_extra_vars(self) -> None:
        result = check_rule_config_vars(
            ["ESXI-70-000004"],
            extra_vars=("esxi_stig_syslog_host=syslog.site1.local",),
        )
        self.assertEqual(result, [])

    def test_all_five_config_rules_detected(self) -> None:
        rules = list(RULE_REQUIRED_VARS.keys())
        result = check_rule_config_vars(rules)
        self.assertEqual(len(result), 5)
        detected_vars = {var for _, var in result}
        self.assertEqual(detected_vars, set(RULE_REQUIRED_VARS.values()))

    def test_at_file_extra_var_ignored(self) -> None:
        # @file forms cannot be parsed for var names; should not suppress warning
        result = check_rule_config_vars(
            ["ESXI-70-000004"],
            extra_vars=("@/tmp/vars.yaml",),
        )
        self.assertEqual(len(result), 1)

    def test_mixed_extra_vars(self) -> None:
        result = check_rule_config_vars(
            ["ESXI-70-000004", "ESXI-70-000007"],
            extra_vars=("esxi_stig_syslog_host=syslog.local", "unrelated=val"),
        )
        # 000004 is satisfied; 000007 (esxi_stig_welcome_message) is not
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0][1], "esxi_stig_welcome_message")


class TestBuildInteractivePlaybook(unittest.TestCase):
    def setUp(self) -> None:
        self.metadata = load_esxi_rule_metadata()
        self.group_id_map = build_group_id_map(self.metadata)

    def _row(self, rule_version: str) -> dict:
        return {"rule_version": rule_version, "status": "failed", "severity": "medium", "title": "Test rule"}

    def _build(self, rows: list[dict], esxi_host: str = "esxi-01.local") -> list:
        raw = build_interactive_playbook(rows, self.metadata, self.group_id_map, esxi_host=esxi_host)
        result = yaml.safe_load(raw)
        assert isinstance(result, list)
        return result

    def test_returns_valid_yaml(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        self.assertEqual(len(plays), 1)
        self.assertIsInstance(plays[0]["tasks"], list)

    def test_esxi_host_in_play_vars(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")], esxi_host="esxi-02.site.local")
        self.assertIn("esxi-02.site.local", plays[0]["vars"]["esxi_stig_target_hosts"])

    def test_all_manage_vars_disabled_at_play_level(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        # Play-level vars should have all 75 manage vars set to False
        play_vars = plays[0]["vars"]
        self.assertFalse(play_vars["esxi_70_000001_Manage"])
        self.assertFalse(play_vars["esxi_70_000002_Manage"])

    def test_three_tasks_per_rule(self) -> None:
        # 3 tasks per rule: pause (with banner in prompt), abort-fail, include_role
        plays = self._build([self._row("ESXI-70-000001"), self._row("ESXI-70-000002")])
        self.assertEqual(len(plays[0]["tasks"]), 6)

    def test_banner_embedded_in_pause_prompt(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        pause_task = plays[0]["tasks"][0]
        prompt = pause_task["ansible.builtin.pause"]["prompt"]
        self.assertIn("ESXI-70-000001", prompt)
        self.assertIn("y/n/abort", prompt)

    def test_apply_task_enables_only_target_rule(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        apply_task = plays[0]["tasks"][2]  # 3rd task: include_role
        self.assertTrue(apply_task["vars"]["esxi_70_000001_Manage"])

    def test_apply_task_has_when_condition(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        apply_task = plays[0]["tasks"][2]
        when = apply_task["when"]
        self.assertIn("y", when)
        self.assertIn("yes", when)

    def test_abort_task_is_fail_with_when(self) -> None:
        plays = self._build([self._row("ESXI-70-000001")])
        abort_task = plays[0]["tasks"][1]  # 2nd task: fail guard
        self.assertIn("ansible.builtin.fail", abort_task)
        self.assertIn("abort", abort_task["when"])

    def test_unresolvable_row_produces_no_tasks(self) -> None:
        plays = self._build([{"id": "UNKNOWN-999", "status": "failed"}])
        self.assertEqual(plays[0]["tasks"], [])

    def test_v_format_id_resolved_via_group_id_map(self) -> None:
        row = {"id": "V-256375", "rule_id": "V-256375", "status": "failed"}
        plays = self._build([row])
        # V-256375 → ESXI-70-000001
        apply_task = plays[0]["tasks"][2]
        self.assertTrue(apply_task["vars"]["esxi_70_000001_Manage"])


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

    def test_dry_run_prints_generated_playbook(self) -> None:
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
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("DRY-RUN", result.output)
        # Generated YAML should contain the rule's manage var and the esxi host
        self.assertIn("esxi_70_000001_Manage", result.output)
        self.assertIn("esxi_stig_target_hosts", result.output)
        self.assertIn("esxi-01.local", result.output)
        # Generated YAML should include the apply role task
        self.assertIn("internal.vmware.esxi", result.output)

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
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        # V-256375 maps to ESXI-70-000001 via the skeleton group_id map
        self.assertIn("esxi_70_000001_Manage", result.output)
        self.assertNotIn("Could not determine rule_version", result.output)

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

    def _write_config_var_artifact(self, tmp_dir: str) -> Path:
        """Artifact with a rule that requires esxi_stig_syslog_host (ESXI-70-000004)."""
        rows = [{
            "id": "V-256378",
            "rule_version": "ESXI-70-000004",
            "status": "failed",
            "severity": "medium",
            "title": "Syslog",
        }]
        artifact = Path(tmp_dir) / "raw_stig_esxi.yaml"
        data = {
            "metadata": {"host": "esxi-01", "audit_type": "stig_esxi", "timestamp": "2026-02-27T00:00:00Z"},
            "data": rows,
            "target_type": "esxi",
        }
        with open(artifact, "w") as f:
            yaml.dump(data, f)
        return artifact

    def test_config_var_warning_shown(self) -> None:
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_config_var_artifact(tmp)
            result = runner.invoke(
                main,
                ["stig-apply", str(artifact), "--limit", "vcenter1",
                 "--esxi-host", "esxi-01.local", "--skip-snapshot", "--dry-run"],
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertIn("esxi_stig_syslog_host", result.output)
        self.assertIn("Warning", result.output)

    def test_config_var_warning_suppressed_by_extra_vars(self) -> None:
        from click.testing import CliRunner
        from ncs_reporter.cli import main

        runner = CliRunner()
        with tempfile.TemporaryDirectory() as tmp:
            artifact = self._write_config_var_artifact(tmp)
            result = runner.invoke(
                main,
                ["stig-apply", str(artifact), "--limit", "vcenter1",
                 "--esxi-host", "esxi-01.local", "--skip-snapshot", "--dry-run",
                 "-e", "esxi_stig_syslog_host=syslog.site1.local"],
            )
        self.assertEqual(result.exit_code, 0, f"CLI output:\n{result.output}")
        self.assertNotIn("Warning", result.output)

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
