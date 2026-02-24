# internal.core/plugins/filter/dates.py

try:
    from ansible_collections.internal.core.plugins.module_utils.date_utils import (
        parse_iso_epoch as _parse_iso_epoch,
        safe_iso_to_epoch,
    )
except ImportError:
    import importlib.util
    from pathlib import Path

    _helper_path = Path(__file__).resolve().parents[1] / "module_utils" / "date_utils.py"
    _spec = importlib.util.spec_from_file_location("internal_core_date_utils", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _parse_iso_epoch = _mod.parse_iso_epoch
    safe_iso_to_epoch = _mod.safe_iso_to_epoch


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

    for item in items:
        epoch = _parse_iso_epoch(item.get(date_key, ""))
        if epoch is None:
            continue
        age_secs = current_epoch - epoch
        if age_secs < threshold_secs:
            continue
        results.append({**item, "age_days": age_secs // 86400})

    return results


class FilterModule(object):
    def filters(self):
        return {
            "filter_by_age": filter_by_age,
            "safe_iso_to_epoch": safe_iso_to_epoch,
        }
