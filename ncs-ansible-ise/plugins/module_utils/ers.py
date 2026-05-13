# -*- coding: utf-8 -*-
"""Shared HTTP client + helpers for the ERS API on Cisco ISE.

Used by both ``plugins/modules/ise_network_devices_info`` (the per-task
module that powers nad_missing_protocols and the NAD-lookup ops) and
``plugins/inventory/ise_nads`` (the inventory plugin that turns the same
NAD population into Ansible inventory groups).
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


def first(row: Any, paths: list[str], default: Any = "") -> Any:
    """Return the first dotted-path lookup that yields a non-empty value."""
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


def first_ip(nd: dict[str, Any]) -> str:
    """Pick the first IP from a NetworkDevice's IP list, tolerating ERS /
    OpenAPI casing variants for both the wrapping key and the inner field."""
    ip_list = first(nd, ["NetworkDeviceIPList", "networkDeviceIPList"], [])
    if isinstance(ip_list, list) and ip_list and isinstance(ip_list[0], dict):
        return first(ip_list[0], ["ipaddress", "ipAddress", "ip"], "")
    return ""


class ErsClient:
    """Minimal stdlib-only HTTPS client for the ERS API.

    Pre-builds the Basic-auth header and an SSL context once at
    construction time so the GET fast path is just ``urllib_request.urlopen``
    with no per-call setup. Errors surface as :class:`RuntimeError` with
    the URL embedded so the caller can collect them per-MAC / per-NAD
    instead of failing the whole run on one bad fetch.
    """

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


def list_nads(
    client: ErsClient,
    page_size: int = 100,
    max_pages: int = 100,
    name_filter: str = "",
) -> tuple[int, list[dict[str, Any]]]:
    """Walk ``/ers/config/networkdevice`` to completion.

    Returns ``(total, summaries)``. ``name_filter`` translates to the ERS
    server-side ``filter=name.CONTAINS.<value>`` parameter so NAD lookups
    don't have to download the full fleet to narrow on the client side.
    ``max_pages`` is a defense-in-depth cap against a runaway ``total``.
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


def fetch_detail(client: ErsClient, nad_id: str) -> dict[str, Any]:
    """Return the ``NetworkDevice`` body for one NAD id."""
    body = client.get_json(f"/ers/config/networkdevice/{nad_id}")
    return body.get("NetworkDevice") or {}


def fetch_details_concurrent(
    client: ErsClient,
    summaries: list[dict[str, Any]],
    max_workers: int = 16,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fan ``fetch_detail`` out across *summaries* via :class:`ThreadPoolExecutor`.

    Returns ``(details, errors)`` where each error is
    ``{"id": <nad_id>, "name": <nad_name>, "error": <str>}`` — so the caller
    can decide whether one bad NAD should abort the whole run.
    """
    ids: list[tuple[str, str]] = [
        (str(s.get("id")), str(s.get("name") or ""))
        for s in summaries
        if isinstance(s, dict) and s.get("id")
    ]
    details: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    workers = max(1, int(max_workers))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(fetch_detail, client, nad_id): (nad_id, name) for nad_id, name in ids}
        for fut in as_completed(futures):
            nad_id, name = futures[fut]
            try:
                details.append(fut.result())
            except Exception as exc:
                errors.append({"id": nad_id, "name": name, "error": str(exc)})
    return details, errors


# ---------------------------------------------------------------------------
# NetworkDeviceGroupList parsing.
#
# ISE concatenates NDG hierarchies as ``#``-separated strings, where the
# first segment is the category (``Location``, ``Device Type``, ``Ops Owner``,
# ``IPSEC``, …). We need a few of these flattened to leaf values for both
# the audit module's row shape and the inventory plugin's groupings.
# ---------------------------------------------------------------------------


def parse_ndg_list(groups: Any) -> dict[str, str]:
    """Return ``{"location": ..., "device_type": ..., "ops_owner": ...}``
    extracted from an ISE ``NetworkDeviceGroupList`` (list of
    ``Category#All Categories#Leaf...`` strings)."""
    out = {"location": "", "device_type": "", "ops_owner": ""}
    if not isinstance(groups, list):
        return out
    for g in groups:
        if not isinstance(g, str):
            continue
        parts = g.split("#")
        if not parts:
            continue
        head = parts[0]
        if head == "Location" and len(parts) > 2:
            # "Location#All Locations#Country#Site#Building"
            #   → "Country#Site#Building"
            out["location"] = "#".join(parts[2:])
        elif head == "Device Type" and len(parts) > 2:
            out["device_type"] = parts[-1]
        elif head == "Ops Owner" and len(parts) > 2:
            out["ops_owner"] = parts[-1]
    return out
