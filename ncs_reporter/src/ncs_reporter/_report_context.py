"""Shared CLI helpers for report generation commands."""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml
from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)

_VIEW_MODEL_KEYS = {"report_stamp", "report_date", "report_id"}


# ---------------------------------------------------------------------------
# Cached Jinja environment
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=1)
def get_jinja_env() -> Environment:
    """Return a cached Jinja2 Environment configured for NCS templates."""
    from .view_models.common import status_badge_meta as _badge  # avoid circular

    template_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(template_dir),
        autoescape=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["status_badge_meta"] = _badge
    return env


# ---------------------------------------------------------------------------
# YAML loading
# ---------------------------------------------------------------------------


def load_hosts_data(input_file: str) -> dict[str, Any]:
    """Load a YAML file and extract the hosts mapping."""
    with open(input_file) as f:
        data = yaml.safe_load(f)
    if not isinstance(data, dict):
        return {}
    return dict(data.get("hosts", data))


def load_yaml(input_file: str) -> dict[str, Any]:
    """Load a YAML file and return the full dict."""
    with open(input_file) as f:
        data = yaml.safe_load(f)
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------------------
# Timestamps
# ---------------------------------------------------------------------------


def generate_timestamps(report_stamp: str | None = None) -> dict[str, Any]:
    """Build the full set of timestamp strings used by report commands."""
    now = datetime.now(tz=timezone.utc)
    stamp = report_stamp or now.strftime("%Y%m%d")
    date_str = now.strftime("%Y-%m-%d %H:%M:%S")
    rid = now.strftime("%Y%m%dT%H%M%SZ")
    now_date = now.strftime("%Y-%m-%d")
    return {
        "report_stamp": stamp,
        "report_date": date_str,
        "report_id": rid,
        "now_date": now_date,
        "now_datetime": date_str,
    }


def vm_kwargs(common_vars: dict[str, Any]) -> dict[str, Any]:
    """Extract only the keys accepted by view-model builder functions."""
    return {k: v for k, v in common_vars.items() if k in _VIEW_MODEL_KEYS}


# ---------------------------------------------------------------------------
# Report writing
# ---------------------------------------------------------------------------


def write_report(output_path: Path, base_name: str, content: str, stamp: str) -> None:
    """Write a stamped report and a 'latest' (un-stamped) copy."""
    stem, ext = base_name.rsplit(".", 1) if "." in base_name else (base_name, "html")
    stamped = output_path / f"{stem}_{stamp}.{ext}"
    latest = output_path / f"{stem}.{ext}"
    with open(stamped, "w") as f:
        f.write(content)
    with open(latest, "w") as f:
        f.write(content)
