#!/usr/bin/env python3
"""Emit the list of FQCN playbook references from ncs-reporter configs.

Reads every `config.stig.ansible_playbook.path:` value across
ncs-reporter/src/ncs_reporter/configs/*.yaml and prints the FQCN-form
references, one per line. The Justfile target `verify-fqcn-contract`
runs this, then `ansible-playbook --syntax-check` on each FQCN to catch
drift between the reporter config and installed collection versions.
"""

from __future__ import annotations

import pathlib
import re
import sys

import yaml

_FQCN = re.compile(r"^internal\.[a-z_]+\.[a-z0-9_]+$")


def main() -> int:
    root = pathlib.Path("ncs-reporter/src/ncs_reporter/configs")
    if not root.is_dir():
        print(f"configs dir not found: {root}", file=sys.stderr)
        return 1

    seen: set[str] = set()
    for p in sorted(root.glob("*.yaml")):
        try:
            data = yaml.safe_load(p.read_text())
        except yaml.YAMLError:
            continue
        if not isinstance(data, dict):
            continue
        cfg = data.get("config", {}) or {}
        stig = cfg.get("stig", {}) or {}
        ap = stig.get("ansible_playbook", {}) or {}
        path = ap.get("path") or ""
        if path and _FQCN.match(path):
            seen.add(path)

    for fqcn in sorted(seen):
        print(fqcn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
