"""Shared CKLB file parsing and lookup utilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from .platform_registry import PlatformRegistry

logger = logging.getLogger(__name__)


def parse_cklb_rules(payload: Any) -> dict[str, dict[str, Any]]:
    """Extract a rule_id/rule_version/group_id → rule dict from a parsed CKLB payload."""
    out: dict[str, dict[str, Any]] = {}
    for stig in payload.get("stigs", []) if isinstance(payload, dict) else []:
        if not isinstance(stig, dict):
            continue
        for rule in stig.get("rules", []) if isinstance(stig.get("rules"), list) else []:
            if not isinstance(rule, dict):
                continue
            for id_key in ("rule_id", "rule_version", "group_id"):
                val = str(rule.get(id_key) or "").strip()
                if val and val not in out:
                    out[val] = rule
    return out


def load_cklb_lookup(
    cklb_path: Path,
    cache: dict[str, dict[str, dict[str, Any]]] | None = None,
) -> dict[str, dict[str, Any]]:
    """Parse a CKLB file into a rule lookup dict.  Results are cached by path."""
    key = str(cklb_path)
    if cache is not None and key in cache:
        return cache[key]
    if not cklb_path.is_file():
        if cache is not None:
            cache[key] = {}
        return {}
    try:
        payload = json.loads(cklb_path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to parse CKLB %s: %s", cklb_path, exc)
        if cache is not None:
            cache[key] = {}
        return {}
    result = parse_cklb_rules(payload)
    if cache is not None:
        cache[key] = result
    return result


def resolve_cklb_lookup(
    hostname: str,
    target_type: str,
    cklb_dir: Path | None,
    registry: PlatformRegistry,
    cache: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, Any]]:
    """Resolve CKLB lookup for a host/target, falling back to the skeleton file."""
    if cklb_dir and target_type:
        lookup = load_cklb_lookup(cklb_dir / f"{hostname}_{target_type}.cklb", cache)
        if lookup:
            return lookup
    if target_type:
        skeleton_file = registry.stig_skeleton_for_target(target_type)
        if skeleton_file:
            sk_path = Path(__file__).parent / "cklb_skeletons" / skeleton_file
            return load_cklb_lookup(sk_path, cache)
    return {}
