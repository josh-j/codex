"""Re-export shim — canonical source is ncs_core.primitives."""

try:
    from ncs_core.primitives import (
        as_list,
        build_alert,
        build_count_alert,
        build_threshold_alert,
        canonical_severity,
        normalize_detail,
        safe_list,
        threshold_severity,
        to_float,
        to_int,
    )
except ImportError:
    import importlib.util
    import sys
    from pathlib import Path

    _src = Path(__file__).resolve().parents[5] / "libs" / "ncs_core" / "src" / "ncs_core" / "primitives.py"
    _spec = importlib.util.spec_from_file_location("ncs_core.primitives", _src)
    assert _spec is not None and _spec.loader is not None
    _mod = importlib.util.module_from_spec(_spec)
    sys.modules["ncs_core.primitives"] = _mod
    _spec.loader.exec_module(_mod)

    from ncs_core.primitives import (  # type: ignore[no-redef]  # noqa: F401
        as_list,
        build_alert,
        build_count_alert,
        build_threshold_alert,
        canonical_severity,
        normalize_detail,
        safe_list,
        threshold_severity,
        to_float,
        to_int,
    )
