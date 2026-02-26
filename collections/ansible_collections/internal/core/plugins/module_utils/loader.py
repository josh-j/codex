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


def load_local_module_utils(current_file: str, module_name: str, filename: str):
    """
    Load a module_utils file from the calling collection's own module_utils/ directory.

    Unlike load_module_utils (which always resolves to core), this resolves to the
    collection that contains *current_file*.  For example, a filter plugin at
    ``internal/vmware/plugins/filter/discovery.py`` calling
    ``load_local_module_utils(__file__, "discovery", "discovery.py")``
    will load ``internal/vmware/plugins/module_utils/discovery.py``.
    """
    cur = Path(current_file).resolve()

    # Derive the collection name from the path (e.g. "vmware", "windows")
    collection = None
    parts = cur.parts
    for i, part in enumerate(parts):
        if part == "internal" and i + 1 < len(parts) and i + 2 < len(parts):
            collection = parts[i + 1]
            break

    if collection:
        # Try standard Ansible import first
        fqcn = f"ansible_collections.internal.{collection}.plugins.module_utils.{module_name}"
        try:
            return importlib.import_module(fqcn)
        except (ImportError, ModuleNotFoundError):
            pass

    # Fallback: walk up from current_file to find sibling module_utils/ directory
    search = cur
    for _ in range(5):
        parent = search.parent
        if parent == search:
            break
        search = parent
        candidate = search / "module_utils" / filename
        if candidate.is_file() and candidate != cur:
            spec = importlib.util.spec_from_file_location(
                f"internal_{collection or 'local'}_{module_name}", candidate
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(module)
                return module

    raise ImportError(
        f"Could not load local module_utils {filename} for collection "
        f"'{collection or 'unknown'}' (searched from {current_file})"
    )


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
