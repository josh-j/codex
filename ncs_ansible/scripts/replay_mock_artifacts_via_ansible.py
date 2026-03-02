#!/usr/bin/env python3
"""Replay generated mock raw artifacts through Ansible callback emission."""

from __future__ import annotations

import argparse
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml


def _iter_raw_files(fixture_root: Path) -> list[Path]:
    return sorted((fixture_root / "platform").rglob("raw_*.yaml"))


def _parse_raw_path(raw_path: Path, fixture_root: Path) -> tuple[str, str, str]:
    rel = raw_path.relative_to(fixture_root)
    parts = rel.parts
    # platform/<platform...>/<host>/raw_<name>.yaml
    if len(parts) < 4 or parts[0] != "platform":
        raise ValueError(f"Unexpected raw path layout: {raw_path}")

    host = parts[-2]
    platform = "/".join(parts[1:-2])
    filename = parts[-1]
    if not filename.startswith("raw_") or not filename.endswith(".yaml"):
        raise ValueError(f"Unexpected raw filename: {raw_path}")
    name = filename[len("raw_") : -len(".yaml")]
    return host, platform, name


def _run(cmd: list[str]) -> None:
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(cmd)}")


def _write_temp_inventory(hosts: set[str]) -> str:
    inv_doc = {
        "all": {
            "hosts": {
                host: {
                    "ansible_connection": "local",
                }
                for host in sorted(hosts)
            }
        }
    }
    tmp = tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", prefix="ncs_sim_inv_", delete=False, encoding="utf-8")
    with tmp:
        yaml.safe_dump(inv_doc, tmp, sort_keys=False)
    return tmp.name


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay mock artifacts via ansible-playbook + set_stats callback.")
    parser.add_argument(
        "--inventory",
        default="",
        help=(
            "Optional; currently ignored (reserved for future inventory-aware replay). "
            "Replay host targeting is derived from fixture hostnames via a generated temporary local inventory."
        ),
    )
    parser.add_argument("--fixture-root", required=True, help="Fixture root containing platform/**/raw_*.yaml.")
    parser.add_argument("--out-root", required=True, help="Destination report root for callback emission.")
    parser.add_argument(
        "--ansible-playbook",
        default="ansible-playbook",
        help="Path to ansible-playbook binary.",
    )
    parser.add_argument(
        "--playbook",
        default="playbooks/simulated_emit_one_raw.yml",
        help="Playbook used to emit a single raw payload.",
    )
    args = parser.parse_args()
    if args.inventory:
        print("Warning: --inventory is currently ignored in replay mode.")

    fixture_root = Path(args.fixture_root).resolve()
    out_root = Path(args.out_root).resolve()
    playbook = str(Path(args.playbook).resolve())

    raws = _iter_raw_files(fixture_root)
    if not raws:
        print(f"No raw artifacts found under {fixture_root / 'platform'}")
        return 1

    parsed = [(*_parse_raw_path(raw, fixture_root), raw) for raw in raws]
    inv_hosts = {host for host, _, _, _ in parsed}
    temp_inventory = _write_temp_inventory(inv_hosts)

    emitted = 0
    try:
        for host, platform, name, raw in parsed:
            cmd = [
                args.ansible_playbook,
                "-i",
                temp_inventory,
                playbook,
                "-l",
                host,
                "-e",
                f"emit_platform={platform}",
                "-e",
                f"emit_name={name}",
                "-e",
                f"emit_payload_file={raw}",
                "-e",
                f"emit_report_directory={out_root}",
            ]
            _run(cmd)
            emitted += 1
    finally:
        Path(temp_inventory).unlink(missing_ok=True)

    print(f"Replayed {emitted} raw artifacts via ansible callback into {out_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
