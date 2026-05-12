"""Filters for Cisco ISE one-off console reports."""

from __future__ import annotations

import re
import csv
import html
import io
from collections import Counter
from typing import Any


MAC_RANDOM_RE = re.compile(r"^[0-9a-f][26ae][:-]")
_MAC_CHARS_RE = re.compile(r"[^0-9A-Fa-f]")


def ise_normalize_mac(value: Any) -> str:
    """Return a MAC in ISE's canonical form (uppercase, colon-separated).

    Accepts inputs with dashes, dots, no separators, or already-canonical
    form. Returns empty string for anything that doesn't yield exactly
    12 hex digits — callers can then short-circuit instead of building
    a malformed URL.
    """
    if value in (None, ""):
        return ""
    hex_only = _MAC_CHARS_RE.sub("", str(value)).upper()
    if len(hex_only) != 12:
        return ""
    return ":".join(hex_only[i : i + 2] for i in range(0, 12, 2))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _get_path(row: Any, path: str, default: Any = "") -> Any:
    cur = row
    for part in path.split("."):
        if isinstance(cur, dict) and part in cur:
            cur = cur[part]
        else:
            return default
    return cur


def _first(row: dict[str, Any], paths: list[str], default: Any = "") -> Any:
    for path in paths:
        value = _get_path(row, path, None)
        if value not in (None, "", [], {}):
            return value
    return default


def _to_int(value: Any, default: int = 0) -> int:
    try:
        if value in (None, ""):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return " ".join(_flatten_text(value))
    return str(value)


def _flatten_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, dict):
        out: list[str] = []
        for key, item in value.items():
            out.append(str(key))
            out.extend(_flatten_text(item))
        return out
    if isinstance(value, list):
        out = []
        for item in value:
            out.extend(_flatten_text(item))
        return out
    return [str(value)]


def _contains(row: dict[str, Any], query: str, fields: list[str] | None = None) -> bool:
    if not query:
        return True
    needle = query.lower()
    if fields:
        haystack = " ".join(_text(_get_path(row, field)) for field in fields).lower()
    else:
        haystack = _text(row).lower()
    return needle in haystack


def _normalize_location(loc: Any) -> str:
    """Strip ``All Locations#`` from the front of the per-session location
    hierarchy so it matches the format the NAD inventory emits.

    MnT Session/MACAddress returns ``location`` as
    ``All Locations#Germany#Ramstein AB#Bldg 313``. The NAD-inventory
    parser already strips ``Location#All Locations#`` from
    ``NetworkDeviceGroupList`` entries; keeping the session-side parity
    means PromQL / Jinja joins between the two work without per-call
    normalization.
    """
    if loc in (None, ""):
        return ""
    parts = str(loc).split("#")
    if parts and parts[0] == "All Locations" and len(parts) > 1:
        return "#".join(parts[1:])
    return str(loc)


def ise_normalize_location(loc: Any) -> str:
    """Public alias for :func:`_normalize_location`."""
    return _normalize_location(loc)


def _first_ip_address(nd: dict[str, Any]) -> str:
    """Return the first IP from a NetworkDevice's NetworkDeviceIPList,
    tolerating ERS / OpenAPI casing variants for the wrapping key and the
    inner ipaddress field."""
    ip_list = _first(nd, ["NetworkDeviceIPList", "networkDeviceIPList"], [])
    if isinstance(ip_list, list) and ip_list and isinstance(ip_list[0], dict):
        return _first(ip_list[0], ["ipaddress", "ipAddress", "ip"], "")
    return ""


def _parse_mnt_xml_rows(content: str) -> list[dict[str, Any]]:
    """Parse an ISE MnT XML response into a list of row dicts.

    Handles all four shapes MnT actually emits:

      * Flat row (e.g. /Session/MACAddress/<mac>, /Version) — root is the
        single row with leaf children directly.
      * 2-level wrapper (e.g. /Session/ActiveList, /FailureReasons) — root's
        children are rows whose children are leaves.
      * 3-level wrapper (e.g. /AuthStatus/...) — root has per-MAC
        ``<authStatusList key="...">`` wrappers, each of which contains one
        or more ``<authStatusElements>`` rows. Walking only two levels
        produced rows like ``{"authStatusElements": <whitespace>}`` — every
        downstream field lookup then resolved to empty, which is why the
        nad_policy_hits authc/authz/profile/policy_set summaries showed up
        empty even when the NAD had auth events.
      * Mixed / deeper nesting — the BFS below finds any node whose direct
        children are all leaves and emits it as a row.
    """
    from collections import deque
    from xml.etree import ElementTree as ET

    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return []

    children = list(root)
    if not children:
        return []

    # Flat-row case: root is a single row with leaf children.
    if any(not list(child) for child in children):
        return [{c.tag: (c.text or "") for c in root if not list(c)}]

    # Wrapper / nested-wrapper case: walk breadth-first until we find
    # nodes whose direct children are all leaves; emit each as a row.
    rows: list[dict[str, Any]] = []
    queue: deque[Any] = deque(children)
    while queue:
        node = queue.popleft()
        node_children = list(node)
        if not node_children:
            continue
        if all(not list(child) for child in node_children):
            rows.append({c.tag: (c.text or "") for c in node})
        else:
            queue.extend(node_children)
    return rows


def _parse_mnt_xml_root_leaves(content: str) -> dict[str, Any]:
    """Parse an MnT XML response whose root holds leaf children directly.

    Used for responses like /Version where the structure is:
    <product><name>...</name><version>...</version></product>
    Returns {'name': ..., 'version': ...}.
    """
    from xml.etree import ElementTree as ET

    if not isinstance(content, str) or not content.strip():
        return {}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {}

    if any(list(child) for child in root):
        return {}
    return {c.tag: c.text for c in root}


def ise_mnt_version(content: Any) -> dict[str, Any]:
    """Parse /admin/API/mnt/Version XML into the dict shape the reporter
    schema reads (mnt_version.ise_response.{name,version,type_of_node})."""
    return _parse_mnt_xml_root_leaves(content if isinstance(content, str) else "")


def ise_mnt_active_count(content: Any) -> dict[str, Any]:
    """Parse /Session/ActiveCount XML into {count: int}. The actual
    response shape is <sessionCount><count>N</count></sessionCount>
    (verified via Cisco DevNet Session-Management ref); root.text is
    just whitespace between elements, so we read root.find('count').text.
    """
    from xml.etree import ElementTree as ET

    if not isinstance(content, str) or not content.strip():
        return {"count": 0}
    try:
        root = ET.fromstring(content)
    except ET.ParseError:
        return {"count": 0}
    count_elem = root.find("count")
    raw = (count_elem.text or "").strip() if count_elem is not None else ""
    try:
        return {"count": int(raw)}
    except ValueError:
        return {"count": 0}


def ise_mnt_active_sessions(content: Any) -> dict[str, Any]:
    """Parse /Session/ActiveList XML into {activeList: [session, ...]} —
    matches the shape the reporter schema reads via
    active_sessions.ise_response.activeList."""
    if not isinstance(content, str):
        return {"activeList": []}
    return {"activeList": _parse_mnt_xml_rows(content)}


def ise_mnt_failure_reasons(content: Any) -> list[dict[str, Any]]:
    """Parse /FailureReasons XML into a flat list of failure_reason dicts."""
    if not isinstance(content, str):
        return []
    return _parse_mnt_xml_rows(content)


def ise_mnt_auth_status(content: Any) -> dict[str, Any]:
    """Parse /AuthStatus/... XML into a dict carrying the parsed records
    under the keys the schema's first_of chain looks for
    (authentications / sessions / response)."""
    if not isinstance(content, str):
        return {"authentications": []}
    rows = _parse_mnt_xml_rows(content)
    return {"authentications": rows, "sessions": rows, "response": rows}


def ise_result_rows(value: Any) -> list[Any]:
    """Unwrap common cisco.ise module result shapes into a list of rows."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if not isinstance(value, dict):
        return [value]

    # ansible.builtin.uri register with XML body (MnT endpoints): parse
    # the .content string into rows before falling through to dict unwrap.
    content = value.get("content")
    if isinstance(content, str) and content.lstrip().startswith("<"):
        rows = _parse_mnt_xml_rows(content)
        if rows:
            return rows

    for key in (
        "json",
        "ise_response",
        "ise_responses",
        "response",
        "authentications",
        "sessions",
        "activeList",
        "resources",
        "Resource",
        "SearchResult",
    ):
        if key not in value:
            continue
        nested = value[key]
        if key == "SearchResult" and isinstance(nested, dict):
            nested = nested.get("resources", nested.get("Resource", nested))
        rows = ise_result_rows(nested)
        if rows:
            return rows

    return [value]


def ise_endpoint_rows(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in ise_result_rows(value):
        if not isinstance(item, dict):
            continue
        mac = _first(item, ["mac", "macAddress", "calling_station_id", "callingStationId"])
        profile = _first(item, ["profile", "profileName", "endpointProfile", "deviceType"])
        group = _first(item, ["groupId", "group_id", "identityGroup", "identity_group"])
        identity_store = _first(item, ["identityStore", "identity_store"])
        repeat = _to_int(
            _first(
                item,
                [
                    "repeatCounter",
                    "repeat_counter",
                    "randomMacCount",
                    "customAttributes.repeatCounter",
                    "customAttributes.repeat_counter",
                    "customAttributes.randomMacCount",
                    "mdmAttributes.repeatCounter",
                ],
                0,
            )
        )
        rows.append(
            {
                "name": _first(item, ["name", "hostname", "hostName"]),
                "id": _first(item, ["id"]),
                "mac": mac,
                "ip_address": _first(item, ["ipAddress", "ip_address", "framed_ip_address"]),
                "profile": profile,
                "group": group,
                "identity_store": identity_store,
                "repeat_counter": repeat,
                "randomized_mac": bool(MAC_RANDOM_RE.search(str(mac).lower())),
                "default_policy_marker": "default"
                in f"{profile} {group} {identity_store}".lower(),
            }
        )
    return rows


def ise_network_device_rows(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in ise_result_rows(value):
        if not isinstance(item, dict):
            continue
        rows.append(
            {
                "name": _first(item, ["name"]),
                "id": _first(item, ["id"]),
                "description": _first(item, ["description"]),
                "ip_address": _first(item, ["ipaddress", "ipAddress"], _first_ip_address(item)),
                "location": _first(item, ["location"]),
                "type": _first(item, ["type"]),
                "groups": _first(item, ["NetworkDeviceGroupList", "networkDeviceGroupList"], []),
            }
        )
    return rows


def ise_auth_rows(value: Any) -> list[dict[str, Any]]:
    rows = []
    for item in ise_result_rows(value):
        if not isinstance(item, dict):
            continue
        # ISE MnT XML element names vary across ISE 3.1–3.5 and across
        # Session/ActiveList vs AuthStatus vs MACAddress vs UserName
        # endpoints. The fallback chains below cover the union of names
        # we've seen documented; whichever element the payload happens
        # to carry wins.
        status_raw = _first(
            item,
            [
                "status",
                "response",
                "session_state",
                "acct_status_type",
                "auth_status",
            ],
        )
        # passed/failed are boolean-strings in AuthStatus. Map them to
        # a human label when no explicit status field was present.
        if status_raw in (None, ""):
            passed = str(_first(item, ["passed"])).lower()
            failed = str(_first(item, ["failed"])).lower()
            if passed in {"true", "1"}:
                status_raw = "passed"
            elif failed in {"true", "1"}:
                status_raw = "failed"
        failure = _first(
            item,
            [
                "failure_reason",
                "failureReason",
                "FailureReason",
                "failed_reason",
                "failure_code",
                "auth_status_failure_reason",
            ],
        )
        rows.append(
            {
                "timestamp": _first(
                    item,
                    [
                        "auth_acs_timestamp",
                        "auth_acsview_timestamp",
                        "acs_timestamp",
                        "event_timestamp",
                        "acct_timestamp",
                        "timestamp",
                        "time",
                    ],
                ),
                "username": _first(
                    item,
                    [
                        "user_name",
                        "username",
                        "UserName",
                        "identity",
                        "calling_station_username",
                    ],
                ),
                "mac": _first(
                    item,
                    [
                        "calling_station_id",
                        "callingStationID",
                        "callingStationId",
                        "orig_calling_station_id",
                        "mac",
                        "mac_address",
                    ],
                ),
                "ip_address": _first(
                    item,
                    [
                        "framed_ip_address",
                        "framedIpAddress",
                        "ipAddress",
                        "ip_address",
                        "endpoint_ip",
                    ],
                ),
                "nad_name": _first(
                    item,
                    [
                        "network_device_name",
                        "NetworkDeviceName",
                        "nad_name",
                        "device_name",
                    ],
                ),
                "nad_ip": _first(
                    item,
                    [
                        "nas_ip_address",
                        "nasIpAddress",
                        "device_ip_address",
                        "nad_ip",
                        "called_station_id",
                    ],
                ),
                "server": _first(
                    item,
                    [
                        "acs_server",
                        "acsServer",
                        "server",
                        "serverhostname",
                        "psn",
                        "ise_node",
                    ],
                ),
                "destination_ip_address": _first(
                    item,
                    [
                        "destination_ip_address",
                        "destinationIpAddress",
                        "dest_ip_address",
                        "destination_ip",
                    ],
                ),
                "port": _first(
                    item,
                    [
                        "nas_port_id",
                        "nasPortId",
                        "nas_port",
                        "nasPort",
                        "port",
                        "interface",
                    ],
                ),
                "port_type": _first(item, ["nas_port_type", "nasPortType"]),
                "authentication_method": _first(
                    item,
                    [
                        "authentication_method",
                        "authenticationMethod",
                        "auth_method",
                    ],
                ),
                "authentication_protocol": _first(
                    item,
                    [
                        "authentication_protocol",
                        "authenticationProtocol",
                        "auth_protocol",
                    ],
                ),
                "identity_group": _first(
                    item,
                    [
                        "identity_group",
                        "identityGroup",
                        "user_identity_group",
                    ],
                ),
                "endpoint_policy": _first(item, ["endpoint_policy", "endpointPolicy"]),
                "cts_security_group": _first(item, ["cts_security_group", "ctsSecurityGroup", "sgt"]),
                "location": _normalize_location(_first(item, ["location", "Location"], "")),
                "device_type": _first(item, ["device_type", "deviceType"]),
                "audit_session_id": _first(
                    item,
                    [
                        "audit_session_id",
                        "auditSessionId",
                        "session_id",
                        "acct_session_id",
                    ],
                ),
                "session_state": _first(item, ["session_state", "sessionState"]),
                "vlan": _first(item, ["vlan", "vlan_id", "vlanId"]),
                "status": _text(status_raw),
                "failure_reason": failure,
                "authorization_profile": _first(
                    item,
                    [
                        "selected_azn_profiles",
                        "selected_authorization_profiles",
                        "selectedAuthorizationProfiles",
                        "authorization_profile",
                        "authorizationProfile",
                        "authz_profile",
                    ],
                ),
                # MnT carries authc and authz rules in distinct elements
                # (authentication_rule / authorization_rule) but the report's
                # legacy "matched_rule" column conflated them. Expose all
                # three: authentication_rule, authorization_rule, policy_set,
                # plus a compatibility-preserving matched_rule.
                "authentication_rule": _first(
                    item,
                    [
                        "authentication_rule",
                        "authenticationRule",
                        "authenticationPolicyMatchedRule",
                    ],
                ),
                "authorization_rule": _first(
                    item,
                    [
                        "authorization_rule",
                        "authorizationRule",
                        "authorizationPolicyMatchedRule",
                    ],
                ),
                "policy_set": _first(
                    item,
                    [
                        "policy_set_name",
                        "policySetName",
                        "policyset",
                    ],
                ),
                "matched_rule": _first(
                    item,
                    [
                        "authorization_rule",
                        "authorizationRule",
                        "authorizationPolicyMatchedRule",
                        "authentication_rule",
                        "authenticationRule",
                        "authenticationPolicyMatchedRule",
                        "matchedRule",
                        "auth_rule",
                        "policy_set_name",
                    ],
                ),
            }
        )
    return rows


def ise_coa_candidates(endpoint_rows: Any, session_rows: Any, query: str = "") -> list[dict[str, Any]]:
    """Resolve a MAC/IP/hostname selector to CoA target candidates."""
    matched_endpoints = ise_search_rows(endpoint_rows, query)
    matched_sessions = ise_search_rows(session_rows, query)
    endpoint_by_mac = {
        str(row.get("mac", "")).lower(): row
        for row in _as_list(endpoint_rows)
        if isinstance(row, dict) and row.get("mac")
    }
    matched_macs = {str(row.get("mac", "")).lower() for row in matched_endpoints if row.get("mac")}

    for row in _as_list(session_rows):
        if not isinstance(row, dict):
            continue
        mac = str(row.get("mac", "")).lower()
        if mac and mac in matched_macs and row not in matched_sessions:
            matched_sessions.append(row)

    candidates: list[dict[str, Any]] = []
    seen = set()
    for session in matched_sessions:
        mac = str(session.get("mac", ""))
        endpoint = endpoint_by_mac.get(mac.lower(), {})
        candidate = {
            "mac": mac,
            "name": endpoint.get("name", ""),
            "ip_address": session.get("ip_address") or endpoint.get("ip_address", ""),
            "username": session.get("username", ""),
            "server": session.get("server", ""),
            "nad_name": session.get("nad_name", ""),
            "nad_ip": session.get("nad_ip", ""),
            "port": session.get("port", ""),
            "status": session.get("status", ""),
            "destination_ip_address": session.get("destination_ip_address", ""),
            "profile": endpoint.get("profile", ""),
            "group": endpoint.get("group", ""),
        }
        key = (candidate["mac"], candidate["server"], candidate["nad_ip"], candidate["port"])
        if candidate["mac"] and key not in seen:
            seen.add(key)
            candidates.append(candidate)

    for endpoint in matched_endpoints:
        mac = str(endpoint.get("mac", ""))
        key = (mac, "", "", "")
        if mac and key not in seen:
            seen.add(key)
            candidates.append(
                {
                    "mac": mac,
                    "name": endpoint.get("name", ""),
                    "ip_address": endpoint.get("ip_address", ""),
                    "username": "",
                    "server": "",
                    "nad_name": "",
                    "nad_ip": "",
                    "port": "",
                    "status": "",
                    "destination_ip_address": "",
                    "profile": endpoint.get("profile", ""),
                    "group": endpoint.get("group", ""),
                }
            )

    return candidates


def ise_search_rows(rows: Any, query: str = "") -> list[dict[str, Any]]:
    return [row for row in _as_list(rows) if isinstance(row, dict) and _contains(row, query)]


def ise_nad_rows(rows: Any, nad_query: str = "") -> list[dict[str, Any]]:
    fields = ["nad_name", "nad_ip", "network_device_name", "nas_ip_address", "device_ip_address"]
    return [row for row in _as_list(rows) if isinstance(row, dict) and _contains(row, nad_query, fields)]


def ise_sessions_on_nads(rows: Any, nads: Any) -> list[dict[str, Any]]:
    """Filter sessions/auth rows to those whose NAD IP matches one of *nads*.

    MnT ``Session/ActiveList`` only carries ``nas_ip_address`` — no NAD name —
    so ``ise_nad_rows(query)`` matching on a name query yields nothing for
    ActiveList sessions. Caller passes the (already query-narrowed) NAD row
    list and we use the NAD ``ip_address`` field as the join key. NAD rows
    coming from ``ise_network_devices_info`` carry ``ip_address``; older
    paths via ``ise_network_device_rows`` use the same field.
    """
    nad_ips: set[str] = set()
    for nad in _as_list(nads):
        if not isinstance(nad, dict):
            continue
        ip = str(nad.get("ip_address") or "").strip()
        if ip:
            nad_ips.add(ip)
    if not nad_ips:
        return []
    return [
        row
        for row in _as_list(rows)
        if isinstance(row, dict)
        and str(row.get("nad_ip") or row.get("nas_ip_address") or "").strip() in nad_ips
    ]


def ise_port_rows(rows: Any, nad_query: str = "", port_query: str = "") -> list[dict[str, Any]]:
    return [
        row
        for row in ise_nad_rows(rows, nad_query)
        if isinstance(row, dict) and _contains(row, port_query, ["port", "nas_port_id", "nasPortId", "interface"])
    ]


def ise_default_policy_rows(rows: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_list(rows)
        if isinstance(row, dict)
        and (
            bool(row.get("default_policy_marker"))
            or "default"
            in f"{row.get('authorization_profile', '')} {row.get('matched_rule', '')}".lower()
        )
    ]


def ise_high_repeat_rows(rows: Any, threshold: int = 3) -> list[dict[str, Any]]:
    threshold = _to_int(threshold, 3)
    return [
        row
        for row in _as_list(rows)
        if isinstance(row, dict) and _to_int(row.get("repeat_counter")) >= threshold
    ]


def ise_randomized_mac_rows(rows: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_list(rows)
        if isinstance(row, dict)
        and (bool(row.get("randomized_mac")) or bool(MAC_RANDOM_RE.search(str(row.get("mac", "")).lower())))
    ]


def ise_failure_rows(rows: Any) -> list[dict[str, Any]]:
    return [
        row
        for row in _as_list(rows)
        if isinstance(row, dict)
        and (
            bool(row.get("failure_reason"))
            or "fail" in f"{row.get('status', '')} {row.get('response', '')}".lower()
        )
    ]


def ise_failure_summary(rows: Any) -> list[dict[str, Any]]:
    """Group failed-auth rows by leading 5-digit reason code.

    MnT C(failure_reason) is formatted ``"<code> <human description>"``
    (e.g. ``"11512 Extracted EAP-NAK"``); the human-readable suffix can
    vary slightly between auths so we key on the numeric code and keep
    the first observed description as ``reason``. That matches what the
    Prometheus exporter buckets sessions by.
    """
    counter: Counter[str] = Counter()
    description_for: dict[str, str] = {}
    for row in ise_failure_rows(rows):
        raw = str(row.get("failure_reason") or row.get("status") or "").strip()
        if not raw:
            continue
        head, sep, rest = raw.partition(" ")
        if head.isdigit():
            code, description = head, rest.strip() or raw
        else:
            code, description = raw, raw
        counter[code] += 1
        description_for.setdefault(code, description)
    return [
        {"code": code, "reason": description_for.get(code, ""), "count": count}
        for code, count in counter.most_common(20)
    ]


def ise_port_failure_summary(rows: Any) -> list[dict[str, Any]]:
    counter = Counter()
    samples: dict[str, dict[str, Any]] = {}
    for row in ise_failure_rows(rows):
        port = str(row.get("port") or "unknown").strip() or "unknown"
        counter[port] += 1
        samples.setdefault(port, row)
    return [
        {
            "port": port,
            "failure_count": count,
            "last_failure_reason": samples.get(port, {}).get("failure_reason", ""),
            "last_user": samples.get(port, {}).get("username", ""),
            "last_mac": samples.get(port, {}).get("mac", ""),
            "last_timestamp": samples.get(port, {}).get("timestamp", ""),
        }
        for port, count in counter.most_common(50)
    ]


def ise_policy_hit_rows(rows: Any, query: str = "") -> list[dict[str, Any]]:
    fields = ["authorization_profile", "matched_rule", "status", "failure_reason"]
    return [row for row in _as_list(rows) if isinstance(row, dict) and _contains(row, query, fields)]


def ise_policy_hit_summary(rows: Any) -> list[dict[str, Any]]:
    counter = Counter()
    samples: dict[str, dict[str, Any]] = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        key = str(row.get("authorization_profile") or row.get("matched_rule") or "unknown").strip()
        key = key or "unknown"
        counter[key] += 1
        samples.setdefault(key, row)
    return [
        {
            "policy_or_rule": key,
            "hit_count": count,
            "sample_user": samples.get(key, {}).get("username", ""),
            "sample_mac": samples.get(key, {}).get("mac", ""),
            "sample_nad": samples.get(key, {}).get("nad_name", ""),
            "sample_port": samples.get(key, {}).get("port", ""),
        }
        for key, count in counter.most_common(50)
    ]


# Accounting-Stop records on Session/MACAddress responses carry no auth
# signal — they have ``acct_status_type=Stop`` but no ``passed``/``failed``
# (see the per-deployment ops notes that prompted the 0.6.0 rewrite). The
# breakdown filters use this to ignore them rather than letting them sink
# into the (empty-keyed) "unknown" bucket.
def _is_auth_record(row: dict[str, Any]) -> bool:
    return bool(row.get("status") in ("passed", "failed"))


def _group_count(
    rows: Any,
    key_field: str,
    column_name: str,
    sample_fields: tuple[str, ...] = (
        "username",
        "mac",
        "authentication_method",
        "authentication_protocol",
    ),
    limit: int = 50,
    split_on: str | None = None,
    auth_only: bool = True,
) -> list[dict[str, Any]]:
    """Generic group-and-count helper used by the nad_policy_hits breakdowns.

    Groups *rows* by ``key_field``, tracks the latest timestamp and a
    sample of the requested *sample_fields*. Returns
    ``[{column_name: key, hit_count: int, last_seen: str, sample_*: str},
    ...]`` sorted by count.

    *split_on* turns a comma-separated MnT field (notably
    ``selected_azn_profiles``, which can be ``"Aviano_VoIP,Last_Method"``)
    into one row per profile.

    *auth_only* drops accounting-Stop records (``acct_status_type=Stop``
    sessions), which carry no policy signal.
    """
    counter: Counter[str] = Counter()
    last_seen_map: dict[str, str] = {}
    samples: dict[str, dict[str, Any]] = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        if auth_only and not _is_auth_record(row):
            continue
        raw = row.get(key_field)
        if split_on and raw:
            keys = [k.strip() for k in str(raw).split(split_on) if k.strip()]
        else:
            v = str(raw or "").strip()
            keys = [v] if v else []
        ts = str(row.get("timestamp") or "")
        for key in keys:
            counter[key] += 1
            if ts and ts > last_seen_map.get(key, ""):
                last_seen_map[key] = ts
                samples[key] = row
            elif key not in samples:
                samples[key] = row
    out: list[dict[str, Any]] = []
    for key, count in counter.most_common(limit):
        entry: dict[str, Any] = {column_name: key, "hit_count": count, "last_seen": last_seen_map.get(key, "")}
        for f in sample_fields:
            entry[f"sample_{f}"] = str(samples.get(key, {}).get(f) or "")
        out.append(entry)
    return out


def ise_status_breakdown(rows: Any) -> list[dict[str, Any]]:
    """Count by RADIUS auth ``status`` (passed/failed). Skips accounting-Stops."""
    return _group_count(
        rows,
        key_field="status",
        column_name="status",
        sample_fields=("authentication_method", "username", "mac", "nad_name"),
        limit=10,
    )


def ise_authz_profile_summary(rows: Any) -> list[dict[str, Any]]:
    """Count by ``authorization_profile`` (``selected_azn_profiles``).

    ISE can return multiple profiles in one CSV string when chained authz
    rules apply; we split so each profile gets its own row.
    """
    return _group_count(
        rows,
        key_field="authorization_profile",
        column_name="authorization_profile",
        sample_fields=(
            "identity_group",
            "endpoint_policy",
            "authentication_method",
            "username",
            "mac",
        ),
        split_on=",",
    )


def ise_identity_group_summary(rows: Any) -> list[dict[str, Any]]:
    """Count by ``identity_group`` (e.g. ``Windows11-Workstation``,
    ``Cisco-IP-Phone``)."""
    return _group_count(
        rows,
        key_field="identity_group",
        column_name="identity_group",
        sample_fields=("endpoint_policy", "authorization_profile", "mac"),
    )


def ise_endpoint_policy_summary(rows: Any) -> list[dict[str, Any]]:
    """Count by ``endpoint_policy`` (profiler match)."""
    return _group_count(
        rows,
        key_field="endpoint_policy",
        column_name="endpoint_policy",
        sample_fields=("identity_group", "authorization_profile", "mac"),
    )


def ise_cts_sgt_summary(rows: Any) -> list[dict[str, Any]]:
    """Count by ``cts_security_group`` (Cisco TrustSec SGT name)."""
    return _group_count(
        rows,
        key_field="cts_security_group",
        column_name="cts_security_group",
        sample_fields=("authorization_profile", "identity_group", "mac"),
    )


def ise_authc_method_summary(rows: Any) -> list[dict[str, Any]]:
    """Group auth records by C((authentication_method, authentication_protocol))."""
    counter: Counter[tuple[str, str]] = Counter()
    last_seen_map: dict[tuple[str, str], str] = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        if not _is_auth_record(row):
            continue
        method = str(row.get("authentication_method") or "").strip()
        protocol = str(row.get("authentication_protocol") or "").strip()
        if not method and not protocol:
            continue
        key = (method or "(unspecified)", protocol or "(unspecified)")
        counter[key] += 1
        ts = str(row.get("timestamp") or "")
        if ts and ts > last_seen_map.get(key, ""):
            last_seen_map[key] = ts
    return [
        {
            "authentication_method": method,
            "authentication_protocol": protocol,
            "hit_count": count,
            "last_seen": last_seen_map.get((method, protocol), ""),
        }
        for (method, protocol), count in counter.most_common(50)
    ]


def ise_timeline_rows(rows: Any) -> list[dict[str, Any]]:
    timeline = []
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        timeline.append(
            {
                "timestamp": row.get("timestamp", ""),
                "username": row.get("username", ""),
                "mac": row.get("mac", ""),
                "ip_address": row.get("ip_address", ""),
                "nad_name": row.get("nad_name", ""),
                "nad_ip": row.get("nad_ip", ""),
                "port": row.get("port", ""),
                "status": row.get("status", ""),
                "authorization_profile": row.get("authorization_profile", ""),
                "matched_rule": row.get("matched_rule", ""),
                "failure_reason": row.get("failure_reason", ""),
            }
        )
    return sorted(timeline, key=lambda row: str(row.get("timestamp", "")), reverse=True)


def ise_port_history_rows(rows: Any, endpoint_rows: Any = None) -> list[dict[str, Any]]:
    endpoint_by_mac = {
        str(row.get("mac", "")).lower(): row
        for row in _as_list(endpoint_rows)
        if isinstance(row, dict) and row.get("mac")
    }
    grouped: dict[str, dict[str, Any]] = {}
    for row in _as_list(rows):
        if not isinstance(row, dict):
            continue
        mac = str(row.get("mac") or "").strip()
        key = mac.lower() or f"unknown-{len(grouped)}"
        item = grouped.setdefault(
            key,
            {
                "mac": mac,
                "ip_addresses": set(),
                "users": set(),
                "profiles": set(),
                "authz_profiles": set(),
                "first_seen": "",
                "last_seen": "",
                "event_count": 0,
                "failure_count": 0,
                "last_status": "",
                "last_failure_reason": "",
                "randomized_mac": bool(MAC_RANDOM_RE.search(mac.lower())),
            },
        )
        timestamp = str(row.get("timestamp") or "")
        item["event_count"] += 1
        if timestamp:
            if not item["first_seen"] or timestamp < item["first_seen"]:
                item["first_seen"] = timestamp
            if not item["last_seen"] or timestamp > item["last_seen"]:
                item["last_seen"] = timestamp
                item["last_status"] = row.get("status", "")
                item["last_failure_reason"] = row.get("failure_reason", "")
        if row.get("failure_reason") or "fail" in str(row.get("status", "")).lower():
            item["failure_count"] += 1
        for source, target in (
            ("ip_address", "ip_addresses"),
            ("username", "users"),
            ("authorization_profile", "authz_profiles"),
        ):
            value = row.get(source)
            if value:
                item[target].add(str(value))
        endpoint = endpoint_by_mac.get(mac.lower(), {})
        if endpoint.get("profile"):
            item["profiles"].add(str(endpoint["profile"]))
        if endpoint.get("randomized_mac"):
            item["randomized_mac"] = True

    output = []
    for item in grouped.values():
        normalized = dict(item)
        for key in ("ip_addresses", "users", "profiles", "authz_profiles"):
            normalized[key] = ", ".join(sorted(item[key]))
        output.append(normalized)
    return sorted(output, key=lambda row: str(row.get("last_seen", "")), reverse=True)


def ise_limit_rows(rows: Any, limit: int = 50) -> list[Any]:
    return _as_list(rows)[: _to_int(limit, 50)]


def _flatten_dict(row: dict[str, Any]) -> dict[str, str]:
    return {str(k): _text(v) for k, v in row.items()}


def _report_sections(report: Any) -> tuple[dict[str, Any], list[tuple[str, list[dict[str, Any]]]]]:
    if not isinstance(report, dict):
        return {}, []
    scalars = {}
    tables = []
    for key, value in report.items():
        if isinstance(value, list):
            rows = [item for item in value if isinstance(item, dict)]
            if rows:
                tables.append((key, rows))
            else:
                scalars[key] = len(value)
        elif isinstance(value, dict):
            tables.append((key, [value]))
        else:
            scalars[key] = value
    return scalars, tables


def ise_one_off_html(report: Any) -> str:
    scalars, tables = _report_sections(report)
    title = html.escape(str(scalars.get("title", "ISE One-Off Report")))
    summary_cards = []
    for key, value in scalars.items():
        if key == "title":
            continue
        summary_cards.append(
            "<div class='card'><div class='label'>{}</div><div class='value'>{}</div></div>".format(
                html.escape(str(key).replace("_", " ").title()),
                html.escape(_text(value)),
            )
        )
    table_html = []
    for name, rows in tables:
        flat_rows = [_flatten_dict(row) for row in rows]
        columns = []
        for row in flat_rows:
            for key in row:
                if key not in columns:
                    columns.append(key)
        head = "".join(f"<th>{html.escape(col.replace('_', ' ').title())}</th>" for col in columns)
        body_rows = []
        for row in flat_rows:
            cells = "".join(f"<td>{html.escape(row.get(col, ''))}</td>" for col in columns)
            body_rows.append(f"<tr>{cells}</tr>")
        table_html.append(
            "<section><h2>{} <span>{}</span></h2><table><thead><tr>{}</tr></thead><tbody>{}</tbody></table></section>".format(
                html.escape(name.replace("_", " ").title()),
                len(rows),
                head,
                "".join(body_rows),
            )
        )
    return """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{title}</title>
<style>
:root {{ color-scheme: dark; }}
body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; background: #0f1216; color: #e7eaee; }}
header {{ padding: 22px 28px 12px; border-bottom: 1px solid #2a3038; background: #151a20; }}
h1 {{ margin: 0; font-size: 22px; font-weight: 650; }}
main {{ padding: 18px 28px 32px; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr)); gap: 10px; margin-bottom: 18px; }}
.card {{ border: 1px solid #2a3038; background: #151a20; border-radius: 6px; padding: 10px 12px; }}
.label {{ color: #8e98a6; font-size: 12px; margin-bottom: 4px; }}
.value {{ font-family: Consolas, monospace; font-size: 13px; overflow-wrap: anywhere; }}
section {{ margin-top: 18px; }}
h2 {{ margin: 0 0 8px; font-size: 16px; font-weight: 620; }}
h2 span {{ color: #8e98a6; font-weight: 400; font-size: 12px; }}
table {{ width: 100%; border-collapse: collapse; border: 1px solid #2a3038; background: #12161b; }}
th, td {{ border-bottom: 1px solid #252b33; padding: 8px 9px; text-align: left; vertical-align: top; font-size: 12px; }}
th {{ color: #9fb4ce; background: #18202a; position: sticky; top: 0; }}
td {{ font-family: Consolas, monospace; overflow-wrap: anywhere; }}
</style>
</head>
<body>
<header><h1>{title}</h1></header>
<main>
<div class="summary">{summary}</div>
{tables}
</main>
</body>
</html>
""".format(title=title, summary="".join(summary_cards), tables="".join(table_html))


def ise_one_off_csv(report: Any) -> str:
    _, tables = _report_sections(report)
    output = io.StringIO()
    writer = None
    columns = ["section"]
    flat = []
    for section, rows in tables:
        for row in rows:
            flat_row = {"section": section}
            flat_row.update(_flatten_dict(row))
            for key in flat_row:
                if key not in columns:
                    columns.append(key)
            flat.append(flat_row)
    writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
    writer.writeheader()
    for row in flat:
        writer.writerow(row)
    return output.getvalue()


class FilterModule:
    def filters(self) -> dict[str, Any]:
        return {
            "ise_result_rows": ise_result_rows,
            "ise_endpoint_rows": ise_endpoint_rows,
            "ise_network_device_rows": ise_network_device_rows,
            "ise_auth_rows": ise_auth_rows,
            "ise_coa_candidates": ise_coa_candidates,
            "ise_normalize_mac": ise_normalize_mac,
            "ise_mnt_version": ise_mnt_version,
            "ise_mnt_active_count": ise_mnt_active_count,
            "ise_mnt_active_sessions": ise_mnt_active_sessions,
            "ise_mnt_failure_reasons": ise_mnt_failure_reasons,
            "ise_mnt_auth_status": ise_mnt_auth_status,
            "ise_search_rows": ise_search_rows,
            "ise_nad_rows": ise_nad_rows,
            "ise_sessions_on_nads": ise_sessions_on_nads,
            "ise_port_rows": ise_port_rows,
            "ise_default_policy_rows": ise_default_policy_rows,
            "ise_high_repeat_rows": ise_high_repeat_rows,
            "ise_randomized_mac_rows": ise_randomized_mac_rows,
            "ise_failure_rows": ise_failure_rows,
            "ise_failure_summary": ise_failure_summary,
            "ise_port_failure_summary": ise_port_failure_summary,
            "ise_policy_hit_rows": ise_policy_hit_rows,
            "ise_policy_hit_summary": ise_policy_hit_summary,
            "ise_authz_profile_summary": ise_authz_profile_summary,
            "ise_authc_method_summary": ise_authc_method_summary,
            "ise_status_breakdown": ise_status_breakdown,
            "ise_identity_group_summary": ise_identity_group_summary,
            "ise_endpoint_policy_summary": ise_endpoint_policy_summary,
            "ise_cts_sgt_summary": ise_cts_sgt_summary,
            "ise_normalize_location": ise_normalize_location,
            "ise_timeline_rows": ise_timeline_rows,
            "ise_port_history_rows": ise_port_history_rows,
            "ise_limit_rows": ise_limit_rows,
            "ise_one_off_html": ise_one_off_html,
            "ise_one_off_csv": ise_one_off_csv,
        }
