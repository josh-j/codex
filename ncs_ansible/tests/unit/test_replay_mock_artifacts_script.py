"""Unit tests for scripts/replay_mock_artifacts_via_ansible.py."""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


SCRIPT_PATH = Path(__file__).resolve().parents[2] / "scripts" / "replay_mock_artifacts_via_ansible.py"
SPEC = importlib.util.spec_from_file_location("replay_mock_artifacts_via_ansible", SCRIPT_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC is not None and SPEC.loader is not None
SPEC.loader.exec_module(MODULE)


def _write_raw_fixture(root: Path, platform: str, host: str, name: str) -> Path:
    raw = root / "platform" / platform / host / f"raw_{name}.yaml"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text(yaml.safe_dump({"metadata": {"host": host}, "data": {"ok": True}}, sort_keys=False), encoding="utf-8")
    return raw


class TestReplayMockArtifactsScript(unittest.TestCase):
    def test_cli_accepts_omitted_inventory(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_raw_fixture(root, "linux/ubuntu", "host-a.local", "discovery")
            out_root = root / "out"
            out_root.mkdir(parents=True, exist_ok=True)

            with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "replay_mock_artifacts_via_ansible.py",
                        "--fixture-root",
                        str(root),
                        "--out-root",
                        str(out_root),
                    ],
                ):
                    rc = MODULE.main()
            self.assertEqual(rc, 0)

    def test_cli_accepts_inventory_and_warns(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_raw_fixture(root, "linux/ubuntu", "host-a.local", "discovery")
            out_root = root / "out"
            out_root.mkdir(parents=True, exist_ok=True)
            buf = io.StringIO()

            with patch.object(MODULE.subprocess, "run", return_value=SimpleNamespace(returncode=0)):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "replay_mock_artifacts_via_ansible.py",
                        "--inventory",
                        "inventory/production/hosts.yaml",
                        "--fixture-root",
                        str(root),
                        "--out-root",
                        str(out_root),
                    ],
                ):
                    with redirect_stdout(buf):
                        rc = MODULE.main()
            self.assertEqual(rc, 0)
            self.assertIn("--inventory is currently ignored", buf.getvalue())

    def test_no_raw_files_fails_cleanly(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            out_root = root / "out"
            out_root.mkdir(parents=True, exist_ok=True)
            buf = io.StringIO()

            with patch.object(
                sys,
                "argv",
                [
                    "replay_mock_artifacts_via_ansible.py",
                    "--fixture-root",
                    str(root),
                    "--out-root",
                    str(out_root),
                ],
            ):
                with redirect_stdout(buf):
                    rc = MODULE.main()
            self.assertEqual(rc, 1)
            self.assertIn("No raw artifacts found", buf.getvalue())

    def test_temp_inventory_host_derivation(self) -> None:
        inv_path = MODULE._write_temp_inventory({"host-b.local", "host-a.local"})  # noqa: SLF001
        try:
            data = yaml.safe_load(Path(inv_path).read_text(encoding="utf-8"))
        finally:
            Path(inv_path).unlink(missing_ok=True)
        self.assertEqual(sorted(data["all"]["hosts"].keys()), ["host-a.local", "host-b.local"])
        self.assertEqual(data["all"]["hosts"]["host-a.local"]["ansible_connection"], "local")

    def test_command_construction_contains_expected_args(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _write_raw_fixture(root, "vmware/vcenter/vcsa", "vc-site1.local", "stig_vcsa")
            out_root = root / "out"
            out_root.mkdir(parents=True, exist_ok=True)

            seen: list[list[str]] = []

            def _fake_run(cmd: list[str], check: bool = False) -> SimpleNamespace:  # noqa: ARG001
                seen.append(cmd)
                return SimpleNamespace(returncode=0)

            with patch.object(MODULE.subprocess, "run", side_effect=_fake_run):
                with patch.object(
                    sys,
                    "argv",
                    [
                        "replay_mock_artifacts_via_ansible.py",
                        "--fixture-root",
                        str(root),
                        "--out-root",
                        str(out_root),
                        "--ansible-playbook",
                        "ansible-playbook",
                        "--playbook",
                        str(Path("playbooks") / "simulated_emit_one_raw.yml"),
                    ],
                ):
                    rc = MODULE.main()

            self.assertEqual(rc, 0)
            self.assertEqual(len(seen), 1)
            cmd = seen[0]
            self.assertIn("-i", cmd)
            self.assertIn("-l", cmd)
            self.assertIn("vc-site1.local", cmd)
            self.assertIn("emit_platform=vmware/vcenter/vcsa", cmd)
            self.assertIn("emit_name=stig_vcsa", cmd)
            self.assertTrue(any(token.startswith("emit_payload_file=") for token in cmd))
            self.assertIn(f"emit_report_directory={out_root.resolve()}", cmd)

            inv_path = Path(cmd[cmd.index("-i") + 1])
            self.assertEqual(inv_path.suffix, ".yaml")
            self.assertIn("ncs_sim_inv_", inv_path.name)


if __name__ == "__main__":
    unittest.main()
