#!/usr/bin/env python3

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
from pathlib import Path


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


class FilterModule(object):
    def filters(self):
        return {
            "shared_report_css": shared_report_css,
        }
