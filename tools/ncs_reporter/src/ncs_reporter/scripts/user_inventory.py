#!/usr/bin/env python3
"""
Built-in script: build enriched user inventory from getent_passwd + shadow.

Combines ansible_facts.getent_passwd (dict) with raw shadow file lines to
compute password_age_days for each local user.

stdin  — JSON: {
    "fields": {
        "getent_passwd": {"username": [pw, uid, gid, gecos, home, shell], ...},
        "shadow_lines":  ["username:$6$...:19000:0:99999:7:::", ...],
        "epoch_seconds": 1709000000
    },
    "args": {}
}
stdout — JSON list of user dicts:
         {name, uid, gid, home, shell, password_age_days}
         password_age_days == -1 means no shadow entry / locked
"""

from __future__ import annotations

import json
import sys


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})

    getent_passwd: dict = fields.get("getent_passwd") or {}
    shadow_lines: list = fields.get("shadow_lines") or []
    epoch_seconds: int = int(fields.get("epoch_seconds") or 0)
    epoch_days = epoch_seconds // 86400

    # Build shadow map: username → last_change_days_since_epoch
    shadow_map: dict[str, int] = {}
    for line in shadow_lines:
        line = str(line or "").strip()
        if not line or line.startswith("#") or ":" not in line:
            continue
        parts = line.split(":")
        username = parts[0]
        try:
            last_change = int(parts[2]) if len(parts) > 2 and parts[2] else 0
        except ValueError:
            last_change = 0
        if username:
            shadow_map[username] = last_change

    result = []
    for user, info in getent_passwd.items():
        info = list(info) if isinstance(info, list) else []
        last_change = shadow_map.get(str(user), 0)
        password_age_days = (epoch_days - last_change) if last_change > 0 else -1
        result.append({
            "name": str(user),
            "uid": info[1] if len(info) > 1 else "",
            "gid": info[2] if len(info) > 2 else "",
            "home": info[4] if len(info) > 4 else "",
            "shell": info[5] if len(info) > 5 else "",
            "password_age_days": password_age_days,
        })

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
