#!/usr/bin/env python3
"""Built-in script: enrich APIC interface utilization rows.

Processes a list of `eqptIngrTotalHist15min` / `eqptEgrTotalHist15min` imdata
envelopes into a flat list of rows suitable for a report table.

For each row it:
  - extracts the inner `attributes` dict
  - parses the DN to produce a human-readable `interface_label` (e.g. "leaf
    node-101 eth1/33") via a regex capture
  - resolves an interface `description` from the host-level
    ``interface_description_map`` (keyed by DN prefix up to the final ``]``)
  - coerces `utilAvg` / `utilMax` to floats
  - drops port-channel aggregate entries (DN ending in ``[PoN]``) — individual
    member ports are already represented
  - filters to rows where ``utilAvg > threshold`` (default 25)
  - deduplicates by ``interface_label``, keeping the row with the highest
    ``utilMax``
  - sorts descending by ``utilMax``
  - truncates to ``top_n`` rows (default 10)

stdin  - JSON: {"fields": {"ingress"|"egress": [...], "interface_description_map": {...}}, "args": {...}}
stdout - JSON list: enriched and filtered rows

args:
  source          — "ingress" (default) or "egress"; selects which field to read
  util_threshold  — numeric; rows with utilAvg <= threshold are dropped (default 25)
  top_n           — int; max rows to return (default 10)
"""

from __future__ import annotations

import json
import re
import sys
from typing import Any

_LABEL_RE = re.compile(r"^.*/(node-\d+)/.*?\[(.*?)\]/.*$")
_PORTCHANNEL_RE = re.compile(r"\[Po\d+\]")
_DESC_KEY_RE = re.compile(r"^.*\]")

# Per-source API wrapper key. The Ansible `uri` module's `imdata` entries wrap
# attributes under an object whose key depends on the queried class.
_SOURCE_WRAPPER_KEY = {
    "ingress": "eqptIngrTotalHist15min",
    "egress": "eqptEgrTotalHist15min",
}


def _to_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _decode_label(dn: str) -> str:
    m = _LABEL_RE.match(dn or "")
    if not m:
        return dn or ""
    return f"leaf {m.group(1)} {m.group(2)}"


def _description_for(dn: str, desc_map: dict[str, str]) -> str:
    m = _DESC_KEY_RE.match(dn or "")
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
    util_threshold = _to_float(args.get("util_threshold", 25))
    try:
        top_n = int(args.get("top_n", 10))
    except (TypeError, ValueError):
        top_n = 10

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

        util_avg = _to_float(attrs.get("utilAvg"))
        util_max = _to_float(attrs.get("utilMax"))
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
