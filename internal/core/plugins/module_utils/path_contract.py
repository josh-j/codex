"""Path contract resolver shared by collector runtime in Ansible collection."""

from __future__ import annotations

from pathlib import Path
from string import Formatter
from typing import Any

import yaml


REQUIRED_PATH_KEYS = {
    "raw_stig_artifact",
    "report_fleet",
    "report_node_latest",
    "report_node_historical",
    "report_stig_host",
    "report_search_entry",
    "report_site",
    "report_stig_fleet",
}

_ALLOWED_TEMPLATE_FIELDS = {"report_dir", "hostname", "schema_name", "target_type", "report_stamp"}
_REQUIRED_TEMPLATE_FIELDS: dict[str, set[str]] = {
    "raw_stig_artifact": {"report_dir", "hostname", "target_type"},
    "report_fleet": {"report_dir", "schema_name"},
    "report_node_latest": {"report_dir", "hostname"},
    "report_node_historical": {"report_dir", "hostname", "report_stamp"},
    "report_stig_host": {"report_dir", "hostname", "target_type"},
    "report_search_entry": {"report_dir", "hostname"},
    "report_site": set(),
    "report_stig_fleet": set(),
}


def _placeholders(template: str) -> set[str]:
    out: set[str] = set()
    for _, field_name, _, _ in Formatter().parse(template):
        if field_name:
            out.add(field_name)
    return out


def _validate_template(key: str, template: str) -> None:
    if not isinstance(template, str) or not template.strip():
        raise ValueError(f"paths.{key} must be a non-empty string")
    found = _placeholders(template)
    unknown = sorted(found - _ALLOWED_TEMPLATE_FIELDS)
    if unknown:
        raise ValueError(f"paths.{key} has unknown placeholder(s): {', '.join(unknown)}")
    missing = sorted(_REQUIRED_TEMPLATE_FIELDS[key] - found)
    if missing:
        raise ValueError(f"paths.{key} missing required placeholder(s): {', '.join(missing)}")


def validate_platforms_config_dict(raw: dict[str, Any]) -> list[dict[str, Any]]:
    platforms = raw.get("platforms", [])
    if not isinstance(platforms, list):
        raise ValueError("platforms config must contain a 'platforms' list")
    out: list[dict[str, Any]] = []
    for idx, p in enumerate(platforms):
        if not isinstance(p, dict):
            raise ValueError(f"platforms[{idx}] must be a mapping")
        for req in ("input_dir", "report_dir", "platform", "state_file", "target_types", "paths"):
            if req not in p:
                raise ValueError(f"platforms[{idx}] missing required field '{req}'")
        if not isinstance(p.get("target_types"), list) or not p.get("target_types"):
            raise ValueError(f"platforms[{idx}].target_types must be a non-empty list")
        paths = p.get("paths")
        if not isinstance(paths, dict):
            raise ValueError(f"platforms[{idx}].paths must be a mapping")
        missing_keys = sorted(REQUIRED_PATH_KEYS - set(paths.keys()))
        if missing_keys:
            raise ValueError(f"platforms[{idx}].paths missing required keys: {', '.join(missing_keys)}")
        for key in REQUIRED_PATH_KEYS:
            _validate_template(key, str(paths[key]))
        out.append(p)
    build_target_type_index(out)
    return out


def load_platforms_config_file(path: str | Path) -> list[dict[str, Any]]:
    p = Path(path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError(f"invalid platforms config {p}: expected mapping root")
    return validate_platforms_config_dict(raw)


def build_target_type_index(platforms: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    index: dict[str, dict[str, Any]] = {}
    for p in platforms:
        for t in p.get("target_types", []):
            key = str(t).strip().lower()
            if not key:
                continue
            if key in index:
                continue
            index[key] = p
    return index


def resolve_platform_for_target_type(
    platforms: list[dict[str, Any]],
    target_type: str,
) -> dict[str, Any]:
    index = build_target_type_index(platforms)
    key = str(target_type).strip().lower()
    if key not in index:
        raise ValueError(f"unknown target_type '{target_type}'")
    return index[key]


def render_contract_path(template: str, **values: str) -> str:
    try:
        return template.format(**values)
    except KeyError as exc:
        raise ValueError(f"missing template value '{exc.args[0]}'") from exc
