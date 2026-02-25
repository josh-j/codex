import importlib.util
from pathlib import Path

try:
    from ansible_collections.internal.core.plugins.module_utils.reporting_primitives import (
        as_list as _as_list,
    )
except ImportError:
    _helper_path = (
        Path(__file__).resolve().parents[3]
        / "core"
        / "plugins"
        / "module_utils"
        / "reporting_primitives.py"
    )
    _spec = importlib.util.spec_from_file_location(
        "internal_core_reporting_primitives", _helper_path
    )
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    _as_list = _mod.as_list


def normalize_esxi_stig_facts(
    raw_api_facts, identity_facts=None, services_facts=None, ssh_facts=None
):
    """
    Normalizes varied VMware ESXi facts into a canonical STIG schema.
    Fixes the advanced_settings dict -> config.option_value list mismatch.
    """
    api = dict(raw_api_facts or {})
    identity = dict(identity_facts or {})
    services = dict(services_facts or {})
    ssh = dict(ssh_facts or {})

    # 1. Build compatibility config.option_value list from advanced_settings dict
    adv_settings = api.get("advanced_settings", {})
    option_value_list = [{"key": k, "value": str(v)} for k, v in adv_settings.items()]

    # 2. Determine base identity fields
    name = api.get("name") or identity.get("name")
    uuid = api.get("uuid") or identity.get("uuid")
    version = identity.get("version") or api.get("version") or "unknown"
    build = identity.get("build") or api.get("build") or "unknown"

    # 3. Build canonical result
    return {
        "name": name,
        "uuid": uuid,
        "identity": {
            "version": version,
            "build": build,
            "uuid": uuid,
        },
        "services": services or api.get("services", {}),
        "system": api.get("system", {}),
        "advanced_settings_map": adv_settings,
        "config": {
            "option_value": option_value_list  # FIX for kernel/syslog templates
        },
        "ssh": {
            "sshd_config": ssh.get("sshd_config", ""),
            "banner_content": ssh.get("banner_content", ""),
            "firewall_raw": ssh.get("firewall_raw", ""),
        },
        "discovery_meta": {
            "schema_version": 1,
            "collectors": {
                "api": "vcenter_powercli_hybrid",
                "identity": "community.vmware.vmware_host_info",
                "services": "community.vmware.vmware_host_service_info",
                "ssh": "raw_ssh" if ssh_facts else "none",
            },
        },
    }


def normalize_vm_stig_facts(
    raw_vms,
    inventory_map=None,
    security_map=None,
    extra_config_map=None,
    hardware_map=None,
):
    """
    Normalizes VM STIG facts from multiple sources.
    """
    raw_vms = list(raw_vms or [])
    inv_map = dict(inventory_map or {})
    sec_map = dict(security_map or {})
    extra_map = dict(extra_config_map or {})
    hw_map = dict(hardware_map or {})

    results = []
    for vm in raw_vms:
        vm = dict(vm or {})
        name = vm.get("name", "unknown")

        inv = inv_map.get(name, {})
        sec = sec_map.get(name, {})
        extra = extra_map.get(name, {})
        hw = hw_map.get(name, {})

        # Determine shared fields with proper precedence
        uuid = inv.get("uuid") or vm.get("uuid")
        guest_id = inv.get("guest_id") or vm.get("guest_id", "unknown")
        tools_status = inv.get("tools_status") or vm.get("tools_status", "unknown")

        encryption = sec.get("encryption") or vm.get("encryption", "None")
        vmotion_encryption = sec.get("vmotion_encryption") or vm.get(
            "vmotion_encryption", "disabled"
        )
        logging_enabled = (
            sec.get("logging_enabled")
            if sec.get("logging_enabled") is not None
            else vm.get("logging_enabled", True)
        )
        ft_encryption = sec.get("ft_encryption") or vm.get(
            "ft_encryption", "ftEncryptionDisabled"
        )

        results.append(
            {
                "name": name,
                "uuid": uuid,
                "identity": {
                    "name": name,
                    "uuid": uuid,
                    "guest_id": guest_id,
                    "tools_status": tools_status,
                },
                "security": {
                    "encryption": encryption,
                    "vmotion_encryption": vmotion_encryption,
                    "logging_enabled": logging_enabled,
                    "ft_encryption": ft_encryption,
                },
                "advanced_settings": extra or vm.get("advanced_settings", {}),
                "hardware": hw or vm.get("hardware", {}),
                # Compatibility aliases for existing templates
                "tools_status": tools_status,
                "encryption": encryption,
                "vmotion_encryption": vmotion_encryption,
                "logging_enabled": logging_enabled,
                "ft_encryption": ft_encryption,
                "discovery_meta": {
                    "schema_version": 1,
                    "source": "hybrid_vm_collector",
                },
            }
        )
    return results


class FilterModule:
    def filters(self):
        return {
            "normalize_esxi_stig_facts": normalize_esxi_stig_facts,
            "normalize_vm_stig_facts": normalize_vm_stig_facts,
        }
