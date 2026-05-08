"""Regression tests for the rule-number extraction in ncs_collector.

The synthetic ``9XXXXX`` IDs that were appearing in raw_stig_vcsa.yaml
(``V-988213``, ``V-961529``, ``V-981793``, ...) came from a SHA1-derived
fallback in ``_record_result`` that fabricated rule numbers for vcsa/vcenter
target_types when no real ``rule_num`` could be extracted from the task name
or result data. The fabricator is now gone — orchestrator-internal
housekeeping tasks ("Phase 0 | Register target context for ncs_collector",
"Load VCSA profile vars", etc.) fall through to the ``if not rule_num:
return`` gate and are correctly skipped.

These tests load the source-tree ncs_collector.py directly via
``importlib.util.spec_from_file_location`` so they don't depend on the
``internal.core.*`` namespace package being importable.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

_NCS_COLLECTOR_PATH = (
    Path(__file__).resolve().parent.parent / "plugins" / "callback" / "ncs_collector.py"
)


@pytest.fixture(scope="module")
def cb():
    # Stub ``ansible.plugins.callback.CallbackBase`` so the import can succeed
    # without ansible-core being on sys.path.
    if "ansible" not in sys.modules:
        ansible_mod = types.ModuleType("ansible")
        plugins_mod = types.ModuleType("ansible.plugins")
        callback_mod = types.ModuleType("ansible.plugins.callback")

        class _CallbackBase:
            pass

        callback_mod.CallbackBase = _CallbackBase
        plugins_mod.callback = callback_mod
        ansible_mod.plugins = plugins_mod
        sys.modules["ansible"] = ansible_mod
        sys.modules["ansible.plugins"] = plugins_mod
        sys.modules["ansible.plugins.callback"] = callback_mod

    spec = importlib.util.spec_from_file_location(
        "ncs_collector_under_test", _NCS_COLLECTOR_PATH,
    )
    assert spec and spec.loader, "could not load ncs_collector.py"
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    # Bypass __init__: the rule-extraction methods don't touch self state, and
    # the real __init__ tries to load the platforms config + emit warnings via
    # self._display, neither of which the test stubs provide.
    return module.CallbackModule.__new__(module.CallbackModule)


def test_extract_rule_number_recognizes_stigrule_numeric_form(cb) -> None:
    assert cb._extract_rule_number("stigrule_270773") == "270773"
    assert cb._extract_rule_number("stigrule_270773a") == "270773"
    assert cb._extract_rule_number("stigrule_270773_b") == "270773"


def test_extract_rule_number_recognizes_v_dash_form(cb) -> None:
    assert cb._extract_rule_number("V-256318") == "256318"


def test_extract_rule_number_recognizes_prefix_year_id_form(cb) -> None:
    assert cb._extract_rule_number("stigrule_VCEM-70-000001") == "VCEM-70-000001"
    assert cb._extract_rule_number("stigrule_PHTN-30-000016") == "PHTN-30-000016"


def test_extract_rule_number_returns_none_for_housekeeping_task_names(cb) -> None:
    housekeeping = [
        "VCSA STIG | Phase 0 | Register target context for ncs_collector",
        "VCSA STIG | Phase 0 | Pre-run validations",
        "VCSA STIG | Phase 1 | Pre-phase tasks",
        "VCSA STIG | Load VCSA profile vars",
        "VCSA STIG | Optional Photon baseline",
        "VCSA STIG | Phase 1a | Run STIG tasks",
        "VCSA STIG | Phase 1a | Run STIG tasks (loop)",
        "Backup files...if restoring be sure to restore permissions",
        "Create time stamp",
        "EAM STIG | Discover current web log files",
    ]
    for name in housekeeping:
        assert cb._extract_rule_number(name) is None, f"unexpected ID for {name!r}"


def test_no_sha1_fabricator_left_in_module() -> None:
    src = _NCS_COLLECTOR_PATH.read_text(encoding="utf-8")
    assert "hashlib.sha1" not in src, (
        "SHA1-derived synthetic rule_num fabricator must not exist in "
        "ncs_collector.py — it was the source of the V-988213 / V-961529 / "
        "... synthetic IDs."
    )
    assert "import hashlib" not in src, (
        "Unused hashlib import — should have been removed alongside the "
        "synthetic-ID fabricator."
    )
