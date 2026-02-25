# collections/ansible_collections/internal/core/plugins/lookup/schema_path.py

from __future__ import annotations

import os
from collections.abc import Sequence
from typing import Any

from ansible.errors import AnsibleError
from ansible.plugins.lookup import LookupBase


def _as_list(x: Any) -> list[str]:
    """Normalize string|list into list[str]."""
    if x is None:
        return []
    if isinstance(x, str):
        s = x.strip()
        return [s] if s else []
    if isinstance(x, Sequence) and not isinstance(x, (str, bytes)):
        out: list[str] = []
        for i in x:
            if i is None:
                continue
            s = str(i).strip()
            if s:
                out.append(s)
        return out
    s = str(x).strip()
    return [s] if s else []


def _split_ref(ref: str) -> tuple[list[str], str] | None:
    """
    Parse:
      - "ns.coll:relpath"        -> parts=["ns","coll"]
      - "ns.coll.role:relpath"   -> parts=["ns","coll","role"]
    """
    if ":" not in ref:
        return None
    left, rel = ref.split(":", 1)
    parts = left.split(".")
    if len(parts) not in (2, 3):
        return None
    rel = rel.lstrip("/")  # normalize
    return parts, rel


def _find_repo_roots(start_dir: str, max_up: int = 6) -> list[str]:
    """
    Walk up from start_dir looking for a repo root containing:
      collections/ansible_collections
    """
    roots: list[str] = []
    cur = os.path.realpath(start_dir)

    for _ in range(max_up + 1):
        marker = os.path.join(cur, "collections", "ansible_collections")
        if os.path.isdir(marker):
            roots.append(cur)
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent

    # De-dup while preserving order
    seen = set()
    out: list[str] = []
    for r in roots:
        if r not in seen:
            seen.add(r)
            out.append(r)
    return out


def _is_within(path: str, base: str) -> bool:
    """Basic traversal guard: path must be inside base directory."""
    base_real = os.path.realpath(base) + os.sep
    path_real = os.path.realpath(path)
    return path_real.startswith(base_real)


class LookupModule(LookupBase):
    def run(self, terms: list[Any], variables=None, **kwargs):
        """
        Usage:
          lookup('internal.core.schema_path', schema_ref, schema_path=schema_path)

        Args:
          terms: primary candidates (schema_ref or paths), string or list
          schema_path: optional fallback candidate(s), string or list
          playbook_dir: optional override; defaults to loader basedir
          collections_paths: optional override list; defaults to ANSIBLE_COLLECTIONS_PATHS env
          max_parent_depth: optional; default 6
        """
        playbook_dir = kwargs.get("playbook_dir")
        if not playbook_dir and self._loader:
            playbook_dir = self._loader.get_basedir()

        if not playbook_dir:
            playbook_dir = os.getcwd()

        max_parent_depth = int(kwargs.get("max_parent_depth", 6))

        collections_paths = _as_list(kwargs.get("collections_paths"))
        if not collections_paths:
            env = os.environ.get("ANSIBLE_COLLECTIONS_PATHS", "")
            collections_paths = [p for p in env.split(":") if p]

        # candidates are checked in order
        candidates = _as_list(terms) + _as_list(kwargs.get("schema_path"))

        repo_roots = _find_repo_roots(playbook_dir, max_up=max_parent_depth)

        attempted: list[str] = []

        for item in candidates:
            parsed = _split_ref(item)
            if parsed:
                parts, rel = parsed

                # Build base dirs depending on whether ref is collection-scoped or role-scoped
                if len(parts) == 2:
                    ns, coll = parts
                    bases = [
                        os.path.join(r, "collections", "ansible_collections", ns, coll)
                        for r in repo_roots
                    ] + [
                        os.path.join(cp, "ansible_collections", ns, coll)
                        for cp in collections_paths
                    ]
                else:
                    ns, coll, role = parts
                    bases = [
                        os.path.join(
                            r,
                            "collections",
                            "ansible_collections",
                            ns,
                            coll,
                            "roles",
                            role,
                        )
                        for r in repo_roots
                    ] + [
                        os.path.join(cp, "ansible_collections", ns, coll, "roles", role)
                        for cp in collections_paths
                    ]

                for base in bases:
                    candidate_path = os.path.join(base, rel)
                    attempted.append(candidate_path)

                    # Traversal guard: rel must not escape base
                    if not _is_within(candidate_path, base):
                        continue

                    if os.path.isfile(candidate_path):
                        return [os.path.realpath(candidate_path)]

                continue

            # Plain file path candidate (absolute or relative to playbook_dir)
            if os.path.isabs(item):
                candidate_path = os.path.realpath(item)
            else:
                candidate_path = os.path.realpath(os.path.join(playbook_dir, item))

            attempted.append(candidate_path)
            if os.path.isfile(candidate_path):
                return [candidate_path]

        raise AnsibleError(
            "schema_path lookup: no candidate matched. "
            f"candidates={candidates}, playbook_dir={playbook_dir}, attempted={attempted[:20]}"
        )
