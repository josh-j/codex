"""Shared fixtures for ncs_ansible integration tests."""

from __future__ import annotations

from pathlib import Path

import pytest

from _paths import COLLECTIONS_INTERNAL, PLAYBOOKS_DIR, PLATFORMS_YAML, SCHEMAS_DIR


def _minimal_envelope(raw_type: str) -> dict:
    return {
        "metadata": {
            "host": "test-host",
            "raw_type": raw_type,
            "timestamp": "2026-03-01T00:00:00Z",
            "engine": "ncs_collector_callback",
        },
        "data": {},
    }


@pytest.fixture()
def schemas_dir() -> Path:
    return SCHEMAS_DIR


@pytest.fixture()
def platforms_yaml() -> Path:
    return PLATFORMS_YAML


@pytest.fixture()
def linux_bundle() -> dict:
    return {"ubuntu_raw_discovery": _minimal_envelope("ubuntu_raw_discovery")}


@pytest.fixture()
def vcenter_bundle() -> dict:
    return {"vmware_raw_vcenter": _minimal_envelope("vmware_raw_vcenter")}


@pytest.fixture()
def windows_bundle() -> dict:
    return {"windows_raw_audit": _minimal_envelope("windows_raw_audit")}
