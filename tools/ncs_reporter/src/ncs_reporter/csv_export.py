"""Generic CSV writer for ncs_reporter."""

import csv
import re
from pathlib import Path
from typing import Any


def header_to_key(header: str) -> str:
    """Convert a display header to a snake_case dict key.

    >>> header_to_key("App Name")
    'app_name'
    >>> header_to_key("Current Version")
    'current_version'
    """
    return re.sub(r"\s+", "_", header.strip()).lower()


def _format_value(value: Any) -> str:
    """Normalize a cell value for CSV output."""
    if isinstance(value, list):
        return "; ".join(str(v) for v in value)
    text = str(value) if value is not None else ""
    return text.replace("\n", " ").replace("\r", "")


def export_csv(
    rows: list[dict[str, Any]],
    headers: list[str],
    output_path: str | Path,
    sort_by: str | None = None,
    key_map: dict[str, str] | None = None,
) -> None:
    """Write *rows* (list of dicts) to *output_path* as CSV.

    Parameters
    ----------
    rows : list[dict]
        Data rows.
    headers : list[str]
        Column headers (display names).
    output_path : str | Path
        Destination file path.
    sort_by : str | None
        Header name to sort rows by (case-insensitive compare).
    key_map : dict | None
        Optional ``{header: key}`` overrides.  Headers not present in
        *key_map* are auto-derived via :func:`header_to_key`.
    """
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    k_map = dict(key_map) if key_map else {}
    resolved = {h: k_map.get(h, header_to_key(h)) for h in headers}

    if sort_by and sort_by in resolved:
        s_key = resolved[sort_by]
        rows = sorted(rows, key=lambda r: str(r.get(s_key, "")).lower())

    with open(path, "w", newline="") as fh:
        writer = csv.writer(fh, quoting=csv.QUOTE_MINIMAL)
        writer.writerow(headers)
        for row in rows:
            writer.writerow([_format_value(row.get(resolved[h], "")) for h in headers])
