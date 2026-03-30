"""Field resolution, coercion, script execution, and list processing."""

from __future__ import annotations

import json
import logging
import re as _re
import subprocess
import sys
from pathlib import Path
from typing import Any

from ncs_reporter.primitives import safe_list

from ._when import _parse_iso, eval_expression
from ._transforms import _PARAM_TRANSFORMS, _TRANSFORMS

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Script field execution
# ---------------------------------------------------------------------------

# Built-in scripts shipped with the package
_BUILTIN_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"


def _resolve_script(script: str, schema_source_path: str | None) -> Path | None:
    """
    Resolve *script* to an executable path.  Search order:
      1. Absolute path (used as-is if it exists)
      2. Relative to the schema file's directory
      3. CWD-relative
      4. Built-in package scripts/
    """
    p = Path(script)
    if p.is_absolute():
        return p if p.exists() else None

    if schema_source_path:
        candidate = Path(schema_source_path).parent / script
        if candidate.exists():
            return candidate

    if p.exists():
        return p

    candidate = _BUILTIN_SCRIPTS_DIR / script
    if candidate.exists():
        return candidate

    return None


# Interpreter commands keyed by file extension.  Used by _run_script_field()
# to invoke scripts without requiring a shebang / chmod.
_INTERPRETERS: dict[str, list[str]] = {
    ".py": [sys.executable],
    ".ps1": ["pwsh", "-NoProfile", "-File"],
    ".sh": ["bash"],
}

# Sentinel object returned by _run_script_field on rc >= 2 / timeout / crash.
# Distinct from None (data absent) so the script pass can tell them apart.
_SCRIPT_ERROR_SENTINEL = object()


def _run_script_field(
    script_path: Path,
    fields: dict[str, Any],
    args: dict[str, Any],
    timeout: int,
) -> Any:
    """
    Invoke *script_path* as a subprocess.

    stdin  — JSON: ``{"fields": {...}, "args": {...}}``
    stdout — JSON-serialised return value
    exit 0 — value used; non-zero — None returned (caller uses fallback)

    .py files are executed with the current interpreter so no shebang / chmod
    is required for built-in scripts.
    """
    payload = json.dumps({"fields": fields, "args": args})
    cmd: list[str] = [*_INTERPRETERS.get(script_path.suffix, []), str(script_path)]
    # Return-code convention:
    #   0  — success; stdout is the JSON value
    #   1  — data not available on this host (normal); use fallback, no warning
    #   2+ — script error / broken path; use sentinel, log warning
    try:
        result = subprocess.run(
            cmd,
            input=payload,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        if result.returncode == 0:
            return json.loads(result.stdout.strip())
        if result.returncode == 1:
            # Data absent — caller uses fallback quietly.
            return None
        # rc >= 2: something is broken
        logger.warning(
            "Script %s exited %d (broken): %s",
            script_path,
            result.returncode,
            result.stderr.strip()[:200],
        )
        return _SCRIPT_ERROR_SENTINEL
    except subprocess.TimeoutExpired:
        logger.warning("Script %s timed out after %ds", script_path, timeout)
        return _SCRIPT_ERROR_SENTINEL
    except Exception as exc:
        logger.warning("Script %s failed: %s", script_path, exc)
        return _SCRIPT_ERROR_SENTINEL


# ---------------------------------------------------------------------------
# Field resolution
# ---------------------------------------------------------------------------


_PARAM_RE = _re.compile(r"^(\w+)\((.+)\)$")


def _apply_transform(obj: Any, transform_str: str, full_path: str) -> Any:
    """Apply a single transform (simple or parameterized) to a value."""
    transform_str = transform_str.strip()
    # Check for parameterized transform: name(arg1, arg2, ...)
    m = _PARAM_RE.match(transform_str)
    if m:
        name = m.group(1)
        fn = _PARAM_TRANSFORMS.get(name)
        if fn is None:
            logger.warning("Unknown parameterized transform '%s' in path '%s'", name, full_path)
            return obj
        # Parse args: handle quoted strings and bare values
        raw_args = m.group(2)
        args = _parse_transform_args(raw_args)
        return fn(obj, *args)

    # Simple transform
    transform = _TRANSFORMS.get(transform_str)
    if transform is None:
        logger.warning("Unknown transform '%s' in path '%s'", transform_str, full_path)
        return obj
    return transform(obj)


def _parse_transform_args(raw: str) -> list[str]:
    """Parse transform arguments, respecting quoted strings.

    Quoted values preserve their content exactly (no stripping).
    Unquoted values are stripped of whitespace.
    Backslashes inside quotes are treated literally.
    """
    args: list[str] = []
    current = ""
    in_quote: str | None = None
    has_quote = False
    for ch in raw:
        if in_quote is not None:
            if ch == in_quote:
                in_quote = None
                continue
            current += ch
            continue
        if ch in ("'", '"'):
            in_quote = ch
            has_quote = True
            # Discard any unquoted whitespace accumulated before the quote
            current = current.rstrip()
            continue
        if ch == ",":
            args.append(current if has_quote else current.strip())
            current = ""
            has_quote = False
            continue
        current += ch
    final = current if has_quote else current.strip()
    if final or has_quote:
        args.append(final)
    return args


def resolve_field(path: str, raw: dict[str, Any]) -> Any:
    """
    Resolve a field path against *raw*.

    Syntax:
      - Dot-notation traversal: ``"ansible_facts.hostname"``
      - Optional pipe transforms (chainable): ``"interfaces | len_if_list"``
      - Parameterized transforms: ``"lines | regex_extract('(\\d+) upgraded')"``
    """
    parts = path.split(" | ")
    path_part = parts[0].strip()
    transforms = parts[1:] if len(parts) > 1 else []

    obj: Any = raw
    for segment in path_part.split("."):
        segment = segment.strip()
        if not segment:
            continue
        if isinstance(obj, dict):
            obj = obj.get(segment)
        else:
            obj = None
            break

    for t in transforms:
        obj = _apply_transform(obj, t, path)

    return obj


_FALSY_STRINGS: frozenset[str] = frozenset({"false", "no", "0", "off", ""})


def _coerce_bool(value: Any) -> bool:
    """Coerce a value to bool, handling string representations from Ansible modules.

    The vmware.vmware.appliance_info module returns shell.enabled as the string
    "False" / "True" rather than a Python bool.  Python's built-in bool() treats
    any non-empty string as True, so a plain bool() coercer would incorrectly mark
    "False" as enabled.  This handles that case.
    """
    if isinstance(value, str):
        return value.lower() not in _FALSY_STRINGS
    return bool(value)


def _coerce_bytes(value: Any) -> int:
    """Coerce to int bytes."""
    return int(float(value))


def _coerce_percentage(value: Any) -> float:
    """Coerce to float percentage."""
    v = float(value)
    # If it's already 0-100, return as-is. If it's 0-1, maybe multiply?
    # Usually we expect it to be 0-100 if typed as percentage.
    return v


def _coerce_datetime(value: Any) -> str:
    """Coerce to ISO 8601 string."""
    if isinstance(value, str):
        # Try parse and format to standard ISO
        dt = _parse_iso(value)
        if dt:
            return dt.isoformat()
    return str(value)


def _coerce_duration(value: Any) -> float:
    """Coerce to duration in seconds."""
    return float(value)


_TYPE_COERCERS: dict[str, Any] = {
    "str": str,
    "int": int,
    "float": float,
    "bool": _coerce_bool,
    "list": safe_list,
    "dict": dict,
    "bytes": _coerce_bytes,
    "percentage": _coerce_percentage,
    "datetime": _coerce_datetime,
    "duration_seconds": _coerce_duration,
}


# Type-appropriate sentinel values shown when a path is provably broken.
# Deliberately wrong-looking so problems are visible in the rendered report.
_TYPE_SENTINELS: dict[str, Any] = {
    "str": "ERROR",
    "int": -1,
    "float": -1.0,
}


def _get_sentinel(spec: Any) -> Any:
    """Return the sentinel for a broken path field."""
    if spec.sentinel is not None:
        return spec.sentinel
    return _TYPE_SENTINELS.get(spec.type, spec.fallback)


def _coerce(value: Any, type_name: str, fallback: Any) -> Any:
    if value is None:
        return fallback
    coercer = _TYPE_COERCERS.get(type_name)
    if coercer is None:
        return value
    try:
        if type_name == "list":
            return safe_list(value)
        if type_name == "dict":
            return value if isinstance(value, dict) else fallback
        return coercer(value)
    except (TypeError, ValueError):
        return fallback


def _matches_filter_rules(item: dict[str, Any], rules: dict[str, list[str]]) -> bool:
    """Check if a dict item matches any filter rule (field → pattern list)."""
    for field_name, patterns in rules.items():
        val = str(item.get(field_name) or "")
        for pat in patterns:
            if pat.startswith("^"):
                if _re.search(pat, val):
                    return True
            else:
                if pat.lower() == val.lower():
                    return True
    return False


def _apply_list_filter(items: list[Any], filter_spec: Any) -> list[Any]:
    """Apply list_filter (exclude/include) to a list of dicts."""
    result: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        if _matches_filter_rules(item, filter_spec.exclude):
            continue
        if filter_spec.include and not _matches_filter_rules(item, filter_spec.include):
            continue
        result.append(item)
    return result


def _apply_list_map(items: list[Any], map_spec: dict[str, str]) -> list[Any]:
    """Apply list_map expressions to each item in a list, adding computed fields."""
    result: list[Any] = []
    for item in items:
        if not isinstance(item, dict):
            result.append(item)
            continue
        enriched = dict(item)
        for field_name, expression in map_spec.items():
            try:
                enriched[field_name] = round(eval_expression(expression, enriched), 2)
            except Exception:
                logger.debug("list_map expression '%s' failed for field '%s': %s", expression, field_name, item, exc_info=True)
                enriched[field_name] = 0.0
        result.append(enriched)
    return result


def _item_matches(item: dict[str, Any], conditions: dict[str, Any]) -> bool:
    """Check if a dict item matches all field=value conditions (case-insensitive for strings)."""
    for field_name, expected in conditions.items():
        val = item.get(field_name)
        if isinstance(val, str) and isinstance(expected, str):
            if val.lower() != expected.lower():
                return False
        elif val != expected:
            return False
    return True


def _apply_count_where(items: list[Any], conditions: dict[str, Any]) -> int:
    """Count list items where all field=value conditions match."""
    return sum(1 for item in items if isinstance(item, dict) and _item_matches(item, conditions))


def _apply_any_where(items: list[Any], conditions: dict[str, Any]) -> bool:
    """True if ANY list item matches all field=value conditions."""
    return any(isinstance(item, dict) and _item_matches(item, conditions) for item in items)


def _apply_all_where(items: list[Any], conditions: dict[str, Any]) -> bool:
    """True if ALL dict items match all field=value conditions. Empty list → True."""
    dict_items = [item for item in items if isinstance(item, dict)]
    return all(_item_matches(item, conditions) for item in dict_items)


def _apply_sum_field(items: list[Any], field_name: str) -> float:
    """Sum a numeric field across all dict items in the list."""
    total = 0.0
    for item in items:
        if isinstance(item, dict):
            val = item.get(field_name)
            if val is not None:
                try:
                    total += float(val)
                except (TypeError, ValueError):
                    pass
    return total


def _apply_list_processing(value: Any, spec: Any) -> Any:
    """Apply list_filter, list_map, and aggregation to a resolved value."""
    items = value if isinstance(value, list) else []
    has_aggregation = spec.count_where is not None or spec.any_where is not None or spec.all_where is not None or spec.sum_field is not None
    has_list_ops = spec.list_filter is not None or spec.list_map

    if not has_aggregation and not has_list_ops:
        return value

    # Step 1: apply list_filter if present
    if spec.list_filter is not None:
        items = _apply_list_filter(items, spec.list_filter)

    # Step 2: aggregation (mutually exclusive, returns non-list)
    if spec.count_where is not None:
        return _apply_count_where(items, spec.count_where)
    if spec.any_where is not None:
        return _apply_any_where(items, spec.any_where)
    if spec.all_where is not None:
        return _apply_all_where(items, spec.all_where)
    if spec.sum_field is not None:
        return _apply_sum_field(items, spec.sum_field)

    # Step 3: list_map (non-aggregating, returns list)
    if spec.list_map:
        items = _apply_list_map(items, spec.list_map)

    return items
