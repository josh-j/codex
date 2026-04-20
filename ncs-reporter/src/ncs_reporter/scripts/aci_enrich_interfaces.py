#!/usr/bin/env python3
"""Enrich APIC interface utilization rows for the ACI report.

stdin  - JSON: {"fields": {<source>: [...], "interface_description_map": {...}}, "args": {...}}
stdout - JSON list: rows enriched with `interface_label` + `description`,
         de-duplicated (keep max `utilMax` per label), sorted, and truncated.

args:
  source          — "ingress" (default) or "egress"
  util_threshold  — drop rows with utilAvg <= threshold (default 25)
  top_n           — max rows to return (default 10)

Port-channel aggregate entries (DN ending in ``[PoN]``) are dropped —
member ports are reported individually and aggregates skew the view.
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

from ncs_reporter.primitives import to_float, to_int

_LABEL_RE = re.compile(r"^.*/(node-\d+)/.*?\[(.*?)\]/.*$")
_PORTCHANNEL_RE = re.compile(r"\[Po\d+\]")
_DESC_KEY_RE = re.compile(r"^.*\]")

# The Ansible `uri` module's imdata entries wrap attributes under an object
# whose key depends on the queried class; source selects which wrapper to unpack.
_SOURCE_WRAPPER_KEY = {
    "ingress": "eqptIngrTotalHist15min",
    "egress": "eqptEgrTotalHist15min",
}


def _decode_label(dn: str) -> str:
    m = _LABEL_RE.match(dn)
    if not m:
        return dn
    return f"leaf {m.group(1)} {m.group(2)}"


def _description_for(dn: str, desc_map: dict[str, str]) -> str:
    m = _DESC_KEY_RE.match(dn)
    key = m.group(0) if m else ""
    return desc_map.get(key, "N/A") if key else "N/A"


def main() -> None:
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError:
        print("[]")
        return

    fields = payload.get("fields") or {}
    args = payload.get("args") or {}

    source = str(args.get("source") or "ingress").strip()
    util_threshold = to_float(args.get("util_threshold"), 25.0)
    top_n = to_int(args.get("top_n"), 10)

    items = fields.get(source) or []
    if not isinstance(items, list):
        items = []

    desc_map_raw = fields.get("interface_description_map") or {}
    desc_map: dict[str, str] = desc_map_raw if isinstance(desc_map_raw, dict) else {}

    wrapper = _SOURCE_WRAPPER_KEY.get(source)

    enriched: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        attrs: Any = item
        if wrapper and wrapper in item and isinstance(item[wrapper], dict):
            attrs = item[wrapper].get("attributes") or {}
        if not isinstance(attrs, dict):
            continue

        dn = str(attrs.get("dn") or "")
        if not dn or _PORTCHANNEL_RE.search(dn):
            continue

        util_avg = to_float(attrs.get("utilAvg"))
        util_max = to_float(attrs.get("utilMax"))
        if util_avg <= util_threshold:
            continue

        label = _decode_label(dn)
        row = dict(attrs)
        row["utilAvg"] = util_avg
        row["utilMax"] = util_max
        row["interface_label"] = label
        row["description"] = _description_for(dn, desc_map)

        existing = enriched.get(label)
        if existing is None or util_max > existing.get("utilMax", 0.0):
            enriched[label] = row

    ordered = sorted(enriched.values(), key=lambda r: r.get("utilMax", 0.0), reverse=True)
    print(json.dumps(ordered[:top_n]))


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        sys.stderr.write(f"Error: {exc}\n")
        sys.exit(2)
