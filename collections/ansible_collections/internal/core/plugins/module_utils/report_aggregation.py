"""Re-export shim — canonical source is ncs_core.aggregation."""

try:
    from ncs_core.aggregation import (
        deep_merge,
        load_all_reports,
        read_report,
        write_output,
    )
except ImportError:
    import importlib.util
    import sys
    from pathlib import Path

    _ncs_core_src = Path(__file__).resolve().parents[5] / "libs" / "ncs_core" / "src" / "ncs_core"

    # Bootstrap primitives first (aggregation depends on it)
    if "ncs_core.primitives" not in sys.modules:
        _prim_path = _ncs_core_src / "primitives.py"
        _prim_spec = importlib.util.spec_from_file_location("ncs_core.primitives", _prim_path)
        assert _prim_spec is not None and _prim_spec.loader is not None
        _prim_mod = importlib.util.module_from_spec(_prim_spec)
        sys.modules["ncs_core.primitives"] = _prim_mod
        _prim_spec.loader.exec_module(_prim_mod)

    _agg_path = _ncs_core_src / "aggregation.py"
    _agg_spec = importlib.util.spec_from_file_location("ncs_core.aggregation", _agg_path)
    assert _agg_spec is not None and _agg_spec.loader is not None
    _agg_mod = importlib.util.module_from_spec(_agg_spec)
    sys.modules["ncs_core.aggregation"] = _agg_mod
    _agg_spec.loader.exec_module(_agg_mod)

    from ncs_core.aggregation import (  # type: ignore[no-redef]  # noqa: F401
        deep_merge,
        load_all_reports,
        read_report,
        write_output,
    )
