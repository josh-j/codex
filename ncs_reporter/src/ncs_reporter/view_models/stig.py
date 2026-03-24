"""STIG reporting view-model builders."""

from __future__ import annotations

import dataclasses
import logging
from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .nav_builder import NavBuilder

from .._cklb import load_cklb_lookup
from ..pathing import rel_href, render_template
from ..platform_registry import PlatformRegistry, default_registry
from ..primitives import canonical_stig_status as _canonical_stig_status
from .common import _iter_hosts, _status_from_health, build_meta, canonical_severity, safe_list

logger = logging.getLogger(__name__)


@dataclasses.dataclass
class StigNavContext:
    """Bundles nav-related parameters for STIG host report building."""
    nav: Mapping[str, Any] | None = None
    host_bundle: dict[str, Any] | None = None
    hosts_data: dict[str, Any] | None = None
    generated_fleet_dirs: set[str] | None = None
    history: list[dict[str, str]] | None = None
    stig_host_peers: list[dict[str, str]] | None = None
    stig_siblings: list[dict[str, str]] | None = None
    nav_builder: NavBuilder | None = None


@dataclasses.dataclass
class FleetAccumulator:
    """Mutable accumulators for fleet row building."""
    rows: list[dict[str, Any]] = dataclasses.field(default_factory=list)
    row_index: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    top_index: dict[str, dict[str, Any]] = dataclasses.field(default_factory=dict)
    totals: dict[str, int] = dataclasses.field(default_factory=lambda: {"hosts": 0, "findings_open": 0, "critical": 0, "warning": 0, "info": 0})
    by_platform: dict[str, dict[str, int]] = dataclasses.field(default_factory=dict)
    platform_hosts: dict[str, set[str]] = dataclasses.field(default_factory=dict)


_SEV_ORDER: dict[str, int] = {"critical": 0, "high": 0, "warning": 1, "medium": 1, "low": 2, "info": 2}
_STATUS_ORDER: dict[str, int] = {"open": 0, "na": 1, "pass": 2}


def collect_stig_entries(
    hosts_data: dict[str, Any],
    stamp: str,
    registry: PlatformRegistry,
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, str]]]]:
    """Enumerate hosts_data and collect STIG audit entries + report index.

    Returns:
        stig_entries: flat list of per-audit-type metadata dicts
        all_stig_reports: hostname → [{target_type, host_report_abs, host_rel_dir}]
    """
    stig_entries: list[dict[str, Any]] = []
    all_stig_reports: dict[str, list[dict[str, str]]] = {}

    for hostname, bundle in hosts_data.items():
        if not isinstance(bundle, dict):
            continue
        for audit_type, payload in bundle.items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            target_type = str(payload.get("target_type", "")).strip().lower()
            entry = registry.entry_for_target_type(target_type)
            if entry is None:
                # Fallback to first available platform entry
                entry = registry.entries[0] if registry.entries else None
            if entry is None:
                logger.warning("No STIG platform mapping for target_type '%s'", target_type)
                continue

            report_dir = entry.report_dir
            path_templates = entry.paths.model_dump()
            host_report_abs = render_template(
                path_templates["report_stig_host"],
                report_dir=report_dir,
                schema_name="",
                hostname=hostname,
                target_type=target_type,
                report_stamp=stamp,
            )
            host_rel_dir = str(Path(host_report_abs).parent).replace("\\", "/")

            se = {
                "hostname": hostname,
                "bundle": bundle,
                "audit_type": audit_type,
                "payload": payload,
                "target_type": target_type,
                "entry": entry,
                "report_dir": report_dir,
                "path_templates": path_templates,
                "host_report_abs": host_report_abs,
                "host_rel_dir": host_rel_dir,
            }
            stig_entries.append(se)
            all_stig_reports.setdefault(hostname, []).append({
                "target_type": target_type,
                "host_report_abs": host_report_abs,
                "host_rel_dir": host_rel_dir,
            })

    return stig_entries, all_stig_reports


def build_stig_nav(
    se: dict[str, Any],
    all_stig_reports: dict[str, list[dict[str, str]]],
    stig_fleet_abs: str,
    site_report_abs: str | None,
    has_site_report: bool,
) -> tuple[dict[str, str], list[dict[str, str]], list[dict[str, str]]]:
    """Build host_nav, stig_host_peers, and stig_siblings for one STIG entry."""
    hostname = se["hostname"]
    target_type = se["target_type"]
    host_rel_dir = se["host_rel_dir"]

    host_nav: dict[str, str] = {
        "fleet_report": rel_href(host_rel_dir, stig_fleet_abs),
        "fleet_label": "STIG Fleet Dashboard",
    }
    if has_site_report and site_report_abs:
        host_nav["site_report"] = rel_href(host_rel_dir, site_report_abs)

    # Peer hosts (all STIG hosts, preferring same target_type)
    stig_host_peers: list[dict[str, str]] = []
    seen_peers: set[str] = set()
    for peer_host, peer_reports in sorted(all_stig_reports.items()):
        if peer_host in seen_peers:
            continue
        seen_peers.add(peer_host)
        pr = next((r for r in peer_reports if r["target_type"] == target_type), peer_reports[0])
        peer_abs = pr["host_rel_dir"] + "/" + Path(pr["host_report_abs"]).name
        stig_host_peers.append({"name": peer_host, "report": rel_href(host_rel_dir, peer_abs)})

    # Siblings (other STIG types for same host)
    stig_siblings: list[dict[str, str]] = sorted(
        [
            {
                "name": f"{sr['target_type'].upper()} STIG",
                "report": rel_href(host_rel_dir, sr["host_rel_dir"] + "/" + Path(sr["host_report_abs"]).name),
            }
            for sr in all_stig_reports.get(hostname, [])
            if sr["target_type"] != target_type
        ],
        key=lambda x: x["name"],
    )

    return host_nav, stig_host_peers, stig_siblings


def _resolve_fleet_cklb(
    cklb_dir: Any,
    hostname: str,
    payload: dict[str, Any],
    registry: PlatformRegistry | None = None,
    cache: dict[str, dict[str, dict[str, Any]]] | None = None,
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
        return load_cklb_lookup(cklb_path, cache=cache)

    # Fall back to skeleton
    skeleton_file = reg.stig_skeleton_for_target(target_type)
    if skeleton_file:
        from ncs_reporter.models.platforms_config import CKLB_SKELETONS_DIR
        sk_path = Path(__file__).parent.parent / CKLB_SKELETONS_DIR / skeleton_file
        if sk_path.is_file():
            return load_cklb_lookup(sk_path)

    return None


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


def _build_finding_detail(
    item: dict[str, Any],
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Build the detail dict and resolve CKLB rule for a finding."""
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
        detail["description"] = str(
            detail.get("description") or cklb_rule.get("discussion") or ""
        )
        detail["checktext"] = str(
            detail.get("checktext") or cklb_rule.get("check_content") or ""
        )
        detail["fixtext"] = str(detail.get("fixtext") or cklb_rule.get("fix_text") or "")
        if cklb_rule.get("rule_id"):
            detail.setdefault("rule_id", cklb_rule.get("rule_id"))

    return detail, cklb_rule


def _resolve_finding_fields(
    item: dict[str, Any],
    detail: dict[str, Any],
    cklb_rule: dict[str, Any],
    audit_type: Any,
    platform: str,
) -> dict[str, Any]:
    """Resolve status, severity, rule_id, title, message and assemble the finding dict."""
    raw_status = item.get("status", detail.get("status", "open"))
    status = _canonical_stig_status(raw_status)

    raw_severity = (
        cklb_rule.get("severity")
        or item.get("severity")
        or detail.get("original_severity")
        or detail.get("severity")
        or "medium"
    )
    severity = canonical_severity(raw_severity)

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


def _normalize_stig_finding(
    finding_or_alert: Any,
    audit_type: Any,
    platform: str,
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    if not isinstance(finding_or_alert, dict):
        finding_or_alert = {"message": str(finding_or_alert)}

    item = dict(finding_or_alert)
    detail, cklb_rule = _build_finding_detail(item, cklb_rule_lookup)
    return _resolve_finding_fields(item, detail, cklb_rule, audit_type, platform)


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


def _collect_source_findings(
    stig_payload: dict[str, Any],
    audit_type: Any,
    platform_name: str,
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Normalize raw audit/alert items and backfill unseen CKLB rules."""
    source_findings: list[dict[str, Any]] = []
    seen_rule_ids: set[str] = set()

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

            was_seen = (
                clean_rid in seen_rule_ids
                or str(rule_def.get("rule_version")).strip() in seen_rule_ids
                or str(rule_def.get("group_id")).strip() in seen_rule_ids
            )

            if not was_seen:
                source_findings.append(
                    _normalize_stig_finding(
                        {"status": "not_reviewed", "rule_id": clean_rid},
                        audit_type,
                        platform_name,
                        cklb_rule_lookup,
                    )
                )

    return source_findings


def _build_stig_host_nav(
    hostname: str,
    audit_type: Any,
    *,
    ctx: StigNavContext,
    registry: PlatformRegistry,
) -> dict[str, Any]:
    """Build the nav-tree dict for a STIG host report."""
    if ctx.nav_builder is not None:
        return ctx.nav_builder.build_for_stig_host(
            hostname,
            base_nav=ctx.nav,
            history=ctx.history,
            stig_host_peers=ctx.stig_host_peers,
            stig_siblings=ctx.stig_siblings,
            host_bundle=ctx.host_bundle,
            audit_type=str(audit_type or ""),
        )

    nav_with_tree: dict[str, Any] = {**ctx.nav} if ctx.nav else {}
    if ctx.history:
        nav_with_tree["history"] = ctx.history

    # Sibling STIG audits for the same host
    if ctx.stig_siblings is not None:
        nav_with_tree["tree_siblings"] = ctx.stig_siblings
    else:
        siblings: list[dict[str, str]] = []
        if ctx.host_bundle:
            for k in ctx.host_bundle.keys():
                if k.lower().startswith("stig_") and k != audit_type:
                    p = ctx.host_bundle[k]
                    t_type = _infer_stig_target_type(k, p)
                    siblings.append({"name": f"{t_type.upper()} STIG", "report": f"{hostname}_stig_{t_type}.html"})
        siblings.sort(key=lambda x: x["name"])
        nav_with_tree["tree_siblings"] = siblings

    if ctx.stig_host_peers:
        nav_with_tree["tree_host_peers"] = ctx.stig_host_peers

    # Global fleets dropdown
    if ctx.hosts_data:
        from ncs_reporter.models.platforms_config import (
            FILENAME_STIG_FLEET as _FSF,
            fleet_link_url,
        )
        current_plt_dir = ctx.hosts_data.get(hostname)
        depth = len(current_plt_dir.split("/")) + 1 if current_plt_dir else 3
        back_to_root = "../" * (depth + 1)

        fleets: list[dict[str, str]] = []
        p_dirs = sorted(list(set(ctx.hosts_data.values())))
        if ctx.generated_fleet_dirs is not None:
            p_dirs = [d for d in p_dirs if d in ctx.generated_fleet_dirs]
        for plt_dir in p_dirs:
            matched_entry = None
            for e in registry.entries:
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
                        {"name": label, "report": fleet_link_url(plt_dir, sn, back_to_root)}
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
                    {"name": label, "report": fleet_link_url(plt_dir, schema_name, back_to_root)}
                )

        from ..models.platforms_config import NAV_LABEL_STIG
        fleets.append({"name": NAV_LABEL_STIG, "report": f"{back_to_root}{_FSF}"})
        nav_with_tree["tree_fleets"] = fleets

    return nav_with_tree


def build_stig_host_view(
    hostname: str,
    audit_type: Any,
    stig_payload: Any,
    *,
    platform: str | None = None,
    report_stamp: str | None = None,
    report_date: str | None = None,
    report_id: str | None = None,
    cklb_rule_lookup: Mapping[str, dict[str, Any]] | None = None,
    registry: PlatformRegistry | None = None,
    nav_ctx: StigNavContext | None = None,
) -> dict[str, Any]:
    reg = registry or default_registry()
    if nav_ctx is None:
        nav_ctx = StigNavContext()
    stig_payload = dict(stig_payload or {})
    platform_name = platform or _infer_stig_platform(audit_type, stig_payload, registry=reg)
    target_type = _infer_stig_target_type(audit_type, stig_payload)

    source_findings = _collect_source_findings(stig_payload, audit_type, platform_name, cklb_rule_lookup)

    summary = _summarize_stig_findings(source_findings)
    health = _status_from_health(stig_payload.get("health"))

    _status_order = _STATUS_ORDER
    _sev_order = _SEV_ORDER
    source_findings.sort(
        key=lambda f: (
            _status_order.get(str(f.get("status") or "").lower(), 3),
            _sev_order.get(str(f.get("severity") or "").lower(), 3),
            str(f.get("rule_id") or ""),
        )
    )

    nav_with_tree = _build_stig_host_nav(
        hostname, audit_type,
        ctx=nav_ctx,
        registry=reg,
    )

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


def _build_fleet_row(
    hostname: str,
    audit_type: str,
    host_view: dict[str, Any],
    *,
    acc: FleetAccumulator,
    registry: PlatformRegistry,
) -> None:
    """Accumulate one audit-type result into the fleet accumulators."""
    target = host_view["target"]
    summary = host_view["summary"]
    findings = host_view["findings"]
    p_name = target["platform"] if target["platform"] in acc.by_platform else "unknown"
    open_count = summary["by_status"].get("open", 0)
    crit = summary["findings"].get("critical", 0)
    warn = summary["findings"].get("warning", 0)
    info = summary["findings"].get("info", 0)

    acc.totals["findings_open"] += open_count
    acc.totals["critical"] += crit
    acc.totals["warning"] += warn
    acc.totals["info"] += info
    acc.by_platform[p_name]["open"] += open_count
    acc.by_platform[p_name]["critical"] += crit
    acc.by_platform[p_name]["warning"] += warn
    acc.by_platform[p_name]["info"] += info
    acc.platform_hosts[p_name].add(hostname)

    t_type = target.get("target_type", "unknown")
    known_types = registry.all_target_types()
    resolved_base_type = t_type if t_type in known_types else None
    if not resolved_base_type:
        for tt in known_types:
            if tt.lower() in t_type.lower():
                resolved_base_type = tt
                break
    link_base = registry.link_base_for_target(resolved_base_type or t_type)
    stamped_name = f"{hostname}_stig_{t_type}.html"
    target_link = f"{link_base}/{hostname}/{stamped_name}"
    key = f"{p_name}:{hostname}"
    row = acc.row_index.get(key)
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
        acc.row_index[key] = row
        acc.rows.append(row)

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
    if t_type in known_types or any(tt in t_type.lower() for tt in known_types):
        row["links"]["node_report_latest"] = target_link

    for f in findings:
        rid = f.get("rule_id") or "UNKNOWN"
        idx = acc.top_index.setdefault(
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


def _build_fleet_nav(
    nav: Mapping[str, Any] | None,
    by_platform: dict[str, dict[str, int]],
    *,
    generated_fleet_dirs: set[str] | None,
    registry: PlatformRegistry,
    nav_builder: NavBuilder | None = None,
) -> dict[str, Any]:
    """Build the nav-tree dict for the STIG fleet report."""
    if nav_builder is not None:
        return nav_builder.build_for_stig_fleet(by_platform, base_nav=nav)

    from ncs_reporter.models.platforms_config import (
        FILENAME_STIG_FLEET as _FSF,
        fleet_link_url,
    )
    nav_with_tree: dict[str, Any] = {**nav} if nav else {}
    tree_fleets: list[dict[str, str]] = []
    for p_name in registry.all_platform_names():
        report_dir = registry.platform_to_report_dir(p_name)
        if report_dir is None:
            continue
        if generated_fleet_dirs is not None and report_dir not in generated_fleet_dirs:
            continue
        if by_platform.get(p_name, {}).get("hosts", 0) > 0:
            fleet_link = registry.platform_fleet_link(p_name)
            if fleet_link:
                display = registry.platform_display_name(p_name)
                tree_fleets.append({"name": display, "report": fleet_link})
            else:
                schema_names = registry.schema_names_for_platform(p_name) or [p_name]
                from ..schema_loader import discover_schemas
                all_schemas = discover_schemas()
                for sn in schema_names:
                    s = all_schemas.get(sn)
                    label = s.display_name if s else sn.replace("_", " ").title()
                    tree_fleets.append({"name": label, "report": fleet_link_url(report_dir, sn)})

    from ncs_reporter.models.platforms_config import NAV_LABEL_STIG
    tree_fleets.append({"name": NAV_LABEL_STIG, "report": _FSF})
    nav_with_tree["tree_fleets"] = tree_fleets
    return nav_with_tree


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
    nav_builder: NavBuilder | None = None,
) -> dict[str, Any]:
    reg = registry or default_registry()
    _init_keys = {*reg.all_platform_names(), "unknown"}
    acc = FleetAccumulator(
        by_platform={k: {"hosts": 0, "open": 0, "critical": 0, "warning": 0, "info": 0} for k in _init_keys},
        platform_hosts={k: set() for k in _init_keys},
    )
    cklb_cache: dict[str, dict[str, dict[str, Any]]] = {}

    for hostname, bundle in _iter_hosts(aggregated_hosts):
        for audit_type, payload in dict(bundle or {}).items():
            if not str(audit_type).lower().startswith("stig"):
                continue
            if not isinstance(payload, dict):
                continue

            cklb_rule_lookup = _resolve_fleet_cklb(
                cklb_dir, hostname, payload, registry=reg, cache=cklb_cache,
            )

            host_view = build_stig_host_view(
                hostname,
                audit_type,
                payload,
                report_stamp=report_stamp,
                report_date=report_date,
                report_id=report_id,
                nav_ctx=StigNavContext(nav=nav),
                registry=reg,
                cklb_rule_lookup=cklb_rule_lookup,
            )
            _build_fleet_row(
                hostname, audit_type, host_view,
                acc=acc,
                registry=reg,
            )

    acc.totals["hosts"] = len({r["host"] for r in acc.rows})
    for p_name in acc.by_platform:
        acc.by_platform[p_name]["hosts"] = len(acc.platform_hosts[p_name])

    for row in acc.rows:
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
    for item in acc.top_index.values():
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
    _sev_order = _SEV_ORDER
    top_findings.sort(
        key=lambda x: (
            -int(x["affected_hosts"]),
            _sev_order.get(str(x.get("severity") or "").lower(), 3),
            str(x["rule_id"]),
        )
    )
    acc.rows.sort(key=lambda x: (str(x["platform"]), str(x["host"])))

    nav_with_tree = _build_fleet_nav(
        nav, acc.by_platform,
        generated_fleet_dirs=generated_fleet_dirs,
        registry=reg,
        nav_builder=nav_builder,
    )

    return {
        "meta": build_meta(report_stamp, report_date, report_id),
        "nav": nav_with_tree,
        "fleet": {
            "totals": acc.totals,
            "by_platform": acc.by_platform,
        },
        "rows": acc.rows,
        "findings_index": {"top_findings": top_findings[:20]},
    }
