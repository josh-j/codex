"""Jinja2-based ``when`` expression evaluator for alerts, visible_if, and style_rules."""

from __future__ import annotations

import functools
import logging
from datetime import datetime, timezone
from typing import Any

from jinja2 import Undefined
from jinja2.nativetypes import NativeEnvironment

from ncs_reporter.primitives import SECONDS_PER_DAY

logger = logging.getLogger(__name__)


def _parse_iso(ts: str) -> datetime | None:
    """Parse an ISO-8601 timestamp, returning a UTC-aware datetime or None."""
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc)
    except (ValueError, TypeError):
        pass
    ts = ts.rstrip("Z")
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(ts, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def _age_days(value: Any, reference: Any = None) -> float:
    """Jinja2 filter: return days since an ISO-8601 timestamp.

    Usage in ``when`` expressions::

        last_backup | age_days > 7
        last_backup | age_days(reference_timestamp) > 7
    """
    dt = _parse_iso(str(value)) if not isinstance(value, datetime) else value
    if dt is None:
        return 0.0

    if reference is not None:
        ref_dt = _parse_iso(str(reference)) if not isinstance(reference, datetime) else reference
        ref_dt = ref_dt or datetime.now(timezone.utc)
    else:
        ref_dt = datetime.now(timezone.utc)

    return (ref_dt - dt).total_seconds() / SECONDS_PER_DAY


@functools.lru_cache(maxsize=1)
def _build_jinja_env() -> NativeEnvironment:
    env = NativeEnvironment(undefined=Undefined)
    env.filters["age_days"] = _age_days
    return env


def evaluate_when(expression: str, fields: dict[str, Any]) -> bool:
    """Evaluate a Jinja2 ``when`` expression against *fields* and return a bool.

    Returns ``False`` for undefined variables, render errors, or falsy results.
    """
    env = _build_jinja_env()
    try:
        tmpl = env.from_string("{{ " + expression + " }}")
        result = tmpl.render(**fields)
    except Exception:
        logger.debug("when expression failed: %r", expression, exc_info=True)
        return False

    if isinstance(result, Undefined):
        return False

    return bool(result)
