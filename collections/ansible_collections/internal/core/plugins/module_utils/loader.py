# collections/ansible_collections/internal/core/plugins/module_utils/loader.py

import importlib.util
from pathlib import Path


def load_module_utils(current_file, module_name, filename):
    """
    Standardizes loading module_utils from filter plugins during tests/standalone runs.
    """
    try:
        # Standard Ansible import (only works when run via Ansible)
        return importlib.import_module(f"ansible_collections.internal.core.plugins.module_utils.{module_name}")
    except (ImportError, ModuleNotFoundError) as exc:
        # Fallback for standalone/pytest: find the internal/core directory
        cur = Path(current_file).resolve()
        core_mu = None
        for _ in range(5):
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
            # Check if we are in a collection and internal/core exists next to us
            potential_core = cur.parent / "core" / "plugins" / "module_utils"
            if potential_core.is_dir():
                core_mu = potential_core
                break

        if not core_mu:
            # Fallback to local module_utils if not found in core
            core_mu = Path(current_file).resolve().parents[1] / "module_utils"

        _util_path = core_mu / filename
        spec = importlib.util.spec_from_file_location(f"internal_core_{module_name}", _util_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        raise ImportError(f"Could not load module_utils {filename} (searched {core_mu})") from exc


def load_filter(current_file, filter_name, filename):
    """
    Standardizes loading filters from other filters during tests/standalone runs.
    """
    try:
        # Standard Ansible import
        return importlib.import_module(f"ansible_collections.internal.core.plugins.filter.{filter_name}")
    except (ImportError, ModuleNotFoundError) as exc:
        cur = Path(current_file).resolve()
        core_filter = None
        for _ in range(5):
            parent = cur.parent
            if parent == cur:
                break
            cur = parent
            potential_core = cur.parent / "core" / "plugins" / "filter"
            if potential_core.is_dir():
                core_filter = potential_core
                break

        if not core_filter:
            core_filter = Path(current_file).resolve().parents[1] / "filter"

        _filter_path = core_filter / filename
        spec = importlib.util.spec_from_file_location(f"internal_core_{filter_name}_filter", _filter_path)
        if spec and spec.loader:
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            return module
        raise ImportError(f"Could not load filter {filename} (searched {core_filter})") from exc
