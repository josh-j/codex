# internal.core/plugins/filter/dates.py

try:
    from ansible_collections.internal.core.plugins.module_utils.loader import load_module_utils
except ImportError:
    import importlib.util
    from pathlib import Path
    _loader_path = Path(__file__).resolve().parents[1] / "module_utils" / "loader.py"
    _spec = importlib.util.spec_from_file_location("internal_core_loader", _loader_path)
    assert _spec and _spec.loader
    _loader_mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_loader_mod)
    load_module_utils = _loader_mod.load_module_utils

_dates = load_module_utils(__file__, "date_utils", "date_utils.py")
_parse_iso_epoch = _dates.parse_iso_epoch
safe_iso_to_epoch = _dates.safe_iso_to_epoch

_prim = load_module_utils(__file__, "reporting_primitives", "reporting_primitives.py")
safe_list = _prim.safe_list


def filter_by_age(items, current_epoch, age_threshold_days, date_key="creation_time"):
    """
    Filters a list of dicts to those where date_key is at or over
    age_threshold_days old relative to current_epoch.
    Adds age_days to each returned item.

    Args:
        items:              list - dicts containing a date string at date_key
        current_epoch:      int  - current unix timestamp
        age_threshold_days: int  - minimum age in days to include
        date_key:           str  - key to read date from (default: 'creation_time')

    Returns:
        list of dicts with age_days injected
    """
    current_epoch = int(current_epoch)
    threshold_secs = int(age_threshold_days) * 86400
    results = []

    for item in safe_list(items):
        if not isinstance(item, dict):
            continue
        epoch = _parse_iso_epoch(item.get(date_key, ""))
        if epoch is None:
            continue
        age_secs = current_epoch - epoch
        if age_secs < threshold_secs:
            continue
        results.append({**item, "age_days": age_secs // 86400})

    return results


class FilterModule:
    def filters(self):
        return {
            "filter_by_age": filter_by_age,
            "safe_iso_to_epoch": safe_iso_to_epoch,
        }
