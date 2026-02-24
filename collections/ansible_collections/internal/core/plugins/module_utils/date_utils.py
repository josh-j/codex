"""Reusable date parsing helpers for filters and report normalization."""

import re
from datetime import datetime, timezone

_ISO_RE = re.compile(r"^\s*(\d{4}-\d{2}-\d{2})T(\d{2}:\d{2}:\d{2})")


def parse_iso_epoch(raw):
    """
    Extract date/time from an ISO-ish string.
    Supports YYYY-MM-DDTHH:MM:SS, YYYY-MM-DD HH:MM:SS, and variants with milliseconds/offsets.
    Returns unix timestamp (int) or None if unparseable.
    """
    if not isinstance(raw, str):
        return None

    # Normalise common variations to a format strptime can handle or fromisoformat
    clean = raw.strip().replace(" ", "T")

    try:
        # try fromisoformat first (Python 3.7+)
        dt = datetime.fromisoformat(clean)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return int(dt.timestamp())
    except (ValueError, AttributeError):
        # Fallback for older or weirder formats
        match = _ISO_RE.match(clean)
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
