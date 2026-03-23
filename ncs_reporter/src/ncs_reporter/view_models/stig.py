"""STIG reporting view-model builders."""

import json
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..platform_registry import PlatformRegistry, default_registry
from ..primitives import canonical_stig_status as _canonical_stig_status
from .common import _iter_hosts, _status_from_health, build_meta, canonical_severity, safe_list

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# CKLB loading helper (used by fleet view to resolve severity per rule)
# ---------------------------------------------------------------------------

_fleet_cklb_cache: dict[str, dict[str, dict[str, Any]]] = {}


def _load_cklb_for_fleet(cklb_path: Path) -> dict[str, dict[str, Any]]:
    """Load a CKLB file and return a rule_id → rule dict lookup.

    Results are cached for the lifetime of the process so repeated calls
    for the same path (e.g. multiple audit types on the same host) don't
    re-parse the JSON.
    """
    key = str(cklb_path)
    if key in _fleet_cklb_cache:
        return _fleet_cklb_cache[key]
    try:
        payload = json.loads(cklb_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.debug("Fleet CKLB load failed for %s: %s", cklb_path, exc)
        _fleet_cklb_cache[key] = {}
        return {}
    out: dict[str, dict[str, Any]] = {}
    for stig in payload.get("stigs", []) if isinstance(payload, dict) else []:
        if not isinstance(stig, dict):
            continue
        for rule in stig.get("rules", []) if isinstance(stig.get("rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            for k in ("rule_id", "rule_version", "group_id"):
                val = str(rule.get(k) or "").strip()
                if val and val not in out:
                    out[val] = rule
    _fleet_cklb_cache[key] = out
    return out


def _resolve_fleet_cklb(
    cklb_dir: Any,
    hostname: str,
    payload: dict[str, Any],
    registry: PlatformRegistry | None = None,
) -> dict[str, dict[str, Any]] | None:
    """Try to load a CKLB lookup for a host/target_type pair.

    Returns the lookup dict or None if no CKLB is available.
    Falls back to the skeleton file from the registry if no per-host
    CKLB artifact exists yet.
    """
    if cklb_dir is None:
        return None

    reg = registry or default_registry()
    target_type = str(payload.get("target_type", "")).strip().lower()
    if not target_type:
        return None

    cklb_path = Path(cklb_dir) / f"{hostname}_{target_type}.cklb"
    if cklb_path.is_file():
        return _load_cklb_for_fleet(cklb_path)

    # Fall back to skeleton
    skeleton_file = reg.stig_skeleton_for_target(target_type)
    if skeleton_file:
        sk_path = Path(__file__).parent.parent / "cklb_skeletons" / skeleton_file
        if sk_path.is_file():
            return _load_cklb_for_fleet(sk_path)

    return None


def _canonical_stig_severity(value: Any) -> str:
    return canonical_severity(value)


def _infer_stig_platform(audit_type: Any, payload: dict[str, Any] | None, registry: PlatformRegistry | None = None) -> str:
    reg = registry or default_registry()
    at = str(audit_type or "").lower()
    # Try to infer from audit_type suffix (e.g. stig_esxi -> esxi)
    if at.startswith("stig_"):
        suffix = at.replace("stig_", "", 1)
        result = reg.infer_platform_from_target_type(suffix)
        if result != "unknown":
            return result
    # Try substrings of audit_type against known target types
    for tt in reg.all_target_types():
        if tt.lower() in at:
            result = reg.infer_platform_from_target_type(tt)
            if result != "unknown":
                return result
    # Try payload target_type (exact match then substring)
    target_type = str((payload or {}).get("target_type", "")).lower()
    if target_type:
        result = reg.infer_platform_from_target_type(target_type)
        if result != "unknown":
            return result
        for tt in reg.all_target_types():
            if tt.lower() in target_type:
                result = reg.infer_platform_from_target_type(tt)
                if result != "unknown":
                    return result
    return "unknown"


def _infer_stig_target_type(audit_type: Any, payload: dict[str, Any] | None) -> str:
    at = str(audit_type or "")
    lower_at = at.lower()
    if lower_at.startswith("stig_"):
        return lower_at.replace("stig_", "", 1)
    detail_target = str((payload or {}).get("target_type", "")).strip()
    if detail_target:
        return detail_target
    return lower_at or "unknown"


def _pick_cklb_rule(
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None,
    *candidates: Any,
) -> dict[str, Any]:
    if not cklb_rule_lookup:
        return {}
    for candidate in candidates:
        key = str(candidate or "").strip()
        if key and key in cklb_rule_lookup:
            return dict(cklb_rule_lookup[key] or {})
    return {}


def _normalize_stig_finding(
    finding_or_alert: Any,
    audit_type: Any,
    platform: str,
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(finding_or_alert, dict):
        finding_or_alert = {"message": str(finding_or_alert)}

    item = dict(finding_or_alert)
    detail = dict(item.get("detail") or {})
    if not detail:
        for key in (
            "checktext",
            "fixtext",
            "details",
            "description",
            "status",
            "id",
            "title",
            "severity",
        ):
            if key in item and item.get(key) is not None:
                detail[key] = item.get(key)

    cklb_rule = _pick_cklb_rule(
        cklb_rule_lookup,
        detail.get("rule_id"),
        detail.get("vuln_id"),
        item.get("rule_id"),
        item.get("vuln_id"),
        item.get("id"),
        item.get("rule_version"),
        item.get("group_id"),
    )
    if cklb_rule:
        # Prefer raw finding data, but fill gaps from CKLB's canonical rule metadata.
        # detail["description"] = str(
        #     detail.get("description") or cklb_rule.get("discussion") or cklb_rule.get("finding_details") or ""
        # )
        detail["description"] = str(
            detail.get("description") or cklb_rule.get("discussion") or ""
        )
        detail["checktext"] = str(
            detail.get("checktext") or cklb_rule.get("check_content") or ""
        )
        detail["fixtext"] = str(detail.get("fixtext") or cklb_rule.get("fix_text") or "")
        if cklb_rule.get("rule_id"):
            detail.setdefault("rule_id", cklb_rule.get("rule_id"))

    raw_status = item.get("status", detail.get("status", "open"))
    status = _canonical_stig_status(raw_status)

    raw_severity = (
        cklb_rule.get("severity")
        or item.get("severity")
        or detail.get("original_severity")
        or detail.get("severity")
        or "medium"
    )
    severity = _canonical_stig_severity(raw_severity)

    rule_id = str(
        detail.get("rule_id")
        or detail.get("vuln_id")
        or item.get("rule_id")
        or item.get("vuln_id")
        or item.get("id")
        or ""
    )

    title = str(
        cklb_rule.get("rule_title")
        or item.get("title")
        or detail.get("title")
        or (str(item.get("message") or "")).replace("STIG Violation: ", "")
        or rule_id
        or "Unknown Rule"
    )
    message = str(item.get("message") or detail.get("description") or cklb_rule.get("discussion") or title)

    return {
        "rule_id": rule_id,
        "vuln_id": str(detail.get("vuln_id") or rule_id),
        "severity": severity,
        "category": str(raw_severity).upper() if str(raw_severity) else "INFO",
        "status": status,
        "title": title,
        "message": message,
        "check_result": str(raw_status or ""),
        "fix_available": None,
        "references": {},
        "detail": detail,
        "raw": item,
        "platform": platform,
        "audit_type": str(audit_type or ""),
    }


def _summarize_stig_findings(findings: Any) -> dict[str, dict[str, int]]:
    out = {
        "findings": {"total": 0, "critical": 0, "warning": 0, "info": 0},
        "by_status": {"open": 0, "pass": 0, "na": 0, "not_reviewed": 0, "unknown": 0},
    }
    for f in safe_list(findings):
        sev = str((f or {}).get("severity") or "INFO").upper()
        status = str((f or {}).get("status") or "unknown")
        out["findings"]["total"] += 1

        if status not in out["by_status"]:
            status = "unknown"
        out["by_status"][status] += 1

        if status == "open":
            if sev in ("CRITICAL", "HIGH"):
                out["findings"]["critical"] += 1
            elif sev in ("WARNING", "MEDIUM"):
                out["findings"]["warning"] += 1
            else:
                out["findings"]["info"] += 1
    return out


def build_stig_host_view(
    hostname: str,
    audit_type: Any,
    stig_payload: Any,
    *,
    host_bundle: dict[str, Any] | None = None,
    hosts_data: dict[str, Any] | None = None,
    platform: str | None = None,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: Mapping[str, Any] | None = None,
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None = None,
    generated_fleet_dirs: set[str] | None = None,
    history: list[dict[str, str]] | None = None,
    stig_host_peers: list[dict[str, str]] | None = None,
    stig_siblings: list[dict[str, str]] | None = None,
    registry: PlatformRegistry | None = None,
) -> dict[str, Any]:
    reg = registry or default_registry()
    stig_payload = dict(stig_payload or {})
    platform_name = platform or _infer_stig_platform(audit_type, stig_payload, registry=reg)
    target_type = _infer_stig_target_type(audit_type, stig_payload)

    source_findings = []
    # Track which rule IDs we've already added from the audit results
    seen_rule_ids = set()

    full_audit = stig_payload.get("full_audit")
    if isinstance(full_audit, list):
        for row in full_audit:
            finding = _normalize_stig_finding(row, audit_type, platform_name, cklb_rule_lookup)
            source_findings.append(finding)
            rid = finding.get("rule_id")
            if rid:
                seen_rule_ids.add(str(rid).strip())
    else:
        for alert in safe_list(stig_payload.get("alerts")):
            finding = _normalize_stig_finding(alert, audit_type, platform_name, cklb_rule_lookup)
            source_findings.append(finding)
            rid = finding.get("rule_id")
            if rid:
                seen_rule_ids.add(str(rid).strip())

    # If we have a skeleton, add any rules that were NOT in the automated results
    if cklb_rule_lookup:
        for rid, rule_def in cklb_rule_lookup.items():
            clean_rid = str(rid).strip()
            # Rule definitions are indexed by rule_id, rule_version, and group_id.
            # We only want to process each rule ONCE.
            if clean_rid != str(rule_def.get("rule_id")).strip():
                continue

            # Check if this rule (or its version aliases) was seen in findings
            was_seen = (
                clean_rid in seen_rule_ids
                or str(rule_def.get("rule_version")).strip() in seen_rule_ids
                or str(rule_def.get("group_id")).strip() in seen_rule_ids
            )

            if not was_seen:
                # Add as a 'not_reviewed' finding
                source_findings.append(
                    _normalize_stig_finding(
                        {"status": "not_reviewed", "rule_id": clean_rid},
                        audit_type,
                        platform_name,
                        cklb_rule_lookup,
                    )
                )

    summary = _summarize_stig_findings(source_findings)
    health = _status_from_health(stig_payload.get("health"))

    _status_order = {"open": 0, "na": 1, "pass": 2}
    _sev_order = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "low": 2, "info": 2}
    source_findings.sort(
        key=lambda f: (
            _status_order.get(str(f.get("status") or "").lower(), 3),
            _sev_order.get(str(f.get("severity") or "").lower(), 3),
            str(f.get("rule_id") or ""),
        )
    )

    # Build nav tree information
    nav_with_tree = {**nav} if nav else {}
    if history:
        nav_with_tree["history"] = history

    # Sibling STIG audits for the same host (e.g. if a host has both ESXi and VM STIGs)
    if stig_siblings is not None:
        # Pre-computed with proper relative paths from cli._render_stig
        nav_with_tree["tree_siblings"] = stig_siblings
    else:
        # Fallback: build from bundle (filename only, works when reports are co-located)
        siblings = []
        if host_bundle:
            for k in host_bundle.keys():
                if k.lower().startswith("stig_") and k != audit_type:
                    p = host_bundle[k]
                    t_type = _infer_stig_target_type(k, p)
                    siblings.append({"name": f"{t_type.upper()} STIG", "report": f"{hostname}_stig_{t_type}.html"})
        siblings.sort(key=lambda x: x["name"])
        nav_with_tree["tree_siblings"] = siblings

    # Peer hosts with same STIG target type (for host-switching dropdown)
    if stig_host_peers:
        nav_with_tree["tree_host_peers"] = stig_host_peers

    # Global fleets dropdown
    if hosts_data:
        current_plt_dir = hosts_data.get(hostname)
        depth = len(current_plt_dir.split("/")) + 1 if current_plt_dir else 3
        back_to_root = "../" * (depth + 1)  # back to site root

        fleets = []
        p_dirs = sorted(list(set(hosts_data.values())))
        if generated_fleet_dirs is not None:
            p_dirs = [d for d in p_dirs if d in generated_fleet_dirs]
        for plt_dir in p_dirs:
            # Find the entry whose report_dir matches to get display_name and schema_name
            matched_entry = None
            for e in reg.entries:
                if e.report_dir == plt_dir:
                    matched_entry = e
                    break
            if matched_entry and len(matched_entry.schema_names) > 1:
                from ..schema_loader import discover_schemas
                all_schemas = discover_schemas()
                for sn in matched_entry.schema_names:
                    s = all_schemas.get(sn)
                    label = s.display_name if s else sn.replace("_", " ").title()
                    fleets.append(
                        {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{sn}_fleet_report.html"}
                    )
            else:
                if matched_entry:
                    label = matched_entry.display_name or matched_entry.platform.capitalize()
                    schema_name = (matched_entry.schema_names[0] if matched_entry.schema_names
                                   else matched_entry.schema_name or matched_entry.platform)
                else:
                    label = plt_dir.split("/")[-1].capitalize()
                    schema_name = plt_dir.split("/")[-1]
                fleets.append(
                    {"name": label, "report": f"{back_to_root}platform/{plt_dir}/{schema_name}_fleet_report.html"}
                )

        fleets.append({"name": "STIG", "report": f"{back_to_root}stig_fleet_report.html"})
        nav_with_tree["tree_fleets"] = fleets

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "nav": nav_with_tree,
        "target": {
            "host": str(hostname),
            "platform": platform_name,
            "target_type": target_type,
            "audit_type": str(audit_type or ""),
            "status": {"raw": health, "label": health},
        },
        "summary": {
            "findings": summary["findings"],
            "by_status": summary["by_status"],
            "score": {"compliance_pct": None},
        },
        "findings": source_findings,
        "widgets": [],
    }


def build_stig_fleet_view(
    aggregated_hosts: dict[str, Any],
    *,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    nav: Mapping[str, Any] | None = None,
    generated_fleet_dirs: set[str] | None = None,
    registry: PlatformRegistry | None = None,
    cklb_dir: Any = None,
) -> dict[str, Any]:
    reg = registry or default_registry()
    rows = []
    row_index: dict[str, dict[str, Any]] = {}
    top_index: dict[str, dict[str, Any]] = {}
    totals = {"hosts": 0, "findings_open": 0, "critical": 0, "warning": 0, "info": 0}
    _init_keys = {*reg.all_platform_names(), "unknown"}
    by_platform: dict[str, dict[str, int]] = {
        k: {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0} for k in _init_keys
    }
    platform_hosts: dict[str, set[str]] = {k: set() for k in by_platform}

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for audit_type, payload in dict(bundle or {}).items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            # Resolve CKLB rule lookup for this host/target so severity,
            # checktext, and fixtext can be hydrated from the authoritative
            # DISA skeleton even when the raw audit data lacks them.
            cklb_rule_lookup = _resolve_fleet_cklb(
                cklb_dir, hostname, payload, registry=reg
            )

            host_view = build_stig_host_view(
                hostname,
                audit_type,
                payload,
                report_stamp=report_stamp,
                report_date=report_date,
                report_id=report_id,
                nav=nav,
                registry=reg,
                cklb_rule_lookup=cklb_rule_lookup,
            )
            target = host_view["target"]
            summary = host_view["summary"]
            findings = host_view["findings"]
            p_name = target["platform"] if target["platform"] in by_platform else "unknown"
            open_count = summary["by_status"].get("open", 0)
            crit = summary["findings"].get("critical", 0)
            warn = summary["findings"].get("warning", 0)
            info = summary["findings"].get("info", 0)

            totals["findings_open"] += open_count
            totals["critical"] += crit
            totals["warning"] += warn
            totals["info"] += info
            by_platform[p_name]["open"] += open_count
            by_platform[p_name]["critical"] += crit
            by_platform[p_name]["warning"] += warn
            by_platform[p_name]["info"] += info
            platform_hosts[p_name].add(hostname)

            # Use the canonical STIG report name pattern: <host>_stig_<target_type>.html
            t_type = target.get("target_type", "unknown")
            # Resolve link base — try exact match, then substring for compound types
            known_types = reg.all_target_types()
            resolved_base_type = t_type if t_type in known_types else None
            if not resolved_base_type:
                for tt in known_types:
                    if tt.lower() in t_type.lower():
                        resolved_base_type = tt
                        break
            link_base = reg.link_base_for_target(resolved_base_type or t_type)
            stamped_name = f"{hostname}_stig_{t_type}.html"
            target_link = f"{link_base}/{hostname}/{stamped_name}"
            key = f"{p_name}:{hostname}"
            row = row_index.get(key)
            if row is None:
                row = {
                    "host": hostname,
                    "platform": p_name,
                    "status": {"raw": "PASS"},
                    "findings_open": 0,
                    "critical": 0,
                    "warning": 0,
                    "info": 0,
                    "links": {"node_report_latest": target_link},
                    "targets": [],
                    "findings": [],
                }
                row_index[key] = row
                rows.append(row)

            row["findings_open"] += open_count
            row["critical"] += crit
            row["warning"] += warn
            row["info"] += info
            row["findings"].extend([f for f in findings if f.get("status") == "open"])
            row["targets"].append(
                {
                    "target_type": str(t_type),
                    "audit_type": str(audit_type),
                    "status": str((target.get("status") or {}).get("raw") or "UNKNOWN"),
                    "link": target_link,
                }
            )
            # Update link if this is a known target type (exact or substring match)
            known_types = reg.all_target_types()
            if t_type in known_types or any(tt in t_type.lower() for tt in known_types):
                row["links"]["node_report_latest"] = target_link

            for f in findings:
                rid = f.get("rule_id") or "UNKNOWN"
                idx = top_index.setdefault(
                    rid,
                    {
                        "rule_id": rid,
                        "affected_hosts": set(),
                        "severity": f.get("severity", "INFO"),
                        "title": f.get("title", rid),
                    },
                )
                if f.get("status") == "open":
                    idx["affected_hosts"].add(hostname)

    totals["hosts"] = len({r["host"] for r in rows})
    for p_name in by_platform:
        by_platform[p_name]["hosts"] = len(platform_hosts[p_name])

    for row in rows:
        row["targets"] = sorted(
            row.get("targets", []),
            key=lambda x: (str(x.get("target_type") or ""), str(x.get("audit_type") or "")),
        )
        if row.get("critical", 0) > 0:
            row["status"] = {"raw": "CRITICAL"}
        elif row.get("findings_open", 0) > 0:
            row["status"] = {"raw": "WARNING"}
        else:
            row["status"] = {"raw": "PASS"}

    top_findings = []
    for item in top_index.values():
        count = len(item["affected_hosts"])
        if count == 0:
            continue
        top_findings.append(
            {
                "rule_id": item["rule_id"],
                "affected_hosts": count,
                "severity": item["severity"],
                "title": item["title"],
            }
        )
    _sev_order = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "low": 2, "info": 2}
    top_findings.sort(
        key=lambda x: (
            -int(x["affected_hosts"]),
            _sev_order.get(str(x.get("severity") or "").lower(), 3),
            str(x["rule_id"]),
        )
    )
    rows.sort(key=lambda x: (str(x["platform"]), str(x["host"])))

    # Build nav tree information
    nav_with_tree = {**nav} if nav else {}
    # We can derive tree_fleets from by_platform if they have hosts
    tree_fleets = []
    for p_name in reg.all_platform_names():
        report_dir = reg.platform_to_report_dir(p_name)
        if report_dir is None:
            continue
        if generated_fleet_dirs is not None and report_dir not in generated_fleet_dirs:
            continue
        if by_platform.get(p_name, {}).get("hosts", 0) > 0:
            fleet_link = reg.platform_fleet_link(p_name)
            if fleet_link:
                display = reg.platform_display_name(p_name)
                tree_fleets.append({"name": display, "report": fleet_link})
            else:
                schema_names = reg.schema_names_for_platform(p_name) or [p_name]
                from ..schema_loader import discover_schemas
                all_schemas = discover_schemas()
                for sn in schema_names:
                    s = all_schemas.get(sn)
                    label = s.display_name if s else sn.replace("_", " ").title()
                    tree_fleets.append({"name": label, "report": f"platform/{report_dir}/{sn}_fleet_report.html"})

    # Add STIG fleet
    tree_fleets.append({"name": "STIG", "report": "stig_fleet_report.html"})
    nav_with_tree["tree_fleets"] = tree_fleets

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "nav": nav_with_tree,
        "fleet": {
            "totals": totals,
            "by_platform": by_platform,
        },
        "rows": rows,
        "findings_index": {"top_findings": top_findings[:20]},
    }
