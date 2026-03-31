"""Config loading and path resolution helpers for the NCS Reporter CLI."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import click
import pydantic
import yaml

from .models.platforms_config import DEFAULT_PATH_TEMPLATES, PlatformEntry, PlatformsConfig
from .platform_registry import default_registry

logger = logging.getLogger("ncs_reporter")

_USER_PLATFORMS_CONFIG = Path.home() / ".config" / "ncs_reporter" / "platforms.yaml"


def default_paths() -> dict[str, str]:
    return dict(DEFAULT_PATH_TEMPLATES)


def builtin_platforms() -> list[dict[str, Any]]:
    return [e.model_dump() for e in default_registry().entries]


def resolve_path_from_config_root(config_dir: str | None, value: str) -> str:
    p = Path(value)
    if p.is_absolute() or not config_dir:
        return str(p)
    return str(Path(config_dir) / p)


def load_config_yaml(config_dir: str | None) -> dict[str, Any]:
    """Load optional config.yaml from config_dir."""
    if not config_dir:
        return {}
    cfg_path = Path(config_dir) / "config.yaml"
    if not cfg_path.is_file():
        return {}
    with open(cfg_path, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}
    if not isinstance(raw, dict):
        raise click.ClickException(f"Invalid config file: {cfg_path} (expected YAML mapping)")
    return raw


def unique_preserve_order(values: list[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for v in values:
        if v in seen:
            continue
        seen.add(v)
        out.append(v)
    return tuple(out)


def resolve_config_dir(
    config_dir: str | None,
    extra_config_dir: tuple[str, ...],
    platforms_config: str | None,
    config_yaml: dict[str, Any],
) -> tuple[tuple[str, ...], str | None]:
    """Resolve config dirs + platforms config from a single config directory.

    Supported layouts:
      1. <config_dir>/platforms.yaml + <config_dir>/*.yaml configs
      2. <config_dir>/configs/platforms.yaml + <config_dir>/configs/*.yaml configs
      3. <config_dir>/schemas/platforms.yaml (deprecated, backward compat)
    """
    resolved_schema_dirs = list(extra_config_dir)
    resolved_platforms = platforms_config

    if not config_dir:
        return unique_preserve_order(resolved_schema_dirs), resolved_platforms

    root = Path(config_dir)

    cfg_extra = config_yaml.get("extra_config_dirs") or config_yaml.get("extra_schema_dirs")
    if isinstance(cfg_extra, list):
        for entry in cfg_extra:
            if isinstance(entry, str) and entry.strip():
                resolved_schema_dirs.append(resolve_path_from_config_root(config_dir, entry.strip()))

    if resolved_platforms is None:
        cfg_platforms = config_yaml.get("platforms_config")
        if isinstance(cfg_platforms, str) and cfg_platforms.strip():
            resolved_platforms = resolve_path_from_config_root(config_dir, cfg_platforms.strip())

    for cand in [root / "configs", root / "schemas", root]:
        if cand.is_dir():
            resolved_schema_dirs.append(str(cand))

    if resolved_platforms is None:
        for cand in [root / "platforms.yaml", root / "configs" / "platforms.yaml", root / "schemas" / "platforms.yaml"]:
            if cand.is_file():
                resolved_platforms = str(cand)
                break

    return unique_preserve_order(resolved_schema_dirs), resolved_platforms


def _format_validation_error(path: Path, exc: pydantic.ValidationError) -> str:
    lines = [f"Invalid platforms config {path}:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_platforms(
    explicit_path: str | None,
    extra_config_dirs: tuple[str, ...] = (),
) -> list[dict[str, Any]]:
    """Locate and load a platforms config YAML.

    Search order: explicit path → ./platforms.yaml → user config → schema-embedded metadata → built-ins.
    """
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path))
    candidates += [Path("platforms.yaml"), _USER_PLATFORMS_CONFIG]

    for path in candidates:
        if not path.is_file():
            continue
        try:
            with open(path) as f:
                raw = yaml.safe_load(f)
            config = PlatformsConfig.model_validate(raw)
            logger.info("Loaded platforms config from %s", path)
            return [p.model_dump() for p in config.platforms]
        except pydantic.ValidationError as exc:
            msg = _format_validation_error(path, exc)
            if explicit_path and path == Path(explicit_path):
                raise click.ClickException(msg) from exc
            logger.warning(msg)
        except Exception as exc:
            if explicit_path and path == Path(explicit_path):
                raise click.ClickException(f"Invalid platforms config {path}: {exc}") from exc
            logger.warning("Failed to load platforms config %s: %s", path, exc)

    # Fall back to schema-embedded platform metadata
    from .schema_loader import build_platform_entries_from_schemas, discover_schemas

    schemas = discover_schemas(extra_dirs=extra_config_dirs)
    schema_entries = build_platform_entries_from_schemas(schemas)
    if schema_entries:
        entries = [PlatformEntry.model_validate(e) for e in schema_entries]
        return [e.model_dump() for e in entries]

    return builtin_platforms()
