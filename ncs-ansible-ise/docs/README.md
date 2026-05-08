# Cisco ISE Ansible References

This folder collects the reference material needed to build, run, and
maintain Ansible automation for Cisco Identity Services Engine (ISE).

## Files

- `REFERENCES.md` - authoritative source links and version notes.
- `QUICKSTART.md` - install, inventory, and first-playbook examples.
- `MODULE_CATALOG.md` - curated map of `cisco.ise` module families.
- `API_NOTES.md` - ISE API Gateway, ERS/OpenAPI, privileges, and
  versioning notes that affect Ansible automation.

## Current State

As of 2026-05-07, Ansible community docs for Ansible 12 say
`cisco.ise` has been removed from the bundled `ansible` package docs.
The collection can still be installed manually with:

```bash
ansible-galaxy collection install cisco.ise
```

The Ansible 11 hosted docs list `cisco.ise` collection version 2.10.0
and mark it unmaintained in the Ansible community bundle. A live Galaxy
install on 2026-05-07 resolved `cisco.ise` 3.1.0. Cisco's upstream
repository continues to publish the Cisco ISE collection source and
compatibility matrix.
