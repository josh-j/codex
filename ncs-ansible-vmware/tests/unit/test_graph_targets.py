from __future__ import annotations

from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "plugins" / "modules"))

from vsphere_graph_targets_info import _read_graphs, _targets


def test_graph_targets_reads_collected_graphs(tmp_path: Path) -> None:
    raw_dir = tmp_path / "vsphere" / "vcsa-01"
    raw_dir.mkdir(parents=True)
    graph = {
        "kind": "vsphere_graph",
        "hosts": [{"name": "esxi-01"}],
        "vms": [{"name": "app-01"}],
        "vcenters": [{"hostname": "vcsa-01"}],
    }
    (raw_dir / "raw.yaml").write_text(yaml.safe_dump({"data": graph}), encoding="utf-8")

    graphs = _read_graphs(str(tmp_path))

    assert _targets(graphs, "esxi") == ["esxi-01"]
    assert _targets(graphs, "vm") == ["app-01"]
    assert _targets(graphs, "vcsa") == ["vcsa-01"]

