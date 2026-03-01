"""Validate that example data bundles stay in sync with production assemble YAML contracts.

Each test compares the keys present in the example bundle's ``data`` dict against
the keys parsed from the real platform assemble/audit/discover task files.  A
failure here means a playbook added a new key to its set_fact and the example
fixture was not updated to match.
"""

from __future__ import annotations

import pytest

from fixtures._assemble_contracts import LINUX_DATA_KEYS, VCENTER_DATA_KEYS, WINDOWS_DATA_KEYS
from fixtures.example_data import make_linux_bundle, make_vcenter_bundle, make_windows_bundle


@pytest.mark.parametrize("unhealthy", [True, False])
def test_vcenter_bundle_has_all_assemble_keys(unhealthy: bool) -> None:
    bundle = make_vcenter_bundle("test-vc", unhealthy=unhealthy)
    data = bundle["vmware_raw_vcenter"]["data"]
    missing = VCENTER_DATA_KEYS - set(data.keys())
    assert not missing, f"vcenter example bundle missing keys from assemble.yaml: {missing}"


@pytest.mark.parametrize("unhealthy", [True, False])
def test_linux_bundle_has_all_assemble_keys(unhealthy: bool) -> None:
    bundle = make_linux_bundle("test-host", "10.0.0.1", unhealthy=unhealthy)
    data = bundle["ubuntu_raw_discovery"]["data"]
    missing = LINUX_DATA_KEYS - set(data.keys())
    assert not missing, f"linux example bundle missing keys from discover.yaml: {missing}"


@pytest.mark.parametrize("unhealthy", [True, False])
def test_windows_bundle_has_all_assemble_keys(unhealthy: bool) -> None:
    bundle = make_windows_bundle("test-win", unhealthy=unhealthy)
    data = bundle["windows_raw_audit"]["data"]
    missing = WINDOWS_DATA_KEYS - set(data.keys())
    assert not missing, f"windows example bundle missing keys from audit.yaml: {missing}"


def test_contract_sets_are_nonempty() -> None:
    """Guard against silent YAML parse failures returning empty sets."""
    assert VCENTER_DATA_KEYS, "VCENTER_DATA_KEYS parsed to empty set — check assemble.yaml path"
    assert LINUX_DATA_KEYS, "LINUX_DATA_KEYS parsed to empty set — check discover.yaml path"
    assert WINDOWS_DATA_KEYS, "WINDOWS_DATA_KEYS parsed to empty set — check audit.yaml path"
