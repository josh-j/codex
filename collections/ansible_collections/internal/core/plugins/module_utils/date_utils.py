"""Reusable date parsing helpers for filters and report normalization."""

import re
from datetime import datetime, timezone

_ISO_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def parse_iso_epoch(raw):
    """
    Extract date/time from an ISO-ish string, ignoring timezone suffix.
    Returns unix timestamp (int) or None if unparseable.
    """
    match = _ISO_RE.match(raw if isinstance(raw, str) else "")
    if not match:
        return None
    try:
        dt = datetime.strptime(f"{match.group(1)} {match.group(2)}", "%Y-%m-%d %H:%M:%S")
        return int(dt.replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None


def safe_iso_to_epoch(raw, default=0):
    epoch = parse_iso_epoch(raw)
    if epoch is None:
        return int(default)
    return int(epoch)
