"""Shared fixtures for ansible-runner integration tests."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
PLAYBOOKS_DIR = Path(__file__).resolve().parent / "playbooks"
FIXTURES_DIR = Path(__file__).resolve().parent / "fixtures"
COLLECTIONS_DIR = REPO_ROOT / "collections"

FILTER_PLUGINS = ":".join(
    str(COLLECTIONS_DIR / "ansible_collections" / "internal" / ns / "plugins" / "filter")
    for ns in ("core", "linux", "vmware", "windows")
)
CALLBACK_PLUGINS = str(COLLECTIONS_DIR / "ansible_collections" / "internal" / "core" / "plugins" / "callback")
LOOKUP_PLUGINS = str(COLLECTIONS_DIR / "ansible_collections" / "internal" / "core" / "plugins" / "lookup")
MODULE_UTILS = str(COLLECTIONS_DIR / "ansible_collections" / "internal" / "core" / "plugins" / "module_utils")


def _load_fixture(name: str) -> Any:
    """Load a YAML or JSON fixture file from the fixtures directory."""
    path = FIXTURES_DIR / name
    raw = path.read_text()
    if name.endswith(".json"):
        return json.loads(raw)
    return yaml.safe_load(raw)


@pytest.fixture()
def load_fixture():
    """Return the fixture loader callable."""
    return _load_fixture


@pytest.fixture()
def run_playbook(tmp_path: Path):
    """Return a callable that runs a wrapper playbook via ansible-runner and returns the output JSON."""
    import ansible_runner

    def _run(playbook_name: str, extravars: dict[str, Any] | None = None) -> dict[str, Any]:
        private_data_dir = tmp_path / "runner"
        project_dir = private_data_dir / "project"
        project_dir.mkdir(parents=True, exist_ok=True)

        # Copy wrapper playbook into project dir
        src_playbook = PLAYBOOKS_DIR / playbook_name
        shutil.copy2(src_playbook, project_dir / playbook_name)

        # Output path for captured facts
        output_path = tmp_path / "results.json"

        ev = dict(extravars or {})
        ev["_output_path"] = str(output_path)
        ev["_collections_dir"] = str(COLLECTIONS_DIR)

        # Write a minimal ansible.cfg to avoid picking up repo's config (vault, inventory, etc.)
        ansible_cfg = project_dir / "ansible.cfg"
        ansible_cfg.write_text(
            f"[defaults]\n"
            f"collections_path = {COLLECTIONS_DIR}\n"
            f"collections_paths = {COLLECTIONS_DIR}\n"
            f"filter_plugins = {FILTER_PLUGINS}\n"
            f"callback_plugins = {CALLBACK_PLUGINS}\n"
            f"lookup_plugins = {LOOKUP_PLUGINS}\n"
            f"host_key_checking = False\n"
        )

        envvars = {
            "ANSIBLE_CONFIG": str(ansible_cfg),
            "ANSIBLE_COLLECTIONS_PATH": str(COLLECTIONS_DIR),
            "ANSIBLE_COLLECTIONS_PATHS": str(COLLECTIONS_DIR),
            "ANSIBLE_FILTER_PLUGINS": FILTER_PLUGINS,
            "ANSIBLE_CALLBACK_PLUGINS": CALLBACK_PLUGINS,
            "ANSIBLE_LOOKUP_PLUGINS": LOOKUP_PLUGINS,
            "ANSIBLE_MODULE_UTILS": MODULE_UTILS,
            "ANSIBLE_LOCALHOST_WARNING": "false",
            "ANSIBLE_HOST_KEY_CHECKING": "false",
        }

        r = ansible_runner.run(
            private_data_dir=str(private_data_dir),
            playbook=playbook_name,
            extravars=ev,
            envvars=envvars,
            quiet=True,
        )

        if r.status != "successful":
            stdout = r.stdout.read() if r.stdout else ""  # type: ignore[union-attr]
            raise RuntimeError(
                f"Playbook {playbook_name} failed (status={r.status}, rc={r.rc}).\n"
                f"--- stdout ---\n{stdout}"
            )

        if not output_path.exists():
            stdout = r.stdout.read() if r.stdout else ""  # type: ignore[union-attr]
            raise RuntimeError(
                f"Playbook {playbook_name} succeeded but no output file at {output_path}.\n"
                f"--- stdout ---\n{stdout}"
            )

        return json.loads(output_path.read_text())

    return _run
