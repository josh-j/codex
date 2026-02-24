#!/usr/bin/env python3

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
from pathlib import Path
import importlib.util

try:
    from ansible_collections.internal.core.plugins.module_utils.report_view_models import (
        build_site_dashboard_view as _build_site_dashboard_view,
        default_report_skip_keys as _default_report_skip_keys,
        build_stig_host_view as _build_stig_host_view,
        build_stig_fleet_view as _build_stig_fleet_view,
    )
except ImportError:
    _helper_path = Path(__file__).resolve().parents[1] / "module_utils" / "report_view_models.py"
    _spec = importlib.util.spec_from_file_location("internal_core_report_view_models", _helper_path)
    _mod = importlib.util.module_from_spec(_spec)
    assert _spec is not None and _spec.loader is not None
    _spec.loader.exec_module(_mod)
    _build_site_dashboard_view = _mod.build_site_dashboard_view
    _default_report_skip_keys = _mod.default_report_skip_keys
    _build_stig_host_view = _mod.build_stig_host_view
    _build_stig_fleet_view = _mod.build_stig_fleet_view


_DEFAULT_SHARED_CSS_PATH = (
    Path(__file__).resolve().parents[2] / "roles" / "reporting" / "templates" / "report_shared.css"
)
_SHARED_CSS_CACHE = None
_SHARED_CSS_MTIME_NS = None
_SHARED_CSS_RESOLVED_PATH = None


def _candidate_shared_css_paths():
    env_path = os.environ.get("NCS_SHARED_REPORT_CSS_PATH", "").strip()
    candidates = []
    if env_path:
        candidates.append(Path(env_path).expanduser())
    candidates.append(_DEFAULT_SHARED_CSS_PATH)
    return candidates


def _resolve_shared_css_path():
    for path in _candidate_shared_css_paths():
        if path.is_file():
            return path
    searched = ", ".join(str(p) for p in _candidate_shared_css_paths())
    raise RuntimeError(
        "internal.core.shared_report_css could not locate report_shared.css. "
        "Searched: " + searched
    )


def shared_report_css(_value=None):
    """
    Return the shared report stylesheet contents from the core collection.
    """
    global _SHARED_CSS_CACHE, _SHARED_CSS_MTIME_NS, _SHARED_CSS_RESOLVED_PATH
    path = _resolve_shared_css_path()
    stat = path.stat()
    if (
        _SHARED_CSS_CACHE is None
        or _SHARED_CSS_MTIME_NS != stat.st_mtime_ns
        or _SHARED_CSS_RESOLVED_PATH != path
    ):
        _SHARED_CSS_CACHE = path.read_text(encoding="utf-8")
        _SHARED_CSS_MTIME_NS = stat.st_mtime_ns
        _SHARED_CSS_RESOLVED_PATH = path
    return _SHARED_CSS_CACHE


def site_dashboard_view(
    aggregated_hosts,
    groups=None,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    return _build_site_dashboard_view(
        aggregated_hosts,
        inventory_groups=groups,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )


def report_skip_keys(_value=None):
    """Return canonical structural/state keys excluded from host report loops."""
    return _default_report_skip_keys()


def stig_host_view(
    stig_payload,
    hostname=None,
    audit_type="stig",
    platform=None,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    return _build_stig_host_view(
        hostname or "unknown",
        audit_type,
        stig_payload,
        platform=platform,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )


def stig_fleet_view(
    aggregated_hosts,
    report_stamp=None,
    report_date=None,
    report_id=None,
):
    return _build_stig_fleet_view(
        aggregated_hosts,
        report_stamp=report_stamp,
        report_date=report_date,
        report_id=report_id,
    )


class FilterModule(object):
    def filters(self):
        return {
            "shared_report_css": shared_report_css,
            "site_dashboard_view": site_dashboard_view,
            "report_skip_keys": report_skip_keys,
            "stig_host_view": stig_host_view,
            "stig_fleet_view": stig_fleet_view,
        }
