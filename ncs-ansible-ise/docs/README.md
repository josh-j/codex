# Cisco ISE — Ansible Reference Notes

Background material for building, running, and maintaining the
`internal.ise` collection against Cisco Identity Services Engine.

## Files

- `REFERENCES.md` — authoritative source links and version notes.
- `QUICKSTART.md` — install, inventory, and first-playbook examples.
- `MODULE_CATALOG.md` — historical map of `cisco.ise` module families
  (kept as a cross-reference; the role itself no longer calls them).
- `API_NOTES.md` — API Gateway, ERS/OpenAPI/MnT surfaces, required
  permissions, and versioning notes that affect direct HTTP access.

## Current state

The `internal.ise` role does **not** depend on the upstream `cisco.ise`
collection or the `ciscoisesdk` Python package. Every API call is made
through `ansible.builtin.uri` directly against one of three ISE HTTP
surfaces:

| Surface  | Port | Path prefix              | Body |
|----------|------|--------------------------|------|
| ERS      | 9060 | `/ers/config/...`        | JSON |
| OpenAPI  | 443  | `/api/v1/...`            | JSON |
| MnT XML  | 443  | `/admin/API/mnt/...`     | XML  |

This avoids the SDK-version coupling that broke `mnt_*_info` and
related modules whenever the deployment's installed `ciscoisesdk`
didn't expose the method signature the cisco.ise collection expected
(e.g. `'Misc' object has no attribute 'get_product_version'`).

`MODULE_CATALOG.md` is retained because it remains a useful index of
which ISE API resources exist; just remember the role talks to those
resources via raw `uri`, not via `cisco.ise.*` modules.
