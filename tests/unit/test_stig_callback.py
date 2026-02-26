"""Unit tests for the stig_xml callback plugin."""

import importlib.util
import json
import os
import pathlib
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Fake Ansible types (plain dataclasses, not unittest.mock)
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
# Module loader — stubs ansible.plugins.callback.CallbackBase before import
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


class _StubCallbackBase:
    """Minimal stand-in for ansible.plugins.callback.CallbackBase."""

    def __init__(self) -> None:
        pass


def _load_callback(artifact_dir: str) -> Any:
    """Load the callback module with Ansible stubs and ARTIFACT_DIR set."""
    # Inject stub so `from ansible.plugins.callback import CallbackBase` resolves
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
        spec = importlib.util.spec_from_file_location("stig_xml_test", CALLBACK_PATH)
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


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_cb(artifact_dir: str) -> tuple[Any, Any]:
    mod = _load_callback(artifact_dir)
    os.environ["ARTIFACT_DIR"] = artifact_dir
    cb = mod.CallbackModule()
    os.environ.pop("ARTIFACT_DIR", None)
    return cb, mod


def _read_json(artifact_dir: str, host: str) -> list[dict[str, Any]]:
    path = os.path.join(artifact_dir, f"xccdf-results_{host}.json")
    with open(path, encoding="utf-8") as f:
        return json.load(f)  # type: ignore[no-any-return]


# ===========================================================================
# Test classes
# ===========================================================================


class TestExtractRuleNumber(unittest.TestCase):
    """Rule number regex works for all task naming conventions."""

    tmpdir: str
    cb: Any
    mod: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, cls.mod = _make_cb(cls.tmpdir)

    def _extract(self, text: Any) -> Any:
        return self.mod.CallbackModule._extract_rule_number(text)

    def test_stigrule_prefix(self) -> None:
        self.assertEqual(self._extract("stigrule_256376_dcui_access"), "256376")

    def test_v_prefix(self) -> None:
        self.assertEqual(self._extract("V-256376"), "256376")

    def test_sv_prefix(self) -> None:
        self.assertEqual(self._extract("SV-256376"), "256376")

    def test_r_prefix(self) -> None:
        self.assertEqual(self._extract("R-256376"), "256376")

    def test_bare_number(self) -> None:
        self.assertEqual(self._extract("256376"), "256376")

    def test_embedded_in_task_name(self) -> None:
        self.assertEqual(
            self._extract("stigrule_256378_syslog : Configure syslog"), "256378"
        )

    def test_rejects_short_numbers(self) -> None:
        self.assertIsNone(self._extract("rule_123"))

    def test_rejects_non_stig_task(self) -> None:
        self.assertIsNone(self._extract("Gather facts"))

    def test_none_input(self) -> None:
        self.assertIsNone(self._extract(None))

    def test_empty_string(self) -> None:
        self.assertIsNone(self._extract(""))


class TestAuditModeStatus(unittest.TestCase):
    """check_mode=True: changed->failed, unchanged->pass, skipped->na."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_changed_in_check_mode_is_failed(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui", check_mode=True),
            _result={"changed": True, "check_mode": True},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules["esxi1"]["256376"], "failed")

    def test_unchanged_in_check_mode_is_pass(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256378_syslog", check_mode=True),
            _result={"changed": False, "check_mode": True},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules["esxi1"]["256378"], "pass")

    def test_skipped_is_na(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256379_lock", check_mode=True),
            _result={"skipped": True, "check_mode": True},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules["esxi1"]["256379"], "na")


class TestRemediationModeStatus(unittest.TestCase):
    """check_mode=False: changed->fixed, unchanged->pass."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_changed_in_apply_mode_is_fixed(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": True},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules["esxi1"]["256376"], "fixed")

    def test_unchanged_in_apply_mode_is_pass(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256378_syslog"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules["esxi1"]["256378"], "pass")


class TestNeverDowngrade(unittest.TestCase):
    """Once a rule is 'failed', subsequent pass/fixed results do not overwrite it."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_pass_does_not_overwrite_failed(self) -> None:
        fail_result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui", check_mode=True),
            _result={"changed": True, "check_mode": True},
        )
        self.cb.v2_runner_on_ok(fail_result)
        self.assertEqual(self.cb.rules["esxi1"]["256376"], "failed")

        pass_result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui", check_mode=True),
            _result={"changed": False, "check_mode": True},
        )
        self.cb.v2_runner_on_ok(pass_result)
        self.assertEqual(self.cb.rules["esxi1"]["256376"], "failed")

    def test_fixed_does_not_overwrite_failed(self) -> None:
        self.cb.rules["esxi1"] = {"256376": "failed"}
        fix_result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": True},
        )
        self.cb.v2_runner_on_ok(fix_result)
        self.assertEqual(self.cb.rules["esxi1"]["256376"], "failed")


class TestHostAttribution(unittest.TestCase):
    """stig_target_host task var overrides result._host."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_target_host_override(self) -> None:
        result = FakeResult(
            _host=FakeHost("localhost"),
            _task=FakeTask(
                "stigrule_256376_dcui",
                vars={"stig_target_host": "esxi-remote-01"},
            ),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertIn("esxi-remote-01", self.cb.rules)
        self.assertNotIn("localhost", self.cb.rules)

    def test_no_override_uses_host(self) -> None:
        result = FakeResult(
            _host=FakeHost("real-host"),
            _task=FakeTask("stigrule_256378_syslog"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertIn("real-host", self.cb.rules)


class TestMultiHostTracking(unittest.TestCase):
    """Separate rule dicts per host; three ESXi hosts produce independent entries."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_three_hosts_independent(self) -> None:
        hosts = ["esxi-01", "esxi-02", "esxi-03"]
        for i, host in enumerate(hosts):
            result = FakeResult(
                _host=FakeHost("localhost"),
                _task=FakeTask(
                    "stigrule_256376_dcui",
                    check_mode=True,
                    vars={"stig_target_host": host},
                ),
                _result={
                    "changed": i == 0,
                    "check_mode": True,
                },
            )
            self.cb.v2_runner_on_ok(result)

        self.assertEqual(len(self.cb.rules), 3)
        self.assertEqual(self.cb.rules["esxi-01"]["256376"], "failed")
        self.assertEqual(self.cb.rules["esxi-02"]["256376"], "pass")
        self.assertEqual(self.cb.rules["esxi-03"]["256376"], "pass")


class TestJsonArtifactOutput(unittest.TestCase):
    """JSON file created with correct structure and required keys."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_json_file_created(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)

        data = _read_json(self.tmpdir, "esxi1")
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_required_keys_present(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)

        row = _read_json(self.tmpdir, "esxi1")[0]
        required = {"id", "rule_id", "name", "status", "title", "severity", "fixtext", "checktext"}
        self.assertTrue(required.issubset(row.keys()), f"Missing keys: {required - row.keys()}")

    def test_json_updates_incrementally(self) -> None:
        for rule in ["256376", "256378", "256379"]:
            result = FakeResult(
                _host=FakeHost("esxi1"),
                _task=FakeTask(f"stigrule_{rule}_check"),
                _result={"changed": False},
            )
            self.cb.v2_runner_on_ok(result)

        data = _read_json(self.tmpdir, "esxi1")
        self.assertEqual(len(data), 3)

    def test_name_field_is_host(self) -> None:
        result = FakeResult(
            _host=FakeHost("localhost"),
            _task=FakeTask(
                "stigrule_256376_dcui",
                vars={"stig_target_host": "esxi-target"},
            ),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)

        row = _read_json(self.tmpdir, "esxi-target")[0]
        self.assertEqual(row["name"], "esxi-target")


class TestEnsureRuleDetails(unittest.TestCase):
    """Populates minimal metadata without STIG XML; does not overwrite existing."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_creates_minimal_details(self) -> None:
        self.cb._ensure_rule_details("256376", "stigrule_256376_dcui_access")
        d = self.cb.rule_details["256376"]
        self.assertEqual(d["full_id"], "V-256376")
        self.assertEqual(d["title"], "stigrule_256376_dcui_access")
        self.assertEqual(d["severity"], "medium")

    def test_does_not_overwrite_existing(self) -> None:
        self.cb.rule_details["256376"] = {
            "full_id": "V-256376",
            "title": "Original Title",
            "severity": "high",
            "fixtext": "Fix it",
            "checktext": "Check it",
        }
        self.cb._ensure_rule_details("256376", "stigrule_256376_dcui_access")
        self.assertEqual(self.cb.rule_details["256376"]["title"], "Original Title")
        self.assertEqual(self.cb.rule_details["256376"]["severity"], "high")


class TestXmlOutput(unittest.TestCase):
    """XML written on v2_playbook_on_stats, contains rule-result elements."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()
        self.cb._xml_written.clear()

    def test_xml_written_on_stats(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.cb.v2_playbook_on_stats(None)

        xml_path = os.path.join(self.tmpdir, "xccdf-results_esxi1.xml")
        self.assertTrue(os.path.exists(xml_path))

        tree = ET.parse(xml_path)
        root = tree.getroot()
        rule_results = [e for e in root.iter() if e.tag.endswith("rule-result")]
        self.assertGreaterEqual(len(rule_results), 1)

    def test_xml_written_only_once(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)

        self.cb.v2_playbook_on_stats(None)
        xml_path = os.path.join(self.tmpdir, "xccdf-results_esxi1.xml")
        mtime1 = os.path.getmtime(xml_path)

        result2 = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256378_syslog"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result2)
        self.cb.v2_playbook_on_stats(None)
        mtime2 = os.path.getmtime(xml_path)

        self.assertEqual(mtime1, mtime2)


class TestDisabled(unittest.TestCase):
    """cb.disabled = True -> all hooks are no-ops."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()
        self.cb.disabled = True

    def tearDown(self) -> None:
        self.cb.disabled = False

    def test_on_ok_noop(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={"changed": True},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules, {})

    def test_on_failed_noop(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("stigrule_256376_dcui"),
            _result={},
        )
        self.cb.v2_runner_on_failed(result)
        self.assertEqual(self.cb.rules, {})

    def test_on_stats_noop(self) -> None:
        self.cb.rules["esxi1"] = {"256376": "pass"}
        self.cb.v2_playbook_on_stats(None)
        xml_path = os.path.join(self.tmpdir, "xccdf-results_esxi1.xml")
        self.assertFalse(os.path.exists(xml_path))


class TestNonStigTaskIgnored(unittest.TestCase):
    """Tasks without rule numbers produce no entries."""

    tmpdir: str
    cb: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.tmpdir = tempfile.mkdtemp()
        cls.cb, _ = _make_cb(cls.tmpdir)

    def setUp(self) -> None:
        self.cb.rules.clear()
        self.cb.rule_details.clear()

    def test_gather_facts_ignored(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("Gather facts"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules, {})

    def test_include_role_ignored(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("include_role : stig"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules, {})

    def test_set_fact_ignored(self) -> None:
        result = FakeResult(
            _host=FakeHost("esxi1"),
            _task=FakeTask("Set connection variables"),
            _result={"changed": False},
        )
        self.cb.v2_runner_on_ok(result)
        self.assertEqual(self.cb.rules, {})


if __name__ == "__main__":
    unittest.main()
