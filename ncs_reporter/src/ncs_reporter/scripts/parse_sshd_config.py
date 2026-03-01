#!/usr/bin/env python3
"""
Built-in script: parse sshd_config key/value pairs from raw stdout lines.

Strips comments and blank lines, splits on whitespace, strips inline comments.

stdin  — JSON: {"fields": {"sshd_lines": [...]}, "args": {}}
stdout — JSON object: {"PermitRootLogin": "no", "PasswordAuthentication": "yes", ...}
"""

from typing import Any

import json
import re
import sys

_SPLIT = re.compile(r"\s+")


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})

    lines: list[Any] = fields.get("sshd_lines") or []
    result: dict[str, str] = {}

    for line in lines:
        line = str(line or "").strip()
        if not line or line.startswith("#"):
            continue
        parts = _SPLIT.split(line, maxsplit=1)
        if len(parts) == 2 and parts[0]:
            # Strip trailing inline comment
            value = parts[1].split("#", 1)[0].strip()
            result[parts[0]] = value

    print(json.dumps(result))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
