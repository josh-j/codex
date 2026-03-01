#!/usr/bin/env python3
"""
Built-in script: count pending package upgrades from apt-get -s upgrade output.

Parses the summary line "X upgraded, Y newly installed, ..." produced by
`apt-get -s upgrade` (or `apt-get --dry-run upgrade`).

stdin  — JSON: {"fields": {"apt_lines": [...]}, "args": {}}
stdout — JSON integer (number of upgradeable packages; 0 if not parseable)
"""

from __future__ import annotations

import json
import re
import sys

_PATTERN = re.compile(r"(\d+)\s+upgraded,")


def main() -> None:
    payload = json.load(sys.stdin)
    fields = payload.get("fields", {})

    lines = fields.get("apt_lines")
    if lines is None:
        # apt_lines field absent — apt not collected on this host.
        sys.exit(1)

    for line in reversed(lines):
        line = str(line or "")
        m = _PATTERN.search(line)
        if m:
            print(json.dumps(int(m.group(1))))
            return

    print(json.dumps(0))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"error: {exc}", file=sys.stderr)
        sys.exit(2)
