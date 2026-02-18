#!/usr/bin/env python3
# roles/vsphere/files/get_vcenter_alarms.py
import json
import os
import ssl
import sys

from pyVim.connect import Disconnect, SmartConnect


def get_triggered_alarms(host, user, password):
    """Get all triggered alarms from vCenter"""
    if not password:
        return {"success": False, "error": "Password not provided via VC_PASSWORD", "alarms": [], "count": 0}

    context = ssl._create_unverified_context()

    try:
        si = SmartConnect(host=host, user=user, pwd=password, sslContext=context)

        content = si.RetrieveContent()
        triggered_alarms = content.rootFolder.triggeredAlarmState

        alarms = []
        for alarm_state in triggered_alarms:
            try:
                # Key names aligned with Ansible templates
                alarm_info = {
                    "alarm_name": alarm_state.alarm.info.name
                    if alarm_state.alarm and alarm_state.alarm.info
                    else "Unknown",
                    "description": alarm_state.alarm.info.description
                    if alarm_state.alarm and alarm_state.alarm.info
                    else "",
                    "entity": alarm_state.entity.name
                    if hasattr(alarm_state.entity, "name")
                    else str(alarm_state.entity),
                    "entity_type": type(alarm_state.entity).__name__,
                    "status": alarm_state.overallStatus,
                    "severity": "critical"
                    if alarm_state.overallStatus == "red"
                    else (
                        "warning" if alarm_state.overallStatus == "yellow" else "info"
                    ),
                    "time": str(alarm_state.time) if alarm_state.time else "",
                    "acknowledged": alarm_state.acknowledged,
                }
                alarms.append(alarm_info)
            except Exception:
                continue

        Disconnect(si)
        return {"success": True, "alarms": alarms, "count": len(alarms)}

    except Exception as e:
        return {"success": False, "error": str(e), "alarms": [], "count": 0}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(
            json.dumps(
                {"success": False, "error": "Usage: script.py <host> <user> (password via VC_PASSWORD env)"}
            )
        )
        sys.exit(1)

    password = os.environ.get("VC_PASSWORD")
    result = get_triggered_alarms(sys.argv[1], sys.argv[2], password)
    print(json.dumps(result))
