"""Test harness: point schema discovery at the orchestrator + every
built-in collection's ncs_configs/ncs-reporter/ tree.

The reporter's discover_schemas() reads NCS_REPORTER_CONFIG_DIR as a
colon-separated list of dirs; feeding it every collection's config
dir is equivalent to the production setup, where the orchestrator's
config.yaml lists the collections as extra_config_dirs.
"""

from __future__ import annotations

import os
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
_ORCH_DIR = REPO_ROOT / "ncs-ansible" / "ncs_configs" / "ncs-reporter"
_COLLECTION_DIRS = sorted(REPO_ROOT.glob("ncs-ansible-*/ncs_configs/ncs-reporter"))
_ALL_DIRS: list[Path] = [_ORCH_DIR, *_COLLECTION_DIRS]
os.environ.setdefault(
    "NCS_REPORTER_CONFIG_DIR",
    os.pathsep.join(str(d) for d in _ALL_DIRS if d.is_dir()),
)


class _MultiDirLookup:
    """Sentinel that resolves ``<sentinel> / "<name>.yaml"`` to the first
    existing match across the orchestrator + every sibling collection's
    ncs_configs/ncs-reporter/ dir. Keeps the ergonomic ``CONFIGS_DIR / name``
    idiom working after schemas were split into per-collection dirs.
    """

    def __init__(self, dirs: list[Path]) -> None:
        self._dirs = dirs

    def __truediv__(self, name: str) -> Path:
        for d in self._dirs:
            candidate = d / name
            if candidate.exists():
                return candidate
        return self._dirs[0] / name

    def __fspath__(self) -> str:
        return str(self._dirs[0])

    def __str__(self) -> str:
        return str(self._dirs[0])


CONFIGS_DIR = _MultiDirLookup(_ALL_DIRS)
