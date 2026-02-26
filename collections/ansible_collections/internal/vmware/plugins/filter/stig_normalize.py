# internal.vmware/plugins/filter/stig_normalize.py
# Thin wrapper — business logic lives in module_utils/stig.py

import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import (
        load_local_module_utils,
    )
except ImportError:
    _loader_path = Path(__file__).resolve().parents[3] / "core" / "plugins" / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_local_module_utils = _loader_mod.load_local_module_utils

# Load all business logic from local module_utils
_mod = load_local_module_utils(__file__, "stig", "stig.py")

# Module-level re-exports (tests do cls.stig_module.some_function)
normalize_esxi_stig_facts = _mod.normalize_esxi_stig_facts
normalize_vm_stig_facts = _mod.normalize_vm_stig_facts


class FilterModule:
    def filters(self):
        return {
            "normalize_esxi_stig_facts": normalize_esxi_stig_facts,
            "normalize_vm_stig_facts": normalize_vm_stig_facts,
        }
