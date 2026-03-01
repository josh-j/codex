#!/usr/bin/env python3
"""
Built-in script: count triggered alarms by severity.

stdin  — JSON: {"fields": {"active_alarms": [...]}, "args": {}}
stdout — JSON dict: {"critical": N, "warning": N, "total": N}
"""

import json
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print('{"critical": 0, "warning": 0, "total": 0}')
        return

    fields = payload.get("fields", {})
    alarms = fields.get("active_alarms") or []
    
    if not isinstance(alarms, list):
        alarms = []

    crit = 0
    warn = 0
    for a in alarms:
        if not isinstance(a, dict):
            continue
        sev = str(a.get("severity") or "").lower()
        if sev == "critical":
            crit += 1
        elif sev == "warning":
            warn += 1

    print(json.dumps({
        "critical": crit,
        "warning": warn,
        "total": len(alarms)
    }))


if __name__ == "__main__":
    main()
