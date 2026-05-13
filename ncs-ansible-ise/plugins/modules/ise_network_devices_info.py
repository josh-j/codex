#!/usr/bin/python
"""List Cisco ISE NADs with per-device RADIUS/TACACS configuration status.

Replaces the previous async + async_status fan-out the ``nad_missing_protocols``
one-off used to drive. ERS exposes only ``{id, name, link}`` in its list call,
so the per-NAD detail fetch is unavoidable; doing the fan-out inside a single
Ansible task with ``concurrent.futures`` removes the per-iteration loop overhead
and the ``delay: 2`` async_status polling that dominated wall-clock on large
fleets.
"""

from __future__ import annotations

from typing import Any

from ansible.module_utils.basic import AnsibleModule
from ansible_collections.internal.ise.plugins.module_utils.ers import (
    ErsClient,
    fetch_details_concurrent,
    first,
    first_ip,
    list_nads,
)


DOCUMENTATION = r"""
---
module: ise_network_devices_info
short_description: List ISE NADs and audit their RADIUS/TACACS configuration
description:
  - Lists every Network Access Device known to the ISE PAN via the ERS API,
    fetches per-NAD detail in parallel, and returns rows shaped for the
    ncs-console "NADs Missing RADIUS/TACACS" one-off report.
  - The ERS list endpoint returns only C({id, name, link}); the
    C(authenticationSettings) (RADIUS) and C(tacacsSettings) (TACACS) keys
    live on the per-id detail body, so a per-NAD detail fetch is required.
options:
  hostname:
    description: ISE Primary Admin Node hostname (serves ERS).
    type: str
    required: true
  port:
    description: ERS port (defaults to ISE's stock 9060).
    type: int
    default: 9060
  username:
    description: ERS API username.
    type: str
    required: true
  password:
    description: ERS API password. Marked C(no_log).
    type: str
    required: true
    no_log: true
  validate_certs:
    description: Verify the PAN's TLS certificate.
    type: bool
    default: false
  request_timeout:
    description: Per-request HTTPS timeout in seconds.
    type: int
    default: 60
  max_workers:
    description: ThreadPoolExecutor worker count for detail fetches.
    type: int
    default: 16
  page_size:
    description: ERS page size for the list call (ISE caps at 100).
    type: int
    default: 100
  max_pages:
    description: Hard cap on pages walked, in case ISE reports a runaway total.
    type: int
    default: 100
  name_filter:
    description:
      - Narrow the list to NADs whose C(name) contains this substring (ERS
        server-side C(filter=name.CONTAINS.<value>)). Leave blank for the
        full fleet.
    type: str
    default: ""
  include_settings:
    description:
      - When false, skip the per-NAD detail fan-out and return ERS summaries
        only. The C(has_radius)/C(has_tacacs)/C(missing_protocols) columns
        will be empty in that mode; callers that don't need those columns
        avoid an N-request fan-out.
    type: bool
    default: true
author:
  - NCS
"""

RETURN = r"""
total:
  description: ERS-reported total NAD count.
  returned: always
  type: int
fetched:
  description: Number of detail rows successfully retrieved.
  returned: always
  type: int
rows:
  description:
    - One entry per NAD, sorted by name. Shape matches the row contract the
      ncs-reporter nad_missing_protocols report expects.
  returned: always
  type: list
  elements: dict
errors:
  description: NADs whose detail fetch failed, with the error string.
  returned: always
  type: list
  elements: dict
"""


def _row(nd: dict[str, Any], include_settings: bool = True) -> dict[str, Any]:
    """Shape one NAD detail body into the audit row contract."""
    row: dict[str, Any] = {
        "name": first(nd, ["name"], ""),
        "id": first(nd, ["id"], ""),
        "ip_address": first_ip(nd),
        "description": first(nd, ["description"], ""),
        "location": first(nd, ["location"], ""),
        "type": first(nd, ["type"], ""),
        "profile_name": first(nd, ["profileName"], ""),
        "model_name": first(nd, ["modelName"], ""),
    }
    if include_settings:
        has_radius = "authenticationSettings" in nd
        has_tacacs = "tacacsSettings" in nd
        missing: list[str] = []
        if not has_radius:
            missing.append("RADIUS")
        if not has_tacacs:
            missing.append("TACACS")
        row["has_radius"] = has_radius
        row["has_tacacs"] = has_tacacs
        row["missing_protocols"] = ", ".join(missing)
    return row


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "hostname": {"type": "str", "required": True},
            "port": {"type": "int", "default": 9060},
            "username": {"type": "str", "required": True},
            "password": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": False},
            "request_timeout": {"type": "int", "default": 60},
            "max_workers": {"type": "int", "default": 16},
            "page_size": {"type": "int", "default": 100},
            "max_pages": {"type": "int", "default": 100},
            "name_filter": {"type": "str", "default": ""},
            "include_settings": {"type": "bool", "default": True},
        },
        supports_check_mode=True,
    )
    p = module.params
    client = ErsClient(
        base_url=f"https://{p['hostname']}:{p['port']}",
        username=p["username"],
        password=p["password"],
        validate_certs=bool(p["validate_certs"]),
        timeout=int(p["request_timeout"]),
    )

    try:
        total, summaries = list_nads(
            client,
            int(p["page_size"]),
            int(p["max_pages"]),
            str(p["name_filter"] or ""),
        )
    except Exception as exc:
        module.fail_json(msg=str(exc), changed=False, total=0, fetched=0, rows=[], errors=[])

    include_settings = bool(p["include_settings"])
    rows: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []

    if not include_settings:
        # Skip the N detail GETs — return summaries shaped to the row contract.
        for s in summaries:
            if isinstance(s, dict):
                rows.append(_row(s, include_settings=False))
    else:
        details, errors = fetch_details_concurrent(client, summaries, int(p["max_workers"]))
        for nd in details:
            rows.append(_row(nd, include_settings=True))

    rows.sort(key=lambda r: (r.get("name") or "").lower())

    module.exit_json(
        changed=False,
        total=total,
        fetched=len(rows),
        rows=rows,
        errors=errors,
    )


def main() -> None:
    run_module()


if __name__ == "__main__":
    main()
