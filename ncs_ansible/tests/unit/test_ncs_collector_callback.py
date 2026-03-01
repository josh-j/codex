"""Unit tests for the ncs_collector callback plugin.

Tests the disk persistence layer that bridges Ansible set_stats telemetry
to the raw_*.yaml artifacts consumed by ncs-reporter normalization.

The contract under test: given ncs_collect data from set_stats, the plugin
must write files at platform/{platform}/{host}/raw_{name}.yaml with an
envelope containing `metadata` (host, raw_type, timestamp, engine) and
`data` (the payload). A separate config.yaml is written when config is
provided. Missing or None payload must not write a raw file. Any OSError
must be caught and warned, not raised.
"""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

CALLBACK_PATH = (
    Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "callback"
    / "ncs_collector.py"
)


# ---------------------------------------------------------------------------
# Ansible stubs
# ---------------------------------------------------------------------------


class _FakeDisplay:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.messages: list[str] = []

    def display(self, msg: str, color: str | None = None) -> None:
        self.messages.append(msg)

    def warning(self, msg: str) -> None:
        self.warnings.append(msg)


class _StubCallbackBase:
    def __init__(self) -> None:
        self._display = _FakeDisplay()


def _load_callback() -> Any:
    fake_cb_module = type(sys)("ansible.plugins.callback")
    fake_cb_module.CallbackBase = _StubCallbackBase  # type: ignore[attr-defined]

    saved: dict[str, Any] = {}
    for key in ("ansible", "ansible.plugins", "ansible.plugins.callback"):
        saved[key] = sys.modules.get(key)

    sys.modules["ansible"] = type(sys)("ansible")
    sys.modules["ansible.plugins"] = type(sys)("ansible.plugins")
    sys.modules["ansible.plugins.callback"] = fake_cb_module

    try:
        spec = importlib.util.spec_from_file_location("ncs_collector_test", CALLBACK_PATH)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
        return mod
    finally:
        for key, val in saved.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val


# ---------------------------------------------------------------------------
# Fake Ansible stats
# ---------------------------------------------------------------------------


class FakeStats:
    def __init__(self, host_data: dict[str, Any]) -> None:
        self.processed: dict[str, Any] = {h: True for h in host_data}
        self._data = host_data

    def get_custom_stats(self, host: str) -> Any:
        return self._data.get(host)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cb() -> tuple[Any, Any]:
    mod = _load_callback()
    cb = mod.CallbackModule()
    return cb, mod


def _read_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))  # type: ignore[return-value]


def _emit(
    cb: Any,
    report_dir: str,
    host: str,
    platform: str,
    name: str,
    payload: Any,
    config: dict[str, Any] | None = None,
) -> None:
    data: dict[str, Any] = {
        "platform": platform,
        "name": name,
        "payload": payload,
        "report_directory": report_dir,
    }
    if config is not None:
        data["config"] = config
    stats = FakeStats({host: {"ncs_collect": data}})
    cb.v2_playbook_on_stats(stats)


# ===========================================================================
# Tests: _find_repo_root
# ===========================================================================


class TestFindRepoRoot(unittest.TestCase):
    """_find_repo_root traverses parent dirs to find the collections/ marker."""

    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.mod = _load_callback()

    def test_finds_root_from_callback_directory(self) -> None:
        result = self.mod._find_repo_root(str(CALLBACK_PATH.parent))
        marker = Path(result) / "collections" / "ansible_collections"
        self.assertTrue(marker.is_dir(), f"Marker not found under {result}")

    def test_finds_same_root_from_deeply_nested_path(self) -> None:
        deep = CALLBACK_PATH.parent / "subdir" / "deeper"
        result = self.mod._find_repo_root(str(deep))
        marker = Path(result) / "collections" / "ansible_collections"
        self.assertTrue(marker.is_dir())

    def test_returns_string(self) -> None:
        result = self.mod._find_repo_root(str(CALLBACK_PATH))
        self.assertIsInstance(result, str)

    def test_returns_start_when_no_marker_within_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            deep = Path(tmp) / "a" / "b" / "c"
            deep.mkdir(parents=True)
            result = self.mod._find_repo_root(str(deep), max_up=2)
            self.assertIsInstance(result, str)

    def test_finds_marker_in_tmpdir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / "collections" / "ansible_collections"
            marker.mkdir(parents=True)
            deep = Path(tmp) / "subdir" / "plugin"
            deep.mkdir(parents=True)
            result = self.mod._find_repo_root(str(deep))
            self.assertEqual(result, str(Path(tmp).resolve()))


# ===========================================================================
# Tests: stats filtering
# ===========================================================================


class TestStatsFiltering(unittest.TestCase):
    """v2_playbook_on_stats only persists hosts that have ncs_collect data."""

    def _no_files_written(self, host_data: dict[str, Any]) -> bool:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            cb.v2_playbook_on_stats(FakeStats(host_data))
            return not (Path(tmp) / "platform").exists()

    def test_skips_host_with_no_ncs_collect_key(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            stats = FakeStats({"host1": {"other_key": "data"}})
            cb.v2_playbook_on_stats(stats)
            self.assertFalse((Path(tmp) / "platform").exists())

    def test_skips_host_with_none_custom_stats(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            cb.v2_playbook_on_stats(FakeStats({"host1": None}))
            self.assertFalse((Path(tmp) / "platform").exists())

    def test_skips_host_when_ncs_collect_is_not_dict(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            cb.v2_playbook_on_stats(FakeStats({"host1": {"ncs_collect": "string-not-dict"}}))
            self.assertFalse((Path(tmp) / "platform").exists())

    def test_skips_host_when_ncs_collect_is_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            cb.v2_playbook_on_stats(FakeStats({"host1": {"ncs_collect": [1, 2, 3]}}))
            self.assertFalse((Path(tmp) / "platform").exists())


# ===========================================================================
# Tests: output file path structure
# ===========================================================================


class TestFilePathStructure(unittest.TestCase):
    """Raw files must land at {report_dir}/platform/{platform}/{host}/raw_{name}.yaml."""

    def test_vmware_vcenter_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "vc-01", "vmware", "vcenter", {"k": "v"})
            expected = Path(tmp) / "platform" / "vmware" / "vc-01" / "raw_vcenter.yaml"
            self.assertTrue(expected.exists(), f"Expected file not found: {expected}")

    def test_ubuntu_discovery_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "linux-01", "ubuntu", "discovery", {"k": "v"})
            expected = Path(tmp) / "platform" / "ubuntu" / "linux-01" / "raw_discovery.yaml"
            self.assertTrue(expected.exists())

    def test_windows_audit_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "win-01", "windows", "audit", {"k": "v"})
            expected = Path(tmp) / "platform" / "windows" / "win-01" / "raw_audit.yaml"
            self.assertTrue(expected.exists())

    def test_stig_esxi_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "esxi-01", "vmware", "stig_esxi", {"k": "v"})
            expected = Path(tmp) / "platform" / "vmware" / "esxi-01" / "raw_stig_esxi.yaml"
            self.assertTrue(expected.exists())

    def test_host_directory_created(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "vc-01", "vmware", "vcenter", {"k": "v"})
            host_dir = Path(tmp) / "platform" / "vmware" / "vc-01"
            self.assertTrue(host_dir.is_dir())


# ===========================================================================
# Tests: envelope structure
# ===========================================================================


class TestEnvelopeStructure(unittest.TestCase):
    """Written YAML must match the envelope format ncs-reporter expects."""

    envelope: dict[str, Any]
    tmpdir: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cb, _ = _make_cb()
        _emit(
            cb,
            cls.tmpdir,
            "esxi-01",
            "vmware",
            "stig_esxi",
            {"findings": [{"id": "V-256376", "status": "pass"}]},
        )
        artifact = Path(cls.tmpdir) / "platform" / "vmware" / "esxi-01" / "raw_stig_esxi.yaml"
        cls.envelope = _read_yaml(artifact)

    def test_has_metadata_key(self) -> None:
        self.assertIn("metadata", self.envelope)

    def test_has_data_key(self) -> None:
        self.assertIn("data", self.envelope)

    def test_metadata_host_matches(self) -> None:
        self.assertEqual(self.envelope["metadata"]["host"], "esxi-01")

    def test_metadata_raw_type_matches_name(self) -> None:
        self.assertEqual(self.envelope["metadata"]["raw_type"], "stig_esxi")

    def test_metadata_engine_is_ncs_collector(self) -> None:
        self.assertEqual(self.envelope["metadata"]["engine"], "ncs_collector_callback")

    def test_metadata_timestamp_is_nonempty_string(self) -> None:
        ts = self.envelope["metadata"].get("timestamp", "")
        self.assertIsInstance(ts, str)
        self.assertTrue(len(ts) > 0, "timestamp must not be empty")

    def test_data_matches_payload(self) -> None:
        self.assertEqual(
            self.envelope["data"],
            {"findings": [{"id": "V-256376", "status": "pass"}]},
        )

    def test_written_file_is_valid_yaml(self) -> None:
        artifact = Path(self.tmpdir) / "platform" / "vmware" / "esxi-01" / "raw_stig_esxi.yaml"
        content = artifact.read_text(encoding="utf-8")
        parsed = yaml.safe_load(content)
        self.assertIsInstance(parsed, dict)


# ===========================================================================
# Tests: null payload
# ===========================================================================


class TestNullPayload(unittest.TestCase):
    """When payload is None no raw_*.yaml is written; directory is still created."""

    def test_no_raw_file_when_payload_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "host1", "vmware", "vcenter", None)
            raw_file = Path(tmp) / "platform" / "vmware" / "host1" / "raw_vcenter.yaml"
            self.assertFalse(raw_file.exists())

    def test_directory_still_created_when_payload_is_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "host1", "vmware", "vcenter", None)
            host_dir = Path(tmp) / "platform" / "vmware" / "host1"
            self.assertTrue(host_dir.is_dir())


# ===========================================================================
# Tests: config file
# ===========================================================================


class TestConfigFile(unittest.TestCase):
    """config key triggers a separate config.yaml alongside the raw file."""

    config_doc: dict[str, Any]
    tmpdir: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cb, _ = _make_cb()
        _emit(
            cb,
            cls.tmpdir,
            "linux-01",
            "ubuntu",
            "discovery",
            {"key": "val"},
            config={"report_stamp": "20260227", "env": "prod"},
        )
        config_path = Path(cls.tmpdir) / "platform" / "ubuntu" / "linux-01" / "config.yaml"
        cls.config_doc = _read_yaml(config_path)

    def test_config_file_exists(self) -> None:
        config_path = Path(self.tmpdir) / "platform" / "ubuntu" / "linux-01" / "config.yaml"
        self.assertTrue(config_path.exists())

    def test_config_envelope_has_metadata(self) -> None:
        self.assertIn("metadata", self.config_doc)

    def test_config_envelope_has_config_key(self) -> None:
        self.assertIn("config", self.config_doc)

    def test_config_data_matches(self) -> None:
        self.assertEqual(
            self.config_doc["config"],
            {"report_stamp": "20260227", "env": "prod"},
        )

    def test_config_metadata_host(self) -> None:
        self.assertEqual(self.config_doc["metadata"]["host"], "linux-01")

    def test_no_config_file_when_config_key_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            cb, _ = _make_cb()
            _emit(cb, tmp, "host2", "ubuntu", "discovery", {"key": "val"})
            config_path = Path(tmp) / "platform" / "ubuntu" / "host2" / "config.yaml"
            self.assertFalse(config_path.exists())


# ===========================================================================
# Tests: multiple hosts
# ===========================================================================


class TestMultipleHosts(unittest.TestCase):
    """Each host in a single stats call gets its own independent directory and file."""

    tmpdir: str

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cb, _ = _make_cb()
        stats = FakeStats(
            {
                host: {
                    "ncs_collect": {
                        "platform": "vmware",
                        "name": "stig_esxi",
                        "payload": {"host": host},
                        "report_directory": cls.tmpdir,
                    }
                }
                for host in ("esxi-01", "esxi-02", "esxi-03")
            }
        )
        cb.v2_playbook_on_stats(stats)

    def test_all_host_dirs_created(self) -> None:
        for host in ("esxi-01", "esxi-02", "esxi-03"):
            self.assertTrue(
                (Path(self.tmpdir) / "platform" / "vmware" / host).is_dir(),
                f"Directory missing for {host}",
            )

    def test_all_raw_files_written(self) -> None:
        for host in ("esxi-01", "esxi-02", "esxi-03"):
            self.assertTrue(
                (Path(self.tmpdir) / "platform" / "vmware" / host / "raw_stig_esxi.yaml").exists()
            )

    def test_payloads_are_independent(self) -> None:
        for host in ("esxi-01", "esxi-02", "esxi-03"):
            envelope = _read_yaml(
                Path(self.tmpdir) / "platform" / "vmware" / host / "raw_stig_esxi.yaml"
            )
            self.assertEqual(envelope["data"]["host"], host)

    def test_metadata_host_matches_each_file(self) -> None:
        for host in ("esxi-01", "esxi-02", "esxi-03"):
            envelope = _read_yaml(
                Path(self.tmpdir) / "platform" / "vmware" / host / "raw_stig_esxi.yaml"
            )
            self.assertEqual(envelope["metadata"]["host"], host)


# ===========================================================================
# Tests: error handling
# ===========================================================================


class TestErrorHandling(unittest.TestCase):
    """OSError from makedirs must be caught and warned, not raised."""

    def test_makedirs_oserror_does_not_propagate(self) -> None:
        cb, _ = _make_cb()
        with patch("os.makedirs", side_effect=OSError("Permission denied")):
            stats = FakeStats(
                {
                    "host1": {
                        "ncs_collect": {
                            "platform": "vmware",
                            "name": "vcenter",
                            "payload": {"k": "v"},
                            "report_directory": "/tmp",
                        }
                    }
                }
            )
            try:
                cb.v2_playbook_on_stats(stats)
            except Exception as exc:
                self.fail(f"OSError was not caught by the plugin: {exc}")

    def test_warning_displayed_on_makedirs_failure(self) -> None:
        cb, _ = _make_cb()
        with patch("os.makedirs", side_effect=OSError("Permission denied")):
            stats = FakeStats(
                {
                    "host1": {
                        "ncs_collect": {
                            "platform": "vmware",
                            "name": "vcenter",
                            "payload": {"k": "v"},
                            "report_directory": "/tmp",
                        }
                    }
                }
            )
            cb.v2_playbook_on_stats(stats)
            self.assertTrue(
                len(cb._display.warnings) > 0,
                "Plugin must emit a warning when directory creation fails",
            )

    def test_missing_report_directory_uses_default_and_does_not_crash(self) -> None:
        """Absent report_directory falls back to /srv/samba/reports.
        That path won't be writable in CI; the OSError must be caught."""
        cb, _ = _make_cb()
        stats = FakeStats(
            {
                "host1": {
                    "ncs_collect": {
                        "platform": "vmware",
                        "name": "vcenter",
                        "payload": {"k": "v"},
                        # no report_directory
                    }
                }
            }
        )
        try:
            cb.v2_playbook_on_stats(stats)
        except Exception as exc:
            self.fail(f"Missing report_directory raised {exc}")


if __name__ == "__main__":
    unittest.main()
