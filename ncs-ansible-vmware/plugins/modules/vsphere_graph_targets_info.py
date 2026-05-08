#!/usr/bin/python
"""Resolve VMware STIG/task targets from collected vSphere graph artifacts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from ansible.module_utils.basic import AnsibleModule


DOCUMENTATION = r"""
---
module: vsphere_graph_targets_info
short_description: Resolve targets from collected vSphere graph artifacts
options:
  report_directory:
    type: path
    required: true
  target_type:
    type: str
    required: true
    choices: [esxi, vm, vcsa]
author:
  - NCS
"""


def _read_graphs(report_directory: str) -> list[dict[str, Any]]:
    root = Path(report_directory)
    graphs: list[dict[str, Any]] = []
    for raw_path in sorted((root / "vsphere").rglob("raw.yaml")) if (root / "vsphere").is_dir() else []:
        try:
            bundle = yaml.safe_load(raw_path.read_text(encoding="utf-8")) or {}
        except Exception:
            continue
        if not isinstance(bundle, dict):
            continue
        data = bundle.get("data")
        if isinstance(data, dict) and data.get("kind") == "vsphere_graph":
            graphs.append(data)
    return graphs


def _targets(graphs: list[dict[str, Any]], target_type: str) -> list[str]:
    if target_type == "esxi":
        values = [str(row.get("name") or "") for graph in graphs for row in graph.get("hosts", []) if isinstance(row, dict)]
    elif target_type == "vm":
        values = [str(row.get("name") or "") for graph in graphs for row in graph.get("vms", []) if isinstance(row, dict)]
    elif target_type == "vcsa":
        values = [
            str(row.get("hostname") or row.get("name") or "")
            for graph in graphs
            for row in graph.get("vcenters", [])
            if isinstance(row, dict)
        ]
    else:
        values = []
    return sorted({value for value in values if value})


def run_module() -> None:
    module = AnsibleModule(
        argument_spec={
            "report_directory": {"type": "path", "required": True},
            "target_type": {"type": "str", "required": True, "choices": ["esxi", "vm", "vcsa"]},
        },
        supports_check_mode=True,
    )
    graphs = _read_graphs(module.params["report_directory"])
    targets = _targets(graphs, module.params["target_type"])
    module.exit_json(changed=False, graphs=len(graphs), targets=targets, count=len(targets))


if __name__ == "__main__":
    run_module()

