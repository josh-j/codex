"""Schema discovery, caching, and validation for YAML-driven report schemas."""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import pydantic
import yaml

from ncs_reporter.models.report_schema import PlatformSpec, ReportSchema

logger = logging.getLogger(__name__)

# Built-in schemas directory (ships with the package)
_BUILTIN_SCHEMAS_DIR = Path(__file__).parent / "schemas"

# User-level config directory
_USER_SCHEMAS_DIR = Path.home() / ".config" / "ncs_reporter" / "schemas"


def _resolve_refs(node: Any, root_path: Path) -> Any:
    """Recursively resolve $ref directives in the YAML schema."""
    if isinstance(node, dict):
        if "$ref" in node:
            ref_path = node["$ref"]
            parts = ref_path.split("#")
            file_part = parts[0]
            json_pointer = parts[1] if len(parts) > 1 else ""

            target_file = root_path.parent / file_part
            if not target_file.exists():
                raise ValueError(f"Schema reference not found: {target_file}")

            with open(target_file, encoding="utf-8") as f:
                target_data = yaml.safe_load(f)

            # Follow JSON pointer (e.g., /fields/some_field)
            if json_pointer:
                keys = [k for k in json_pointer.split("/") if k]
                for key in keys:
                    if isinstance(target_data, dict) and key in target_data:
                        target_data = target_data[key]
                    else:
                        raise ValueError(f"Pointer {json_pointer} not found in {target_file}")

            # Merge resolved data with any other keys in the current node (overriding ref data)
            resolved = dict(target_data) if isinstance(target_data, dict) else target_data
            if isinstance(resolved, dict):
                for k, v in node.items():
                    if k != "$ref":
                        resolved[k] = _resolve_refs(v, root_path)
            return resolved

        else:
            return {k: _resolve_refs(v, root_path) for k, v in node.items()}
    elif isinstance(node, list):
        return [_resolve_refs(item, root_path) for item in node]
    return node


def _resolve_includes(data: dict[str, Any], root_path: Path) -> dict[str, Any]:
    """Resolve $include directives in dict-valued sections (fields, alerts, etc.).

    ``$include`` merges the contents of an external YAML file into the current dict.
    Keys defined in the including file override keys from the included file.

    Example::

        fields:
          $include: "linux_base_fields.yaml"
          # local overrides here
          hostname:
            path: "different.path"
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)
    for section_key in ("fields",):
        section = result.get(section_key)
        if not isinstance(section, dict):
            continue
        include_path = section.pop("$include", None)
        if include_path is None:
            continue
        target_file = root_path.parent / include_path
        if not target_file.exists():
            raise ValueError(f"$include file not found: {target_file}")
        with open(target_file, encoding="utf-8") as f:
            included = yaml.safe_load(f)
        if not isinstance(included, dict):
            raise ValueError(f"$include file must be a YAML mapping: {target_file}")
        # Included fields go first, local overrides win
        merged = dict(included)
        merged.update(section)
        result[section_key] = merged

    return result


def _load_schema_file(path: Path) -> ReportSchema | None:
    """Load and validate a single schema YAML file. Returns None on error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.warning("Skipping %s: not a YAML mapping", path)
            return None

        # Skip fragment files (used via $include) — they lack required schema keys.
        if "name" not in data or "detection" not in data:
            logger.debug("Skipping %s: missing 'name'/'detection' (likely a fragment)", path)
            return None

        data = _resolve_refs(data, path)
        data = _resolve_includes(data, path)

        schema = ReportSchema.model_validate(data)
        object.__setattr__(schema, "_source_path", str(path))
        _attach_broken_paths(schema)
        return schema
    except Exception as exc:
        logger.warning("Failed to load schema %s: %s", path, exc)
        return None


def _attach_broken_paths(schema: ReportSchema) -> None:
    """
    Validate all path fields against the example bundle (if present) and store
    the set of broken field names as ``_broken_paths`` on the schema object.
    Broken paths are logged as warnings immediately so problems surface at
    startup, not silently at report generation time.
    """
    example = load_example_bundle(schema)
    if example is None:
        object.__setattr__(schema, "_broken_paths", frozenset())
        return

    broken = validate_schema_paths(schema, example)
    object.__setattr__(schema, "_broken_paths", frozenset(broken.keys()))

    for field_name, msg in broken.items():
        logger.warning("Schema '%s': %s", schema.name, msg)


def _scan_dir(directory: Path, result: dict[str, ReportSchema]) -> None:
    """Scan a directory for *.yaml / *.yml schema files (non-recursive)."""
    if not directory.is_dir():
        return
    for path in sorted(directory.iterdir()):
        if path.suffix not in {".yaml", ".yml"}:
            continue
        if path.stem in {"platforms", "config"}:
            continue  # platforms.yaml/config.yaml are CLI config files, not report schemas
        if path.stem.endswith(".example"):
            continue  # Skip example bundles — they are not schemas
        schema = _load_schema_file(path)
        if schema is None:
            continue
        if schema.name in result:
            logger.debug("Schema '%s' already registered (first-wins); skipping %s", schema.name, path)
        else:
            result[schema.name] = schema
            logger.debug("Registered schema '%s' from %s", schema.name, path)


@lru_cache(maxsize=1)
def discover_schemas(extra_dirs: tuple[str, ...] = ()) -> dict[str, ReportSchema]:
    """
    Scan all schema directories and return a name→ReportSchema mapping.

    Search order (first-wins on name collision):
      1. extra_dirs (callers / tests can inject custom paths)
      2. ./schemas/  (CWD-relative, useful during development)
      3. ~/.config/ncs_reporter/schemas/
      4. Built-in package schemas/
    """
    result: dict[str, ReportSchema] = {}

    for d in extra_dirs:
        _scan_dir(Path(d), result)

    _scan_dir(Path("schemas"), result)
    _scan_dir(_USER_SCHEMAS_DIR, result)
    _scan_dir(_BUILTIN_SCHEMAS_DIR, result)

    return result


def detect_schemas_for_bundle(bundle: dict[str, Any], extra_dirs: tuple[str, ...] = ()) -> list[ReportSchema]:
    """Return all known schemas whose detection rules match the given raw bundle."""
    schemas = discover_schemas(extra_dirs)
    matched: list[ReportSchema] = []
    for schema in schemas.values():
        det = schema.detection
        if det.keys_any and not any(k in bundle for k in det.keys_any):
            continue
        if det.keys_all and not all(k in bundle for k in det.keys_all):
            continue
        matched.append(schema)
    return matched


def resolve_template_path(schema: ReportSchema, template_name: str) -> Path | None:
    """
    Resolve a template path:
      1. If schema has template_override and _source_path, look relative to schema file.
      2. Otherwise return None (caller falls back to built-in templates).
    """
    if not schema.template_override:
        return None
    source = getattr(schema, "_source_path", None)
    if not source:
        return None
    candidate = Path(source).parent / schema.template_override
    return candidate if candidate.exists() else None


def format_schema_validation_error(path: Path, exc: pydantic.ValidationError) -> str:
    """Format a Pydantic validation error with schema file path and field-level context."""
    lines = [f"Invalid schema {path}:"]
    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        lines.append(f"  {loc}: {err['msg']}")
    return "\n".join(lines)


def load_schema_from_file(path: Path) -> ReportSchema:
    """Load and validate a schema file, raising ValueError on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Not a YAML mapping: {path}")

        data = _resolve_refs(data, path)
        data = _resolve_includes(data, path)

        schema = ReportSchema.model_validate(data)
        object.__setattr__(schema, "_source_path", str(path))
        _attach_broken_paths(schema)
        return schema
    except pydantic.ValidationError as exc:
        raise ValueError(format_schema_validation_error(path, exc)) from exc
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f"Invalid schema {path}: {exc}") from exc


def load_example_bundle(schema: ReportSchema) -> dict[str, Any] | None:
    """
    Look for a ``<schema_name>.example.yaml`` file next to the schema file and
    return its contents as a dict, or None if no example file exists.
    """
    source = getattr(schema, "_source_path", None)
    if not source:
        return None
    example_path = Path(source).parent / f"{schema.name}.example.yaml"
    if not example_path.exists():
        return None
    try:
        with open(example_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data if isinstance(data, dict) else None
    except Exception as exc:
        logger.warning("Failed to load example bundle %s: %s", example_path, exc)
        return None


def validate_schema_paths(schema: ReportSchema, example_bundle: dict[str, Any]) -> dict[str, str]:
    """
    Resolve every path-based field in *schema* against *example_bundle*.

    Returns a mapping of ``field_name → error_message`` for every field whose
    path resolves to None against the example data (i.e. the path is broken).
    Compute and script fields are skipped — they cannot be validated statically.
    """
    from ncs_reporter.normalization.schema_driven import resolve_field

    errors: dict[str, str] = {}
    for name, spec in schema.fields.items():
        if spec.path is None:
            continue
        value = resolve_field(spec.path, example_bundle)
        if value is None:
            errors[name] = f"field '{name}': path '{spec.path}' → None (check path segments against the example file)"
    return errors


def build_platform_entries_from_schemas(
    schemas: dict[str, ReportSchema],
) -> list[dict[str, Any]]:
    """Extract PlatformEntry dicts from schemas that have embedded platform metadata.

    Each schema with a ``platform_spec`` produces one primary entry and zero or more
    sub-entries (non-renderable, STIG-only entries like vcsa/esxi/vm under vmware).
    """
    entries: list[dict[str, Any]] = []
    seen_platforms: set[str] = set()

    for schema in schemas.values():
        spec: PlatformSpec | None = schema.platform_spec
        if spec is None:
            continue

        platform_name = spec.name or schema.platform or schema.name

        # Primary entry
        primary: dict[str, Any] = {
            "input_dir": spec.input_dir or schema.platform or schema.name,
            "report_dir": spec.report_dir or schema.platform or schema.name,
            "platform": platform_name,
            "state_file": spec.state_file,
            "render": spec.render,
            "schema_name": schema.name,
            "target_types": list(spec.target_types),
            "display_name": schema.display_name or spec.display_name,
            "asset_label": spec.asset_label,
            "inventory_groups": list(spec.inventory_groups),
            "schema_names": [schema.name],
            "stig_skeleton_map": dict(spec.stig_skeleton_map),
            "stig_rule_prefixes": dict(spec.stig_rule_prefixes),
            "site_category": spec.site_category,
        }
        entries.append(primary)
        seen_platforms.add(platform_name)

        # Sub-entries (non-renderable)
        for sub in spec.sub_entries:
            sub_entry: dict[str, Any] = {
                "input_dir": sub.input_dir,
                "report_dir": sub.report_dir,
                "platform": platform_name,
                "state_file": sub.state_file,
                "render": False,
                "target_types": list(sub.target_types),
                "stig_skeleton_map": dict(sub.stig_skeleton_map),
            }
            entries.append(sub_entry)

    return entries
