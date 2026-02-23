#!/usr/bin/env python3
# collections/ansible_collections/internal/vmware/roles/discovery/files/get_vcenter_alarms.py
#
# Collects all triggered alarms from vCenter via PyVmomi.
# Password is passed via VC_PASSWORD environment variable - never as an argument.
#
# Usage: get_vcenter_alarms.py <host> <user>
# Output: JSON to stdout - {"success": bool, "alarms": [...], "count": int}

import json
import os
import ssl
import sys

from pyVim.connect import Disconnect, SmartConnect


def get_triggered_alarms(host, user, password):
    if not password:
        return {
            "success": False,
            "error": "Password not provided via VC_PASSWORD",
            "alarms": [],
            "count": 0,
        }

    context = ssl._create_unverified_context()

    try:
        si = SmartConnect(host=host, user=user, pwd=password, sslContext=context)
    except Exception as e:
        return {"success": False, "error": str(e), "alarms": [], "count": 0}

    try:
        content = si.RetrieveContent()
        triggered = content.rootFolder.triggeredAlarmState

        alarms = []
        for state in triggered:
            try:
                has_info = state.alarm and state.alarm.info
                status = state.overallStatus

                alarms.append(
                    {
                        "alarm_name": state.alarm.info.name if has_info else "Unknown",
                        "description": state.alarm.info.description if has_info else "",
                        "entity": state.entity.name
                        if hasattr(state.entity, "name")
                        else str(state.entity),
                        "entity_type": type(state.entity).__name__,
                        "status": status,
                        "severity": "critical"
                        if status == "red"
                        else ("warning" if status == "yellow" else "info"),
                        "time": str(state.time) if state.time else "",
                        "acknowledged": state.acknowledged,
                    }
                )
            except Exception:
                continue

        return {"success": True, "alarms": alarms, "count": len(alarms)}

    finally:
        Disconnect(si)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": "Usage: get_vcenter_alarms.py <host> <user>  (password via VC_PASSWORD)",
                }
            )
        )
        sys.exit(1)

    result = get_triggered_alarms(
        sys.argv[1], sys.argv[2], os.environ.get("VC_PASSWORD")
    )
    print(json.dumps(result))
