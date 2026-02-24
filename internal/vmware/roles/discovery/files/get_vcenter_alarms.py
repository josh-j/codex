#!/usr/bin/env python3
# collections/ansible_collections/internal/vmware/roles/discovery/files/get_vcenter_alarms.py

import argparse
import json
import os
import ssl
import sys

from pyVim.connect import Disconnect, SmartConnect


def get_triggered_alarms(host: str, user: str, password: str) -> dict:
    if not password:
        return {
            "success": False,
            "error": "Password not provided via VC_PASSWORD",
            "alarms": [],
            "count": 0,
        }

    # SECURITY: Disabling TLS verification is risky. Prefer a trusted CA bundle in production.
    # If you must bypass verification (lab/self-signed), keep it explicit like this.
    context = ssl._create_unverified_context()

    si = None
    try:
        si = SmartConnect(host=host, user=user, pwd=password, sslContext=context)
        content = si.RetrieveContent()
        triggered = getattr(content.rootFolder, "triggeredAlarmState", []) or []

        alarms = []
        for state in triggered:
            try:
                # Some vSphere objects can be missing fields depending on alarm type
                acknowledged = bool(getattr(state, "acknowledged", False))
                if acknowledged:
                    continue

                status = str(
                    getattr(state, "overallStatus", "gray")
                ).lower()  # gray/green/yellow/red

                if status in {"green", "gray"}:
                    continue

                # Standardize severities (you later lower() in Ansible anyway)
                severity = (
                    "CRITICAL"
                    if status == "red"
                    else ("WARNING" if status == "yellow" else "INFO")
                )

                alarm_obj = getattr(state, "alarm", None)
                info = getattr(alarm_obj, "info", None) if alarm_obj else None

                entity = getattr(state, "entity", None)
                entity_name = getattr(entity, "name", None)

                alarms.append(
                    {
                        "alarm_name": getattr(info, "name", "Unknown"),
                        "description": getattr(info, "description", "") or "",
                        "entity": entity_name or str(entity),
                        "entity_type": type(entity).__name__
                        if entity is not None
                        else "Unknown",
                        "status": status,
                        "severity": severity,
                        "time": str(getattr(state, "time", "") or ""),
                        "acknowledged": acknowledged,
                    }
                )
            except Exception:
                # Keep collecting other alarms even if one record is weird
                continue

        return {"success": True, "alarms": alarms, "count": len(alarms)}

    except Exception as e:
        return {"success": False, "error": str(e), "alarms": [], "count": 0}

    finally:
        if si is not None:
            Disconnect(si)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("host")
    parser.add_argument("user")
    args = parser.parse_args()

    result = get_triggered_alarms(args.host, args.user, os.environ.get("VC_PASSWORD"))

    # Ensure stdout is JSON-only for Ansible parsing.
    print(json.dumps(result))

    # Non-zero exit code on failure so Ansible can detect it reliably.
    return 0 if result.get("success") else 2


if __name__ == "__main__":
    sys.exit(main())
