"""Shared CKLB file parsing utilities."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

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
