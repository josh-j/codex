#!/usr/bin/env python3
"""Verify ncs_reporter configs/scripts are in sync with files/ncs_reporter_configs/.

ncs_reporter/src/ncs_reporter/ is the single source of truth.
files/ncs_reporter_configs/ is the runtime copy used by ncs_collector.

Exit 0 if in sync, exit 1 with details if not.
Use --fix to copy source → destination automatically.
"""

from __future__ import annotations

import argparse
import filecmp
import shutil
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

SYNC_PAIRS: list[tuple[Path, Path, str]] = [
    (
        REPO_ROOT / "ncs_reporter" / "src" / "ncs_reporter" / "configs",
        REPO_ROOT / "files" / "ncs_reporter_configs",
        "*.yaml",
    ),
    (
        REPO_ROOT / "ncs_reporter" / "src" / "ncs_reporter" / "scripts",
        REPO_ROOT / "files" / "ncs_reporter_configs" / "scripts",
        "*.py",
    ),
]


def check_sync(fix: bool = False) -> list[str]:
    """Return list of error messages for out-of-sync files."""
    errors: list[str] = []

    for src_dir, dst_dir, glob in SYNC_PAIRS:
        if not src_dir.is_dir():
            errors.append(f"Source directory missing: {src_dir}")
            continue

        src_files = {f.name: f for f in src_dir.glob(glob)}
        dst_files = {f.name: f for f in dst_dir.glob(glob)} if dst_dir.is_dir() else {}

        # Check each source file is present and identical in destination.
        for name, src_path in sorted(src_files.items()):
            dst_path = dst_dir / name
            if name not in dst_files:
                errors.append(f"Missing: {dst_path.relative_to(REPO_ROOT)}  (source: {src_path.relative_to(REPO_ROOT)})")
                if fix:
                    dst_path.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src_path, dst_path)
            elif not filecmp.cmp(src_path, dst_path, shallow=False):
                errors.append(f"Differs: {dst_path.relative_to(REPO_ROOT)}  (source: {src_path.relative_to(REPO_ROOT)})")
                if fix:
                    shutil.copy2(src_path, dst_path)

    return errors


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fix",
        action="store_true",
        help="Copy source files to destination to fix drift.",
    )
    args = parser.parse_args()

    errors = check_sync(fix=args.fix)

    if not errors:
        print("ncs_reporter configs/scripts are in sync.")
        raise SystemExit(0)

    label = "Fixed" if args.fix else "Out of sync"
    for msg in errors:
        print(f"  {label}: {msg}", file=sys.stderr)

    if args.fix:
        print(f"\n{len(errors)} file(s) fixed.", file=sys.stderr)
        raise SystemExit(0)

    print(
        f"\n{len(errors)} file(s) out of sync. "
        "Run 'python scripts/check_config_sync.py --fix' or copy manually.",
        file=sys.stderr,
    )
    raise SystemExit(1)


if __name__ == "__main__":
    main()
