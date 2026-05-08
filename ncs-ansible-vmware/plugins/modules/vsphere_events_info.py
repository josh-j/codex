#!/usr/bin/python
"""Collect normalized vSphere alarms, recent tasks, and recent events."""

from __future__ import annotations

import ssl
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.internal.vmware.plugins.module_utils.vsphere.normalize import normalize_events

try:
    from pyVim.connect import Disconnect, SmartConnect
    from pyVmomi import vim

    HAS_PYVMOMI = True
except ImportError:
    HAS_PYVMOMI = False


DOCUMENTATION = r"""
---
module: vsphere_events_info
short_description: Collect normalized vSphere event payload
description:
  - Collects active alarms plus recent vCenter tasks/events into C(vsphere_events).
options:
  hostname:
    type: str
    required: true
  username:
    type: str
    required: true
  password:
    type: str
    required: true
    no_log: true
  validate_certs:
    type: bool
    default: false
  window_hours:
    type: int
    default: 24
  limit:
    type: int
    default: 500
author:
  - NCS
"""


def _severity(status: Any) -> str:
    value = str(status or "").lower()
    if value == "red":
        return "critical"
    if value == "yellow":
        return "warning"
    return "info"


def _active_alarms(content: Any) -> list[dict[str, Any]]:
    rows = []
    for state in getattr(content.rootFolder, "triggeredAlarmState", None) or []:
        if bool(getattr(state, "acknowledged", False)):
            continue
        status = str(getattr(state, "overallStatus", "gray")).lower()
        if status in {"green", "gray"}:
            continue
        alarm = getattr(state, "alarm", None)
        info = getattr(alarm, "info", None) if alarm else None
        entity = getattr(state, "entity", None)
        rows.append({
            "key": getattr(alarm, "_moId", "") or getattr(info, "name", ""),
            "time": str(getattr(state, "time", "") or ""),
            "entity": getattr(entity, "name", "") if entity else "",
            "message": getattr(info, "name", "Unknown alarm"),
            "description": getattr(info, "description", "") or "",
            "status": status,
            "severity": _severity(status),
        })
    return rows


def _recent_events(content: Any, *, window_hours: int, limit: int) -> list[dict[str, Any]]:
    event_manager = getattr(content, "eventManager", None)
    if event_manager is None:
        return []
    spec = vim.event.EventFilterSpec()
    spec.time = vim.event.EventFilterSpec.ByTime()
    spec.time.beginTime = datetime.now(timezone.utc) - timedelta(hours=window_hours)
    spec.time.endTime = datetime.now(timezone.utc)
    collector = event_manager.CreateCollectorForEvents(spec)
    try:
        events = collector.ReadNextEvents(limit)
    finally:
        collector.DestroyCollector()
    rows = []
    for event in events or []:
        rows.append({
            "key": getattr(event, "key", ""),
            "createdTime": str(getattr(event, "createdTime", "") or ""),
            "userName": getattr(event, "userName", "") or "",
            "entity": {"name": getattr(getattr(event, "vm", None) or getattr(event, "host", None) or getattr(event, "computeResource", None), "name", "")},
            "fullFormattedMessage": getattr(event, "fullFormattedMessage", "") or "",
        })
    return rows


def _recent_tasks(content: Any, *, limit: int) -> list[dict[str, Any]]:
    task_manager = getattr(content, "taskManager", None)
    tasks = list(getattr(task_manager, "recentTask", []) or []) if task_manager is not None else []
    rows = []
    for task in tasks[:limit]:
        info = getattr(task, "info", None)
        entity = getattr(info, "entity", None)
        rows.append({
            "key": getattr(info, "key", ""),
            "createdTime": str(getattr(info, "queueTime", "") or getattr(info, "startTime", "") or ""),
            "userName": getattr(info, "reason", "") and str(getattr(info, "reason", "")),
            "entity": {"name": getattr(entity, "name", "") if entity else ""},
            "fullFormattedMessage": getattr(info, "descriptionId", "") or getattr(info, "name", "") or "",
            "status": str(getattr(info, "state", "") or ""),
        })
    return rows


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "hostname": {"type": "str", "required": True},
            "username": {"type": "str", "required": True},
            "password": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": False},
            "window_hours": {"type": "int", "default": 24},
            "limit": {"type": "int", "default": 500},
        },
        supports_check_mode=True,
    )
    result: dict[str, Any] = {"changed": False, "python": sys.executable, "vsphere_events": {}}
    if not HAS_PYVMOMI:
        module.fail_json(msg="pyVmomi is required for vsphere_events_info", **result)

    context = ssl.create_default_context() if module.params["validate_certs"] else ssl._create_unverified_context()
    si = None
    try:
        si = SmartConnect(
            host=module.params["hostname"],
            user=module.params["username"],
            pwd=module.params["password"],
            sslContext=context,
        )
        content = si.RetrieveContent()
        recent = _recent_events(content, window_hours=module.params["window_hours"], limit=module.params["limit"])
        result["vsphere_events"] = normalize_events(
            vcenter=module.params["hostname"],
            alarms=_active_alarms(content),
            tasks=_recent_tasks(content, limit=module.params["limit"]),
            events=recent,
            window_hours=module.params["window_hours"],
            limit=module.params["limit"],
        )
        module.exit_json(**result)
    except Exception as exc:
        result["vsphere_events"] = normalize_events(
            vcenter=module.params["hostname"],
            window_hours=module.params["window_hours"],
            limit=module.params["limit"],
            errors=[{"source": "vsphere_events_info", "message": str(exc)}],
        )
        module.fail_json(msg=str(exc), **result)
    finally:
        if si is not None:
            Disconnect(si)


if __name__ == "__main__":
    run_module()
