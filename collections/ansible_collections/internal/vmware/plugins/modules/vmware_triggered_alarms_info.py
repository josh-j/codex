#!/usr/bin/env python3

# (c) 2024, Codex Team
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

import ssl

from ansible.module_utils.basic import AnsibleModule

try:
    from pyVim.connect import Disconnect, SmartConnect

    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False



DOCUMENTATION = r"""
---
module: vmware_triggered_alarms_info
short_description: Gather triggered alarms from vCenter
description:
    - This module gathers active (unacknowledged) triggered alarms from vCenter.
    - It filters out 'green' and 'gray' statuses.
options:
    hostname:
        description:
            - The hostname or IP address of the vSphere vCenter server.
        type: str
        required: true
    username:
        description:
            - The username of the vSphere vCenter server.
        type: str
        required: true
    password:
        description:
            - The password of the vSphere vCenter server.
        type: str
        required: true
        no_log: true
    validate_certs:
        description:
            - Whether to validate SSL certificates.
        type: bool
        default: false
author:
    - Codex Team
"""

EXAMPLES = r"""
- name: Get triggered alarms
  internal.vmware.vmware_triggered_alarms_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
  register: alarms_info
"""

RETURN = r"""
alarms:
    description: List of triggered alarms
    returned: always
    type: list
    sample:
        - alarm_name: "Host connection failure"
          status: "red"
          severity: "CRITICAL"
          entity: "esxi01"
count:
    description: Number of alarms found
    returned: always
    type: int
"""


def run_module():
    module_args = dict(
        hostname=dict(type="str", required=True),
        username=dict(type="str", required=True),
        password=dict(type="str", required=True, no_log=True),
        validate_certs=dict(type="bool", default=False),
    )

    result = dict(changed=False, alarms=[], count=0)

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if not HAS_PYVMOMI:
        module.fail_json(msg="pyVmomi is required for this module")

    hostname = module.params["hostname"]
    username = module.params["username"]
    password = module.params["password"]
    validate_certs = module.params["validate_certs"]

    if not validate_certs:
        context = ssl._create_unverified_context()
    else:
        context = ssl.create_default_context()

    si = None
    try:
        si = SmartConnect(host=hostname, user=username, pwd=password, sslContext=context)
        content = si.RetrieveContent()
        triggered = getattr(content.rootFolder, "triggeredAlarmState", []) or []

        alarms = []
        for state in triggered:
            try:
                acknowledged = bool(getattr(state, "acknowledged", False))
                if acknowledged:
                    continue

                status = str(getattr(state, "overallStatus", "gray")).lower()
                if status in {"green", "gray"}:
                    continue

                severity = "CRITICAL" if status == "red" else ("WARNING" if status == "yellow" else "INFO")
                alarm_obj = getattr(state, "alarm", None)
                info = getattr(alarm_obj, "info", None) if alarm_obj else None
                entity = getattr(state, "entity", None)
                entity_name = getattr(entity, "name", None)

                alarms.append(
                    {
                        "alarm_name": getattr(info, "name", "Unknown"),
                        "description": getattr(info, "description", "") or "",
                        "entity": entity_name or str(entity),
                        "entity_type": type(entity).__name__ if entity is not None else "Unknown",
                        "status": status,
                        "severity": severity,
                        "time": str(getattr(state, "time", "") or ""),
                        "acknowledged": acknowledged,
                    }
                )
            except Exception:
                continue

        result["alarms"] = alarms
        result["count"] = len(alarms)
        module.exit_json(**result)

    except Exception as e:
        module.fail_json(msg=str(e))
    finally:
        if si:
            Disconnect(si)


if __name__ == "__main__":
    run_module()
