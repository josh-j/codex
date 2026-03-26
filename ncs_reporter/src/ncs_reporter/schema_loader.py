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

# Built-in configs directory (ships with the package)
_BUILTIN_CONFIGS_DIR = Path(__file__).parent / "configs"

# User-level config directories (prefer configs/, fall back to schemas/)
_USER_CONFIGS_DIR = Path.home() / ".config" / "ncs_reporter" / "configs"
_USER_SCHEMAS_DIR_LEGACY = Path.home() / ".config" / "ncs_reporter" / "schemas"


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
    """Resolve $include directives in fields, alerts, and widgets sections.

    For dict sections (fields): included keys go first, local keys override.
    For list sections (alerts, widgets): included items come first, then local
    items from ``$local`` are merged by ``id`` (replace) or appended (new id).

    Examples::

        fields:
          $include: "linux_base_fields.yaml"
          hostname:
            path: "different.path"

        alerts:
          $include: "linux_base_alerts.yaml"
          $local:
            - id: memory_critical      # replaces the included item with same id
              severity: CRITICAL
              condition: { op: gte, field: memory_used_pct, threshold: 95 }
              message: "Custom threshold"
            - id: platform_specific    # new id → appended
              ...
    """
    if not isinstance(data, dict):
        return data

    result = dict(data)

    # Dict sections (fields): merge by key, local overrides win
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
        merged = dict(included)
        merged.update(section)
        result[section_key] = merged

    # List sections (alerts, widgets): merge by id
    for section_key in ("alerts", "widgets"):
        section = result.get(section_key)
        if not isinstance(section, dict) or "$include" not in section:
            continue
        include_path = section["$include"]
        target_file = root_path.parent / include_path
        if not target_file.exists():
            raise ValueError(f"$include file not found: {target_file}")
        with open(target_file, encoding="utf-8") as f:
            included = yaml.safe_load(f)
        if not isinstance(included, list):
            raise ValueError(f"$include file for '{section_key}' must be a YAML list: {target_file}")

        local_items = section.get("$local", [])
        if not isinstance(local_items, list):
            local_items = []

        # Start with included list, then merge local items by id
        merged = list(included)
        for local_item in local_items:
            if not isinstance(local_item, dict) or "id" not in local_item:
                merged.append(local_item)
                continue
            # Find matching id in included items and replace
            replaced = False
            for i, inc_item in enumerate(merged):
                if isinstance(inc_item, dict) and inc_item.get("id") == local_item["id"]:
                    merged[i] = local_item
                    replaced = True
                    break
            if not replaced:
                merged.append(local_item)

        result[section_key] = merged

    return result


def _load_schema_file(path: Path) -> ReportSchema | None:
    """Load and validate a single schema YAML file. Returns None on error."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            logger.debug("Skipping %s: not a YAML mapping (likely a fragment)", path)
            return None

        # Skip fragment files (used via $include) — they lack required schema keys.
        if "name" not in data or "detection" not in data:
            logger.debug("Skipping %s: missing 'name'/'detection' (likely a fragment)", path)
            return None

        data = _resolve_refs(data, path)
        data = _resolve_includes(data, path)
        data = _expand_compact_syntax(data)

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
    Scan all config directories and return a name→ReportSchema mapping.

    Search order (first-wins on name collision):
      1. extra_dirs (callers / tests can inject custom paths)
      2. ./configs/  (CWD-relative, preferred)
      3. ./schemas/  (CWD-relative, deprecated fallback)
      4. ~/.config/ncs_reporter/configs/
      5. ~/.config/ncs_reporter/schemas/  (deprecated fallback)
      6. Built-in package configs/
    """
    result: dict[str, ReportSchema] = {}

    for d in extra_dirs:
        _scan_dir(Path(d), result)

    _scan_dir(Path("configs"), result)
    _scan_dir(Path("schemas"), result)
    _scan_dir(_USER_CONFIGS_DIR, result)
    _scan_dir(_USER_SCHEMAS_DIR_LEGACY, result)
    _scan_dir(_BUILTIN_CONFIGS_DIR, result)

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


def _build_yaml_line_map(path: Path) -> dict[str, int]:
    """Build a mapping from dot-paths to YAML line numbers."""
    try:
        with open(path, encoding="utf-8") as f:
            root = yaml.compose(f)
    except Exception:
        return {}

    line_map: dict[str, int] = {}

    def _walk(node: Any, prefix: str) -> None:
        if isinstance(node, yaml.MappingNode):
            for key_node, val_node in node.value:
                key = key_node.value if isinstance(key_node, yaml.ScalarNode) else str(key_node)
                dot_path = f"{prefix}.{key}" if prefix else key
                line_map[dot_path] = key_node.start_mark.line + 1
                _walk(val_node, dot_path)
        elif isinstance(node, yaml.SequenceNode):
            for i, item in enumerate(node.value):
                dot_path = f"{prefix}.{i}"
                line_map[dot_path] = item.start_mark.line + 1
                _walk(item, dot_path)

    if root:
        _walk(root, "")
    return line_map


def _did_you_mean(invalid: str, allowed: list[str]) -> str:
    """Suggest the closest match from allowed values."""
    import difflib
    matches = difflib.get_close_matches(invalid, allowed, n=1, cutoff=0.5)
    return f" (did you mean '{matches[0]}'?)" if matches else ""


# ---------------------------------------------------------------------------
# Compact syntax expansion
# ---------------------------------------------------------------------------

from ncs_reporter.normalization._fields import _TYPE_COERCERS

_KNOWN_FIELD_TYPES = frozenset({
    *_TYPE_COERCERS.keys(),
})

_WIDGET_TYPE_KEYS = frozenset({"alert_panel", "key_value", "table"})


def _expand_compact_field(value: str) -> dict[str, Any]:
    """Expand 'path | type = fallback' into a FieldSpec dict."""
    result: dict[str, Any] = {}

    # Split on ' = ' for fallback (rightmost)
    if " = " in value:
        before_eq, fallback_str = value.rsplit(" = ", 1)
        result["fallback"] = yaml.safe_load(fallback_str)
    else:
        before_eq = value

    # Split on ' | ' for type (rightmost, only if it's a known type)
    if " | " in before_eq:
        before_pipe, maybe_type = before_eq.rsplit(" | ", 1)
        if maybe_type.strip() in _KNOWN_FIELD_TYPES:
            result["type"] = maybe_type.strip()
            result["path"] = before_pipe.strip()
        else:
            result["path"] = before_eq.strip()
    else:
        result["path"] = before_eq.strip()

    return result




def _slugify(title: str) -> str:
    """Convert a title to a snake_case id."""
    import re as _re
    return _re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


def _expand_compact_column(value: str) -> dict[str, Any]:
    """Expand 'Label: field_name [badge]' into a column/field dict."""
    badge = False
    if value.endswith(" [badge]"):
        badge = True
        value = value[:-8]
    if ":" not in value:
        return {"label": value, "field": value}
    label, field = value.split(":", 1)
    result: dict[str, Any] = {"label": label.strip(), "field": field.strip()}
    if badge:
        result["badge"] = True
    return result


def _expand_compact_widget(item: dict[str, Any]) -> dict[str, Any]:
    """Expand compact widget dict (e.g., {table: "Title", rows: field, columns: [...]})."""
    for wtype in _WIDGET_TYPE_KEYS:
        if wtype not in item:
            continue
        title = item.pop(wtype)
        widget_id = item.pop("id", _slugify(title))
        result: dict[str, Any] = {"id": widget_id, "title": title, "type": wtype}

        if wtype == "table":
            result["rows_field"] = item.pop("rows", item.pop("rows_field", None))
            result["columns"] = _expand_column_list(item.pop("columns", []))
        elif wtype == "key_value":
            result["fields"] = _expand_column_list(item.pop("fields", []))

        # Pass through remaining keys (layout, visible_if, etc.)
        result.update(item)
        return result

    # Not a compact widget — but still expand compact column strings inside it
    return _expand_columns_in_widget(item)


def _expand_column_list(items: list[Any]) -> list[Any]:
    """Expand compact column/field strings in a list, leaving dicts unchanged."""
    return [_expand_compact_column(c) if isinstance(c, str) else c for c in items]


def _expand_columns_in_widget(item: dict[str, Any]) -> dict[str, Any]:
    """Expand compact column strings in a full-format widget dict."""
    for key in ("columns", "fields"):
        if key in item and isinstance(item[key], list):
            item[key] = _expand_column_list(item[key])
    return item


def _expand_compact_syntax(data: dict[str, Any]) -> dict[str, Any]:
    """Expand compact YAML shorthand into full Pydantic-compatible dicts.

    Runs after YAML parsing and $ref/$include resolution, before model validation.
    """
    # 1. Expand compact fields
    fields = data.get("fields")
    if isinstance(fields, dict):
        for key, val in list(fields.items()):
            if isinstance(val, str) and (" | " in val or " = " in val):
                fields[key] = _expand_compact_field(val)

    # 2. Alerts must be dicts with a 'when' key (compact string syntax removed)
    alerts = data.get("alerts")
    if isinstance(alerts, list):
        for item in alerts:
            if isinstance(item, str):
                raise ValueError(
                    f"Compact alert string syntax is no longer supported. "
                    f"Convert to dict with 'when' key: {item!r}"
                )

    # 3. Expand compact widgets
    widgets = data.get("widgets")
    if isinstance(widgets, list):
        data["widgets"] = [
            _expand_compact_widget(item) if isinstance(item, dict) else item
            for item in widgets
        ]

    # 4. Expand script_bundles into individual field entries
    bundles = data.pop("script_bundles", None)
    if isinstance(bundles, list):
        if fields is None:
            fields = {}
            data["fields"] = fields
        for bundle in bundles:
            if not isinstance(bundle, dict):
                continue
            script = bundle.get("script")
            base_args = dict(bundle.get("script_args", {}))
            timeout = bundle.get("script_timeout", 30)
            unpack = bundle.get("unpack", {})
            for field_name, spec in unpack.items():
                if isinstance(spec, dict):
                    key = spec.get("key", field_name)
                    field_type = spec.get("type", "str")
                else:
                    key = str(spec)
                    field_type = "str"
                entry: dict[str, Any] = {
                    "script": script,
                    "script_args": {**base_args, "metric": "_all", "_extract_key": key},
                    "type": field_type,
                    "script_timeout": timeout,
                }
                fields[field_name] = entry

    # 5. Expand compact fleet_columns
    fleet_columns = data.get("fleet_columns")
    if isinstance(fleet_columns, list):
        data["fleet_columns"] = _expand_column_list(fleet_columns)

    return data


def format_schema_validation_error(path: Path, exc: pydantic.ValidationError) -> str:
    """Format a Pydantic validation error with line numbers and suggestions."""
    line_map = _build_yaml_line_map(path)
    output = [f"Invalid config {path}:"]

    for err in exc.errors():
        loc = ".".join(str(part) for part in err["loc"])
        line = line_map.get(loc)
        prefix = f"  line {line}: " if line else "  "
        msg = err["msg"]

        # Add "did you mean?" for literal/enum errors
        hint = ""
        ctx = err.get("ctx", {})
        if err["type"] == "literal_error" and "expected" in ctx:
            invalid_val = err.get("input", "")
            if isinstance(invalid_val, str) and isinstance(ctx["expected"], str):
                # Parse allowed values from Pydantic's "expected 'a', 'b' or 'c'" format
                import re as _re
                allowed = _re.findall(r"'([^']+)'", ctx["expected"])
                hint = _did_you_mean(invalid_val, allowed)

        output.append(f"{prefix}{loc}: {msg}{hint}")

    return "\n".join(output)


def load_schema_from_file(path: Path) -> ReportSchema:
    """Load and validate a schema file, raising ValueError on failure."""
    try:
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        if not isinstance(data, dict):
            raise ValueError(f"Not a YAML mapping: {path}")

        data = _resolve_refs(data, path)
        data = _resolve_includes(data, path)
        data = _expand_compact_syntax(data)

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

    When multiple schemas share the same ``input_dir``, the first one encountered
    becomes the primary entry and subsequent schemas are merged into its
    ``schema_names`` list.  Schemas with ``sub_entries`` are processed first so
    they always serve as the primary.
    """
    entries: list[dict[str, Any]] = []
    seen_entries: dict[tuple[str, str], dict[str, Any]] = {}

    # Process schemas with sub_entries first so they become the primary entry
    # for their input_dir (they carry the richest metadata).
    platform_schemas = [s for s in schemas.values() if s.platform_spec is not None]
    platform_schemas.sort(key=lambda s: (not s.platform_spec.sub_entries,))

    for schema in platform_schemas:
        spec: PlatformSpec = schema.platform_spec  # type: ignore[assignment]

        platform_name = spec.name or schema.platform or schema.name
        input_dir = spec.input_dir or schema.platform or schema.name
        report_dir = spec.report_dir or schema.platform or schema.name

        # Merge schemas that share both input_dir AND report_dir.
        # Schemas with different report_dirs become independent entries.
        merge_key = (input_dir, report_dir)
        if merge_key in seen_entries:
            primary_entry = seen_entries[merge_key]
            primary_entry["schema_names"].append(schema.name)
            primary_entry["stig_checklist_map"].update(spec.stig_checklist_map)
            primary_entry["stig_rule_prefixes"].update(spec.stig_rule_prefixes)
            continue

        # Primary entry
        primary: dict[str, Any] = {
            "input_dir": input_dir,
            "report_dir": spec.report_dir or schema.platform or schema.name,
            "platform": platform_name,
            "render": spec.render,
            "schema_name": schema.name,
            "display_name": schema.display_name,
            "schema_names": [schema.name],
            "stig_checklist_map": dict(spec.stig_checklist_map),
            "stig_rule_prefixes": dict(spec.stig_rule_prefixes),
            "site_infra_fields": list(spec.site_infra_fields),
            "site_compute_node": spec.site_compute_node,
            "stig_playbook": spec.stig_playbook,
            "stig_target_var": spec.stig_target_var,
        }
        entries.append(primary)
        seen_entries[merge_key] = primary

        # Sub-entries (non-renderable)
        for sub in spec.sub_entries:
            sub_entry: dict[str, Any] = {
                "input_dir": sub.input_dir,
                "report_dir": sub.report_dir,
                "platform": platform_name,
                "render": False,
                "stig_checklist_map": dict(sub.stig_checklist_map),
                "stig_playbook": sub.stig_playbook or spec.stig_playbook,
                "stig_target_var": sub.stig_target_var or spec.stig_target_var,
            }
            entries.append(sub_entry)

    return entries
