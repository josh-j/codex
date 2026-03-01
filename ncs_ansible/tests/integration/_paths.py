"""Shared path constants for integration tests."""

from __future__ import annotations

from pathlib import Path

NCS_ANSIBLE_ROOT = Path(__file__).resolve().parents[2]
SCHEMAS_DIR = NCS_ANSIBLE_ROOT / "files" / "ncs_reporter_configs"
PLATFORMS_YAML = SCHEMAS_DIR / "platforms.yaml"
CONFIG_YAML = SCHEMAS_DIR / "config.yaml"
PLAYBOOKS_DIR = NCS_ANSIBLE_ROOT / "playbooks"
COLLECTIONS_INTERNAL = NCS_ANSIBLE_ROOT / "collections" / "ansible_collections" / "internal"
