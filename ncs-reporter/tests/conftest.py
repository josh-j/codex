"""Test harness: point schema discovery at the sibling ncs_configs/ tree."""

from __future__ import annotations

import os
from pathlib import Path

CONFIGS_DIR = Path(__file__).parent.parent.parent / "ncs-ansible" / "ncs_configs" / "ncs-reporter"
os.environ.setdefault("NCS_REPORTER_CONFIG_DIR", str(CONFIGS_DIR))
