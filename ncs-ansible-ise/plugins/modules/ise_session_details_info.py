#!/usr/bin/python
"""Fetch full Cisco ISE MnT session detail for every active session on one or
more NADs, in parallel.

MnT C(Session/ActiveList) is intentionally condensed — it carries only
C(user), C(calling_station_id), C(nas_ip_address), C(framed_ip_address),
C(audit_session_id), C(server) per row, so reports that render columns like
C(port), C(vlan), C(authentication_protocol), C(authorization_profile),
C(matched_rule), C(session_state), etc., end up with everything blank when
the source is ActiveList alone. The only MnT path that returns full session
detail for *any* MAC is C(Session/MACAddress/<mac>), which is per-call.

This module does the N+1 fan-out (list once, then per-MAC detail in a
C(ThreadPoolExecutor)) so the playbook gets one task instead of a sequential
C(async_status) harvest. Filter by C(nad_ip_filter) so we don't fan out
across the entire fleet when the caller already knows which NAD(s) it cares
about — typical case for the C(nad_endpoint_inventory) one-off.
"""

from __future__ import annotations

import re
import ssl
from base64 import b64encode
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any
from urllib import error as urllib_error
from urllib import request as urllib_request
from urllib.parse import quote as urlquote
from xml.etree import ElementTree as ET

from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r"""
---
module: ise_session_details_info
short_description: Fetch full MnT session detail for active sessions on a NAD
description:
  - Lists active sessions via the MnT C(/admin/API/mnt/Session/ActiveList)
    endpoint, optionally narrows by C(nas_ip_address), then fetches the full
    per-session detail via C(/admin/API/mnt/Session/MACAddress/<mac>) in
    parallel.
  - Returns parsed session dicts with the full set of MnT element names so
    the existing C(ise_auth_rows) filter shapes them identically to other
    auth/session sources.
options:
  hostname:
    description: ISE Monitoring (MnT) node hostname.
    type: str
    required: true
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
    description: Verify the MnT node's TLS certificate.
    type: bool
    default: false
  request_timeout:
    description: Per-request HTTPS timeout in seconds.
    type: int
    default: 60
  max_workers:
    description: ThreadPoolExecutor worker count for per-MAC detail fetches.
    type: int
    default: 16
  nad_ip_filter:
    description:
      - List of NAD IPs (as strings). When non-empty, sessions whose
        C(nas_ip_address) is not in the set are dropped before the detail
        fan-out, bounding the cost to "sessions on this NAD" rather than the
        whole fleet.
    type: list
    elements: str
    default: []
  max_sessions:
    description: Hard cap on detail fetches, defense-in-depth against runaway lists.
    type: int
    default: 5000
author:
  - NCS
"""

RETURN = r"""
active_total:
  description: Number of sessions in the ActiveList payload (pre-filter).
  returned: always
  type: int
filtered:
  description: Number of sessions after C(nad_ip_filter) narrowing.
  returned: always
  type: int
fetched:
  description: Number of detail fetches that returned a session body.
  returned: always
  type: int
sessions:
  description:
    - Parsed session detail dicts. Element names come straight from the MnT
      XML; pipe through C(internal.ise.ise_auth_rows) to reshape into the
      report row contract.
  returned: always
  type: list
  elements: dict
errors:
  description: Per-MAC failures, with the error string.
  returned: always
  type: list
  elements: dict
"""


_MAC_CHARS_RE = re.compile(r"[^0-9A-Fa-f]")


def _normalize_mac(value: Any) -> str:
    """Strip non-hex chars and re-format as the uppercase colon form ISE accepts."""
    if value in (None, ""):
        return ""
    hex_only = _MAC_CHARS_RE.sub("", str(value)).upper()
    if len(hex_only) != 12:
        return ""
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def _parse_row_xml(content: str) -> dict[str, Any]:
    """Parse a C(<sessionParameters>) (or similar) leaf-element doc into a dict.

    Returns an empty dict on parse failure rather than raising — callers
    collect parse errors via the C(errors) return.
    """
    if not content or not content.strip():
        return {}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}
    return {child.tag: (child.text or "") for child in root if not list(child)}


def _parse_active_list_xml(content: str) -> list[dict[str, Any]]:
    """Parse an C(<activeList>) XML body into a list of leaf-element dicts."""
    if not content or not content.strip():
        return []
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []
    sessions: list[dict[str, Any]] = []
    for row in root:
        if not list(row):
            continue
        sessions.append({child.tag: (child.text or "") for child in row if not list(child)})
    return sessions


class _Client:
    def __init__(self, hostname: str, username: str, password: str, validate_certs: bool, timeout: int) -> None:
        self.base_url = f"https://{hostname.rstrip('/')}"
        self.timeout = timeout
        token = b64encode(f"{username}:{password}".encode("utf-8")).decode("ascii")
        self.headers = {"Authorization": f"Basic {token}", "Accept": "application/xml"}
        if validate_certs:
            self.ctx: ssl.SSLContext = ssl.create_default_context()
        else:
            self.ctx = ssl.create_default_context()
            self.ctx.check_hostname = False
            self.ctx.verify_mode = ssl.CERT_NONE

    def get_xml(self, path: str) -> str:
        url = f"{self.base_url}{path}"
        req = urllib_request.Request(url, headers=self.headers, method="GET")
        try:
            with urllib_request.urlopen(req, timeout=self.timeout, context=self.ctx) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urllib_error.HTTPError as exc:
            raise RuntimeError(f"HTTP {exc.code} GET {url}") from exc
        except urllib_error.URLError as exc:
            raise RuntimeError(f"network error GET {url}: {exc.reason}") from exc


def _list_active(client: _Client) -> list[dict[str, Any]]:
    return _parse_active_list_xml(client.get_xml("/admin/API/mnt/Session/ActiveList"))


def _fetch_detail(client: _Client, mac: str) -> dict[str, Any]:
    return _parse_row_xml(client.get_xml(f"/admin/API/mnt/Session/MACAddress/{urlquote(mac)}"))


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "hostname": {"type": "str", "required": True},
            "username": {"type": "str", "required": True},
            "password": {"type": "str", "required": True, "no_log": True},
            "validate_certs": {"type": "bool", "default": False},
            "request_timeout": {"type": "int", "default": 60},
            "max_workers": {"type": "int", "default": 16},
            "nad_ip_filter": {"type": "list", "elements": "str", "default": []},
            "max_sessions": {"type": "int", "default": 5000},
        },
        supports_check_mode=True,
    )
    p = module.params
    client = _Client(
        hostname=str(p["hostname"]),
        username=str(p["username"]),
        password=str(p["password"]),
        validate_certs=bool(p["validate_certs"]),
        timeout=int(p["request_timeout"]),
    )

    try:
        active = _list_active(client)
    except Exception as exc:
        module.fail_json(
            msg=str(exc),
            changed=False,
            active_total=0,
            filtered=0,
            fetched=0,
            sessions=[],
            errors=[],
        )

    active_total = len(active)
    ip_filter = {str(ip) for ip in (p.get("nad_ip_filter") or []) if ip}
    if ip_filter:
        narrowed = [s for s in active if str(s.get("nas_ip_address") or "") in ip_filter]
    else:
        narrowed = list(active)

    cap = max(0, int(p["max_sessions"]))
    if cap and len(narrowed) > cap:
        narrowed = narrowed[:cap]

    macs: list[str] = []
    seen: set[str] = set()
    for s in narrowed:
        mac = _normalize_mac(s.get("calling_station_id") or s.get("mac"))
        if mac and mac not in seen:
            seen.add(mac)
            macs.append(mac)

    sessions: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    workers = max(1, int(p["max_workers"]))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_fetch_detail, client, mac): mac for mac in macs}
        for fut in as_completed(futures):
            mac = futures[fut]
            try:
                detail = fut.result()
            except Exception as exc:
                errors.append({"mac": mac, "error": str(exc)})
                continue
            if not detail:
                # XML was empty or unparseable — keep the condensed ActiveList
                # row as a fallback so the report doesn't lose the session
                # entirely on a single bad detail call.
                fallback = next((s for s in narrowed if _normalize_mac(s.get("calling_station_id")) == mac), {})
                if fallback:
                    sessions.append(dict(fallback))
                continue
            sessions.append(detail)

    sessions.sort(key=lambda s: str(s.get("auth_acs_timestamp") or s.get("acs_timestamp") or ""), reverse=True)

    module.exit_json(
        changed=False,
        active_total=active_total,
        filtered=len(narrowed),
        fetched=len(sessions),
        sessions=sessions,
        errors=errors,
    )


def main() -> None:
    run_module()


if __name__ == "__main__":
    main()
