"""Hardcoded RETURN samples from Ansible modules.

These were extracted from module RETURN docstrings via yaml.safe_load(module.RETURN).
To regenerate after a module update, run from the repo root venv:

    python -c "
    import sys, yaml, json
    sys.path.insert(0, 'collections')
    from ansible_collections.vmware.vmware.plugins.modules import appliance_info as m
    print(json.dumps(yaml.safe_load(m.RETURN)['appliance']['sample'], indent=2))
    "

Replace the corresponding dict below with the printed output.
"""

from __future__ import annotations

# appliance_info RETURN["appliance"]["sample"] — includes outer "appliance" key
APPLIANCE_BASE: dict = {
    "appliance": {
        "access": {
            "consolecli": False,
            "dcui": False,
            "shell": {"enabled": "False", "timeout": "0"},
            "ssh": True,
        },
        "firewall": {
            "inbound": [
                {"address": "1.2.3.6", "interface_name": "*", "policy": "ACCEPT", "prefix": "32"},
                {"address": "1.2.4.5", "interface_name": "nic0", "policy": "IGNORE", "prefix": "24"},
            ]
        },
        "networking": {
            "network": {
                "dns_servers": [],
                "hostname": ["vcenter.local"],
                "nics": {
                    "nic0": {
                        "ipv4": "{configurable : True, mode : STATIC, address : 10.185.246.4, prefix : 26, default_gateway : 10.185.246.1}",
                        "ipv6": "None",
                        "mac": "00:50:56:cd:e7:2e",
                        "name": "nic0",
                        "status": "up",
                    }
                },
            },
            "proxy": {
                "ftp": {"enabled": "False", "password": "None", "port": "-1", "server": "", "username": "None"},
                "http": {
                    "enabled": "True",
                    "password": "None",
                    "port": "80",
                    "server": "http://localhost",
                    "username": "None",
                },
                "https": {"enabled": "False", "password": "None", "port": "-1", "server": "", "username": "None"},
                "noproxy": ["localhost", "127.0.0.1"],
            },
        },
        "services": {
            "appliance-shutdown": {
                "description": "/etc/rc.local.shutdown Compatibility",
                "state": "STOPPED",
            }
        },
        "summary": {
            "build_number": "21560480",
            "health": {
                "cpu": "green",
                "database": "green",
                "memory": "green",
                "overall": "green",
                "storage": "green",
                "swap": "green",
            },
            "hostname": ["vcenter.local"],
            "product": "VMware vCenter Server",
            "sso": {},
            "uptime": "12531937.54",
            "version": "8.0.1.00000",
        },
        "syslog": {"forwarding": []},
        "time": {
            "time_sync": {
                "current": {
                    "date": "Tue 03-26-2024",
                    "seconds_since_epoch": "1711465124.5183642",
                    "time": "02:58:44 PM",
                    "timezone": "UTC",
                },
                "mode": "NTP",
                "servers": ["time.google.com"],
            },
            "time_zone": "Etc/UTC",
        },
    }
}

# vmware_datastore_info RETURN["datastores"]["sample"][0]
DS_BASE: dict = {
    "accessible": False,
    "capacity": 42681237504,
    "datastore_cluster": "datacluster0",
    "freeSpace": 39638269952,
    "maintenanceMode": "normal",
    "multipleHostAccess": False,
    "name": "datastore2",
    "provisioned": 12289211488,
    "type": "VMFS",
    "uncommitted": 9246243936,
    "url": "ds:///vmfs/volumes/5a69b18a-c03cd88c-36ae-5254001249ce/",
    "vmfs_blockSize": 1024,
    "vmfs_uuid": "5a69b18a-c03cd88c-36ae-5254001249ce",
    "vmfs_version": "6.81",
}

# vmware_vm_info RETURN["virtual_machines"]["sample"][0]
VM_BASE: dict = {
    "guest_name": "ubuntu_t",
    "datacenter": "Datacenter-1",
    "cluster": None,
    "esxi_hostname": "10.76.33.226",
    "folder": "/Datacenter-1/vm",
    "guest_fullname": "Ubuntu Linux (64-bit)",
    "ip_address": "",
    "mac_address": ["00:50:56:87:a5:9a"],
    "power_state": "poweredOff",
    "uuid": "4207072c-edd8-3bd5-64dc-903fd3a0db04",
    "vm_network": {
        "00:50:56:87:a5:9a": {
            "ipv4": ["10.76.33.228/24"],
            "ipv6": [],
        }
    },
    "attributes": {"job": "backup-prepare"},
    "datastore_url": [{"name": "t880-o2g", "url": "/vmfs/volumes/e074264a-e5c82a58"}],
    "tags": [
        {
            "category_id": "urn:vmomi:InventoryServiceCategory:b316cc45-f1a9-4277-811d-56c7e7975203:GLOBAL",
            "category_name": "cat_0001",
            "description": "",
            "id": "urn:vmomi:InventoryServiceTag:43737ec0-b832-4abf-abb1-fd2448ce3b26:GLOBAL",
            "name": "tag_0001",
        }
    ],
    "moid": "vm-24",
    "allocated": {"storage": 500000000, "cpu": 2, "memory": 16},
}

# win_service RETURN — {k: v["sample"] for k, v in yaml.safe_load(win_service_mod.RETURN).items()}
WIN_SVC_BASE: dict = {
    "exists": True,
    "name": "CoreMessagingRegistrar",
    "display_name": "CoreMessaging",
    "state": "stopped",
    "start_mode": "manual",
    "path": "C:\\Windows\\system32\\svchost.exe -k LocalServiceNoNetwork",
    "can_pause_and_continue": True,
    "description": "Manages communication between system components.",
    "username": "LocalSystem",
    "desktop_interact": False,
    "dependencies": False,
    "depended_by": False,
}
