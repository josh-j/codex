# collections/ansible_collections/internal/vmware/plugins/modules/vmware_triggered_alarms_info.py

import ssl
import sys
from typing import Any

from ansible.module_utils.basic import AnsibleModule

try:
    from pyVim.connect import Disconnect, SmartConnect  # pyVmomi dependency

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
  - NCS
"""

EXAMPLES = r"""
- name: Get triggered alarms
  internal.vmware.vmware_triggered_alarms_info:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    validate_certs: false
  register: alarms_info
"""

RETURN = r"""
alarms:
  description: List of triggered alarms
  returned: always
  type: list
count:
  description: Number of alarms found
  returned: always
  type: int
python:
  description: Python interpreter used to run the module
  returned: always
  type: str
"""


def _severity_from_status(status: str) -> str:
    s = (status or "").strip().lower()
    if s == "red":
        return "CRITICAL"
    if s == "yellow":
        return "WARNING"
    return "INFO"


def run_module() -> None:
    module_args = dict(
        hostname=dict(type="str", required=True),
        username=dict(type="str", required=True),
        password=dict(type="str", required=True, no_log=True),
        validate_certs=dict(type="bool", default=False),
    )

    result: dict[str, Any] = dict(changed=False, alarms=[], count=0, python=sys.executable)

    module = AnsibleModule(argument_spec=module_args, supports_check_mode=True)

    if not HAS_PYVMOMI:
        module.fail_json(
            msg=(
                "pyVmomi is required for this module. "
                f"Interpreter: {sys.executable}. "
                "Install into the interpreter environment used by Ansible "
                "(e.g. pip install pyvmomi)."
            ),
            **result,
        )

    hostname = module.params["hostname"]
    username = module.params["username"]
    password = module.params["password"]
    validate_certs = module.params["validate_certs"]

    # SSL context handling
    if validate_certs:
        context = ssl.create_default_context()
    else:
        context = ssl._create_unverified_context()

    si = None
    try:
        # Connect to vCenter
        si = SmartConnect(
            host=hostname, user=username, pwd=password, sslContext=context
        )
        content = si.RetrieveContent()

        # Note: triggeredAlarmState may not be present depending on permissions/object model
        triggered = getattr(content.rootFolder, "triggeredAlarmState", None) or []

        alarms = []
        for state in triggered:
            # Defensive parsing: a single weird object shouldn't fail the module
            try:
                acknowledged = bool(getattr(state, "acknowledged", False))
                if acknowledged:
                    continue

                status = str(getattr(state, "overallStatus", "gray")).lower()
                if status in {"green", "gray"}:
                    continue

                alarm_obj = getattr(state, "alarm", None)
                info = getattr(alarm_obj, "info", None) if alarm_obj else None

                entity = getattr(state, "entity", None)
                entity_name = (
                    getattr(entity, "name", None) if entity is not None else None
                )

                alarms.append(
                    {
                        "alarm_name": getattr(info, "name", "Unknown"),
                        "description": getattr(info, "description", "") or "",
                        "entity": entity_name
                        or (str(entity) if entity is not None else "Unknown"),
                        "entity_type": type(entity).__name__
                        if entity is not None
                        else "Unknown",
                        "status": status,
                        "severity": _severity_from_status(status),
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
        module.fail_json(msg=str(e), **result)
    finally:
        if si is not None:
            try:
                Disconnect(si)
            except Exception:
                # Avoid masking the original failure/exit
                pass


if __name__ == "__main__":
    run_module()
