#!/usr/bin/env python3
"""Sync ncs_path_contract resolver into Ansible collection module_utils."""

from __future__ import annotations

import argparse
import difflib
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "ncs_reporter" / "src" / "ncs_path_contract" / "resolver.py"
DST = (
    REPO_ROOT
    / "ncs_ansible"
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "path_contract.py"
)


HEADER = '"""Path contract resolver shared by collector runtime in Ansible collection."""\n\n'


def _expected_dst_content(src_text: str) -> str:
    # Replace leading module docstring from reporter version with module_utils-specific header.
    if src_text.startswith('"""'):
        _, _, rest = src_text.partition('"""\n')
        if rest:
            return HEADER + rest
    return HEADER + src_text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Fail if destination differs from source-derived content.")
    args = parser.parse_args()

    src_text = SRC.read_text(encoding="utf-8")
    expected = _expected_dst_content(src_text)
    current = DST.read_text(encoding="utf-8") if DST.exists() else ""

    if args.check:
        if current == expected:
            print("path contract sync check: OK")
            return 0
        print("path contract sync check: OUT OF DATE")
        diff = difflib.unified_diff(
            current.splitlines(),
            expected.splitlines(),
            fromfile=str(DST),
            tofile="expected(module_utils/path_contract.py)",
            lineterm="",
        )
        for line in diff:
            print(line)
        return 1

    DST.parent.mkdir(parents=True, exist_ok=True)
    DST.write_text(expected, encoding="utf-8")
    print(f"synced {SRC} -> {DST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
