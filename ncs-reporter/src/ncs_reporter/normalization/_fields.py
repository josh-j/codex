"""Field resolution, coercion, script execution, and list processing."""

from __future__ import annotations

import json
import logging
import re as _re
import subprocess
import sys
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from ncs_reporter.primitives import safe_list

from ._when import _parse_iso
from ._transforms import _PARAM_TRANSFORMS, _TRANSFORMS


def traverse(obj: Any, segments: Iterable[str]) -> Any:
    """Walk dotted segments, treating numeric segments as list indices.

    Returns ``None`` for missing dict keys, out-of-range list indices, or
    scalar dead ends. Empty segments are skipped (so trailing/leading
    dots in a path are tolerated).

    Shared between ``resolve_field`` (Jinja-aware bundle traversal) and
    the DSL's ``_path_get`` (item/parent traversal in normalize specs).
    """
    current = obj
    for segment in segments:
        if not segment:
            continue
        if isinstance(current, dict):
            current = current.get(segment)
        elif isinstance(current, list) and segment.lstrip("-").isdigit():
            idx = int(segment)
            current = current[idx] if -len(current) <= idx < len(current) else None
        else:
            return None
    return current

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Script field execution
# ---------------------------------------------------------------------------

def _resolve_script(script: str, schema_source_path: str | None) -> Path | None:
    """
    Resolve *script* to an executable path.  Search order:
      1. Absolute path (used as-is if it exists)
      2. Relative to the schema file's directory
      3. Relative to the schema file's directory under scripts/
      4. CWD-relative
      5. CWD-relative under scripts/
    """
    p = Path(script)
    if p.is_absolute():
        return p if p.exists() else None

    if schema_source_path:
        schema_dir = Path(schema_source_path).parent
        for candidate in (schema_dir / script, schema_dir / "scripts" / script):
            if candidate.exists():
                return candidate

    if p.exists():
        return p

    candidate = Path("scripts") / script
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
      - Numeric segments index into lists: ``"results.0.json.imdata.0.cur"``
      - Optional pipe transforms (chainable): ``"interfaces | len_if_list"``
      - Parameterized transforms: ``"lines | regex_extract('(\\d+) upgraded')"``
    """
    parts = path.split(" | ")
    path_part = parts[0].strip()
    transforms = parts[1:] if len(parts) > 1 else []

    obj: Any = traverse(raw, (seg.strip() for seg in path_part.split(".")))

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


