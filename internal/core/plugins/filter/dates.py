# internal.core/plugins/filter/dates.py

import re
from datetime import datetime, timezone

_ISO_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def _parse_iso_epoch(raw):
    """
    Extracts date and time from an ISO 8601 string, ignoring timezone suffix.
    Returns unix timestamp (int) or None if unparseable.
    """
    match = _ISO_RE.match(raw)
    if not match:
        return None
    try:
        dt = datetime.strptime(
            f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S"
        )
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


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
        return {"filter_by_age": filter_by_age}
