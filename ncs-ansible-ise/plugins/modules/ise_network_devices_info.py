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

import json
import ssl
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote as urlquote

from ansible.module_utils.basic import AnsibleModule


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


def _first(row: Any, paths: list[str], default: Any = "") -> Any:
    for path in paths:
        cur = row
        ok = True
        for part in path.split("."):
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                ok = False
                break
        if ok and cur not in (None, "", [], {}):
            return cur
    return default


def _first_ip(nd: dict[str, Any]) -> str:
    # ERS sometimes wraps the IP list under NetworkDeviceIPList, OpenAPI under
    # networkDeviceIPList; the inner field name also drifts (ipaddress / ipAddress / ip).
    ip_list = _first(nd, ["NetworkDeviceIPList", "networkDeviceIPList"], [])
    if isinstance(ip_list, list) and ip_list and isinstance(ip_list[0], dict):
        return _first(ip_list[0], ["ipaddress", "ipAddress", "ip"], "")
    return ""


def _row(nd: dict[str, Any], include_settings: bool = True) -> dict[str, Any]:
    row: dict[str, Any] = {
        "name": _first(nd, ["name"], ""),
        "id": _first(nd, ["id"], ""),
        "ip_address": _first_ip(nd),
        "description": _first(nd, ["description"], ""),
        "location": _first(nd, ["location"], ""),
        "type": _first(nd, ["type"], ""),
        "profile_name": _first(nd, ["profileName"], ""),
        "model_name": _first(nd, ["modelName"], ""),
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


class _Client:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        validate_certs: bool,
        timeout: int,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.headers = {
            "Authorization": f"Basic {token}",
            "Accept": "application/json",
        }
        if validate_certs:
            self.ctx: ssl.SSLContext = ssl.create_default_context()
        else:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def get_json(self, path: str) -> dict[str, Any]:
        url = f"{self.base_url}{path}"
        req = urllib_request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib_request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                body = resp.read().decode("utf-8")
        except urllib_error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} GET {url}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"network error GET {url}: {exc.reason}") from exc
        try:
            return json.loads(body) if body else {}
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"invalid JSON from {url}: {exc}") from exc


def _list_nads(
    client: _Client,
    page_size: int,
    max_pages: int,
    name_filter: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    """Walk the ERS NAD list endpoint to completion. Returns (total, summaries).

    When *name_filter* is non-empty, the ERS C(filter=name.CONTAINS.<value>)
    parameter is appended so the server narrows the list before pagination.
    Bypasses the page-1 cap that the playbook used to hit when a NAD lived
    on page 2+.
    """
    base = f"/ers/config/networkdevice?size={page_size}"
    if name_filter:
        base += f"&filter=name.CONTAINS.{urlquote(name_filter, safe='')}"
    page1 = client.get_json(f"{base}&page=1")
    sr = page1.get("SearchResult") or {}
    summaries: list[dict[str, Any]] = list(sr.get("resources") or [])
    total = int(sr.get("total") or len(summaries))
    pages = (total + page_size - 1) // page_size if total > 0 else 1
    pages = min(pages, max_pages)
    for page in range(2, pages + 1):
        body = client.get_json(f"{base}&page={page}")
        summaries.extend((body.get("SearchResult") or {}).get("resources") or [])
    return total, summaries


def _fetch_detail(client: _Client, nad_id: str) -> dict[str, Any]:
    body = client.get_json(f"/ers/config/networkdevice/{nad_id}")
    return body.get("NetworkDevice") or {}


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
    base_url = f"https://{p['hostname']}:{p['port']}"
    client = _Client(
        base_url=base_url,
        username=p["username"],
        password=p["password"],
        validate_certs=bool(p["validate_certs"]),
        timeout=int(p["request_timeout"]),
    )

    try:
        total, summaries = _list_nads(
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
        ids: list[tuple[str, str]] = [
            (str(s.get("id")), str(s.get("name") or ""))
            for s in summaries
            if isinstance(s, dict) and s.get("id")
        ]
        workers = max(1, int(p["max_workers"]))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(_fetch_detail, client, nad_id): (nad_id, name) for nad_id, name in ids}
            for fut in as_completed(futures):
                nad_id, name = futures[fut]
                try:
                    rows.append(_row(fut.result(), include_settings=True))
                except Exception as exc:
                    errors.append({"id": nad_id, "name": name, "error": str(exc)})

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
