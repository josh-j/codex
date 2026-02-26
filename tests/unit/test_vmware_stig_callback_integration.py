"""Wired integration tests: real callback plugin -> JSON artifact -> normalize.

Instantiates the real callback, feeds it FakeResult objects with real VMware
rule IDs, reads the written JSON, and passes it through normalize_stig_results.
"""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Fake Ansible types (same as test_stig_callback.py)
# ---------------------------------------------------------------------------


@dataclass
class FakeHost:
    name: str = "localhost"

    def get_name(self) -> str:
        return self.name


@dataclass
class FakeTask:
    _name: str = ""
    check_mode: bool = False
    vars: dict[str, Any] = field(default_factory=dict)

    def get_name(self) -> str:
        return self._name


@dataclass
class FakeResult:
    _host: FakeHost = field(default_factory=FakeHost)
    _task: FakeTask = field(default_factory=FakeTask)
    _result: dict[str, Any] = field(default_factory=dict)

    def is_changed(self) -> bool:
        return bool(self._result.get("changed", False))


# ---------------------------------------------------------------------------
# Module loaders
# ---------------------------------------------------------------------------

CALLBACK_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "callback"
    / "stig_xml.py"
)

STIG_FILTER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "stig.py"
)


class _StubCallbackBase:
    def __init__(self) -> None:
        pass


def _load_callback(artifact_dir: str) -> Any:
    fake_cb_module = type(sys)("ansible.plugins.callback")
    fake_cb_module.CallbackBase = _StubCallbackBase  # type: ignore[attr-defined]

    saved: dict[str, Any] = {}
    for key in ("ansible", "ansible.plugins", "ansible.plugins.callback"):
        saved[key] = sys.modules.get(key)

    sys.modules["ansible"] = type(sys)("ansible")
    sys.modules["ansible.plugins"] = type(sys)("ansible.plugins")
    sys.modules["ansible.plugins.callback"] = fake_cb_module

    old_env = os.environ.get("ARTIFACT_DIR")
    os.environ["ARTIFACT_DIR"] = artifact_dir

    try:
        spec = importlib.util.spec_from_file_location("stig_xml_integ", CALLBACK_PATH)
        assert spec and spec.loader
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod
    finally:
        os.environ.pop("ARTIFACT_DIR", None)
        if old_env is not None:
            os.environ["ARTIFACT_DIR"] = old_env
        for key, val in saved.items():
            if val is None:
                sys.modules.pop(key, None)
            else:
                sys.modules[key] = val


def _load_stig_filter() -> Any:
    spec = importlib.util.spec_from_file_location("core_stig_filter", STIG_FILTER_PATH)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _make_cb(artifact_dir: str) -> Any:
    mod = _load_callback(artifact_dir)
    os.environ["ARTIFACT_DIR"] = artifact_dir
    cb = mod.CallbackModule()
    os.environ.pop("ARTIFACT_DIR", None)
    return cb


def _read_json(artifact_dir: str, host: str) -> list[dict[str, Any]]:
    path = os.path.join(artifact_dir, f"xccdf-results_{host}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


# ===========================================================================
# Integration tests
# ===========================================================================


class TestCallbackJsonFeedsNormalize(unittest.TestCase):
    """5 FakeResults for an ESXi host -> JSON -> normalize -> correct summary."""

    tmpdir: str
    cb: Any
    stig: Any
    artifact: list[dict[str, Any]]
    normalized: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb = _make_cb(cls.tmpdir)
        cls.stig = _load_stig_filter()

        # Feed 5 results: 3 pass, 1 fail (changed in check), 1 na (skipped)
        rules = [
            ("stigrule_256376_dcui_access", False, False),
            ("stigrule_256378_syslog", False, False),
            ("stigrule_256379_account_lock", False, False),
            ("stigrule_256397_password_complexity", True, False),
            ("stigrule_256399_mob_disabled", False, True),
        ]
        for task_name, changed, skipped in rules:
            r = FakeResult(
                _host=FakeHost("esxi-prod-01"),
                _task=FakeTask(task_name, check_mode=True),
                _result={"changed": changed, "check_mode": True, "skipped": skipped},
            )
            cls.cb.v2_runner_on_ok(r)

        cls.artifact = _read_json(cls.tmpdir, "esxi-prod-01")
        cls.normalized = cls.stig.normalize_stig_results(cls.artifact, "esxi")

    def test_artifact_has_5_rows(self) -> None:
        self.assertEqual(len(self.artifact), 5)

    def test_summary_total(self) -> None:
        self.assertEqual(self.normalized["summary"]["total"], 5)

    def test_summary_violations(self) -> None:
        self.assertEqual(self.normalized["summary"]["violations"], 1)

    def test_summary_passed(self) -> None:
        self.assertEqual(self.normalized["summary"]["passed"], 3)

    def test_critical_count(self) -> None:
        self.assertEqual(self.normalized["summary"]["critical_count"], 0)
        self.assertEqual(self.normalized["summary"]["warning_count"], 1)


class TestHostAttributionFlowsToJson(unittest.TestCase):
    """stig_target_host override appears in JSON 'name' field and normalizes correctly."""

    tmpdir: str
    cb: Any
    stig: Any
    artifact: list[dict[str, Any]]
    normalized: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb = _make_cb(cls.tmpdir)
        cls.stig = _load_stig_filter()

        r = FakeResult(
            _host=FakeHost("localhost"),
            _task=FakeTask(
                "stigrule_256376_dcui_access",
                vars={"stig_target_host": "esxi-remote-05"},
            ),
            _result={"changed": False},
        )
        cls.cb.v2_runner_on_ok(r)

        cls.artifact = _read_json(cls.tmpdir, "esxi-remote-05")
        cls.normalized = cls.stig.normalize_stig_results(cls.artifact, "esxi")

    def test_json_name_field(self) -> None:
        self.assertEqual(self.artifact[0]["name"], "esxi-remote-05")

    def test_normalize_succeeds(self) -> None:
        self.assertEqual(self.normalized["summary"]["total"], 1)
        self.assertEqual(self.normalized["summary"]["passed"], 1)

    def test_no_localhost_artifact(self) -> None:
        path = os.path.join(self.tmpdir, "xccdf-results_localhost.json")
        self.assertFalse(os.path.exists(path))


class TestRemediationFixedThenNormalize(unittest.TestCase):
    """Changed results in apply mode -> 'fixed' in JSON -> normalizes to 'pass'."""

    tmpdir: str
    cb: Any
    stig: Any
    artifact: list[dict[str, Any]]
    normalized: dict[str, Any]

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb = _make_cb(cls.tmpdir)
        cls.stig = _load_stig_filter()

        rules = [
            ("stigrule_256376_dcui_access", True),
            ("stigrule_256378_syslog", False),
            ("stigrule_256397_password_complexity", True),
        ]
        for task_name, changed in rules:
            r = FakeResult(
                _host=FakeHost("esxi-remediate-01"),
                _task=FakeTask(task_name, check_mode=False),
                _result={"changed": changed},
            )
            cls.cb.v2_runner_on_ok(r)

        cls.artifact = _read_json(cls.tmpdir, "esxi-remediate-01")
        cls.normalized = cls.stig.normalize_stig_results(cls.artifact, "esxi")

    def test_fixed_in_artifact(self) -> None:
        statuses = {r["id"]: r["status"] for r in self.artifact}
        self.assertEqual(statuses["V-256376"], "fixed")
        self.assertEqual(statuses["V-256397"], "fixed")
        self.assertEqual(statuses["V-256378"], "pass")

    def test_fixed_normalizes_to_pass(self) -> None:
        self.assertEqual(self.normalized["summary"]["passed"], 3)
        self.assertEqual(self.normalized["summary"]["violations"], 0)

    def test_no_alerts(self) -> None:
        self.assertEqual(len(self.normalized["alerts"]), 0)


if __name__ == "__main__":
    unittest.main()
