"""Common normalization utilities for all platforms."""

from typing import Any
from ncs_reporter.date_utils import parse_iso_epoch
from ncs_reporter.primitives import safe_list


def filter_by_age(items: list[Any], current_epoch: int, age_threshold_days: int, date_key: str = "creation_time") -> list[dict[str, Any]]:
    """
    Filters a list of dicts to those where date_key is at or over
    age_threshold_days old relative to current_epoch.
    """
    current_epoch = int(current_epoch)
    threshold_secs = int(age_threshold_days) * 86400
    results = []

    for item in safe_list(items):
        if not isinstance(item, dict):
            continue
        epoch = parse_iso_epoch(item.get(date_key, ""))
        if epoch is None:
            continue
        age_secs = current_epoch - epoch
        if age_secs < threshold_secs:
            continue
        results.append({**item, "age_days": age_secs // 86400})

    return results
