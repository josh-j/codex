#!/usr/bin/env python3
"""Extract an ansible-galaxy collection tarball into a source-shaped tree.

`ansible-galaxy collection build` produces distribution tarballs that contain
`MANIFEST.json` and `FILES.json` in place of the source `galaxy.yml`. When we
want to reconstruct a SOURCE repo from a tarball (the use case for
`just place-collection-siblings`), we need the reverse transform:

- extract the tarball
- reconstruct `galaxy.yml` from `MANIFEST.json.collection_info`
- delete `MANIFEST.json` and `FILES.json` (build-time artifacts)

Usage:
    python scripts/extract_collection_tarball.py <tarball> <dest_dir>
"""

from __future__ import annotations

import json
import pathlib
import shutil
import sys
import tarfile

import yaml


def main(argv: list[str]) -> int:
    if len(argv) != 3:
        print(f"usage: {argv[0]} <tarball> <dest_dir>", file=sys.stderr)
        return 2

    tarball = pathlib.Path(argv[1])
    dest = pathlib.Path(argv[2])

    if not tarball.is_file():
        print(f"tarball not found: {tarball}", file=sys.stderr)
        return 1

    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)

    with tarfile.open(tarball, "r:gz") as tf:
        tf.extractall(dest, filter="data")

    manifest_path = dest / "MANIFEST.json"
    files_path = dest / "FILES.json"
    galaxy_path = dest / "galaxy.yml"

    if not manifest_path.is_file():
        print(f"{tarball}: no MANIFEST.json inside — not a collection tarball?", file=sys.stderr)
        return 1

    manifest = json.loads(manifest_path.read_text())
    info = manifest.get("collection_info") or {}
    if not info:
        print(f"{tarball}: MANIFEST.json missing collection_info", file=sys.stderr)
        return 1

    # Drop fields that only make sense inside a built manifest.
    for key in ("issues", "documentation", "homepage"):
        if key in info and info[key] is None:
            del info[key]

    galaxy_path.write_text(yaml.safe_dump(info, sort_keys=False))
    manifest_path.unlink()
    files_path.unlink(missing_ok=True)

    print(f"{dest}: reconstructed galaxy.yml from MANIFEST.json")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
