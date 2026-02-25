import os


def resolve_schema_path(ref, playbook_dir=None):
    """
    Simplified schema resolution for filters and lookups.
    Supports internal.linux:schemas/ubuntu_ctx.yaml style refs.
    """
    if not ref:
        return None

    if ":" not in ref:
        # Assume it's a plain path
        if os.path.isabs(ref):
            return ref if os.path.isfile(ref) else None
        if playbook_dir:
            path = os.path.join(playbook_dir, ref)
            return path if os.path.isfile(path) else None
        return None

    # Parse internal.linux:schemas/path
    left, rel = ref.split(":", 1)
    parts = left.split(".")
    rel = rel.lstrip("/")

    # Find the project root by looking for 'collections/ansible_collections'
    cur = os.path.realpath(__file__)
    repo_root = None
    for _ in range(7):
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
        if os.path.isdir(os.path.join(cur, "collections", "ansible_collections")):
            repo_root = cur
            break

    if not repo_root:
        return None

    if len(parts) == 2:
        ns, coll = parts
        base = os.path.join(repo_root, "collections", "ansible_collections", ns, coll)
    elif len(parts) == 3:
        ns, coll, role = parts
        base = os.path.join(repo_root, "collections", "ansible_collections", ns, coll, "roles", role)
    else:
        return None

    path = os.path.join(base, rel)
    return path if os.path.isfile(path) else None
