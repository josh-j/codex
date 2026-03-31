from __future__ import annotations

from pathlib import PurePosixPath
from string import Formatter


def _placeholders(template: str) -> set[str]:
    out: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            out.add(field_name)
    return out


def validate_template(template: str, *, allowed: set[str], required: set[str], field_name: str) -> None:
    found = _placeholders(template)
    unknown = sorted(found - allowed)
    if unknown:
        raise ValueError(f"{field_name}: unknown placeholder(s): {', '.join(unknown)}")
    missing = sorted(required - found)
    if missing:
        raise ValueError(f"{field_name}: missing required placeholder(s): {', '.join(missing)}")


def render_template(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError as exc:
        missing = exc.args[0]
        raise ValueError(f"missing template value: {missing}") from exc


def rel_href(from_dir: str, to_path: str) -> str:
    from_path = PurePosixPath(from_dir or ".")
    to = PurePosixPath(to_path)
    from_abs = PurePosixPath("/") / from_path
    to_abs = PurePosixPath("/") / to
    # PurePosixPath has no relpath; use pathlib-compatible parts math.
    from_parts = from_abs.parts
    to_parts = to_abs.parts
    i = 0
    while i < len(from_parts) and i < len(to_parts) and from_parts[i] == to_parts[i]:
        i += 1
    up = [".."] * (len(from_parts) - i)
    down = list(to_parts[i:])
    parts = up + down
    if not parts:
        return "."
    return "/".join(parts)
