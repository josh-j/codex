from pathlib import Path
import sys
import types

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

ansible_module = types.ModuleType("ansible")
plugins_module = types.ModuleType("ansible.plugins")
callback_module = types.ModuleType("ansible.plugins.callback")


class _CallbackBase:
    pass


callback_module.CallbackBase = _CallbackBase
plugins_module.callback = callback_module
ansible_module.plugins = plugins_module

sys.modules.setdefault("ansible", ansible_module)
sys.modules.setdefault("ansible.plugins", plugins_module)
sys.modules.setdefault("ansible.plugins.callback", callback_module)

from internal.core.plugins.callback.ncs_collector import CallbackModule


def test_assemble_split_host_payload_tolerates_nullish_vmware_lists() -> None:
    entry = {
        "item": "esxi-01.local",
        "ansible_facts": {
            "ansible_distribution_version": "8.0.3",
            "ansible_distribution_build": "123456",
            "ansible_datastore": None,
        },
    }
    full_payload = {
        "hosts_info": {
            "host_nics": {"results": None},
            "host_services": {
                "results": [
                    {
                        "host_service_info": {
                            "esxi-01.local": None,
                        }
                    }
                ]
            },
        },
        "clusters_info": {
            "results": [
                {
                    "item": "dc-01",
                    "clusters_info": {
                        "cluster-a": {
                            "hosts": None,
                        }
                    },
                }
            ]
        },
    }

    payload = CallbackModule._assemble_split_host_payload(entry, "esxi-01.local", full_payload, {})

    assert payload["name"] == "esxi-01.local"
    assert payload["datastores"] == []
    assert payload["nics"] == []
    assert payload["cluster"] == ""
    assert payload["datacenter"] == ""
    assert payload["ssh_enabled"] is False
    assert payload["shell_enabled"] is False
    assert payload["ntp_running"] is False


def test_assemble_split_host_payload_merges_vmware_context_when_shapes_are_valid() -> None:
    entry = {
        "item": "esxi-01.local",
        "ansible_facts": {
            "ansible_distribution_version": "8.0.3",
            "ansible_distribution_build": "123456",
            "ansible_memtotal_mb": 1000,
            "ansible_memfree_mb": 250,
            "ansible_datastore": [
                {"name": "datastore1", "total": "100", "free": "25"},
            ],
        },
    }
    full_payload = {
        "hosts_info": {
            "host_nics": {
                "results": [
                    {
                        "hosts_vmnic_info": {
                            "esxi-01.local": {
                                "vmnic_details": [
                                    {
                                        "device": "vmnic0",
                                        "status": "up",
                                        "speed": "1000",
                                        "driver": "ixgben",
                                        "vswitch": "vSwitch0",
                                    }
                                ]
                            }
                        }
                    }
                ]
            },
            "host_services": {
                "results": [
                    {
                        "host_service_info": {
                            "esxi-01.local": [
                                {"key": "TSM-SSH", "running": True},
                                {"key": "TSM", "running": True},
                                {"key": "ntpd", "running": False},
                            ]
                        }
                    }
                ]
            },
        },
        "clusters_info": {
            "results": [
                {
                    "item": "dc-01",
                    "clusters_info": {
                        "cluster-a": {
                            "hosts": [
                                {"name": "esxi-01.local"},
                            ]
                        }
                    },
                }
            ]
        },
    }

    payload = CallbackModule._assemble_split_host_payload(entry, "esxi-01.local", full_payload, {})

    assert payload["mem_used_pct"] == 75.0
    assert payload["datastores"] == [{"name": "datastore1", "total": "100", "free": "25"}]
    assert payload["nics"] == [
        {
            "device": "vmnic0",
            "link_status": "up",
            "speed_mbps": 1000,
            "driver": "ixgben",
            "switch": "vSwitch0",
        }
    ]
    assert payload["cluster"] == "cluster-a"
    assert payload["datacenter"] == "dc-01"
    assert payload["ssh_enabled"] is True
    assert payload["shell_enabled"] is True
    assert payload["ntp_running"] is False
