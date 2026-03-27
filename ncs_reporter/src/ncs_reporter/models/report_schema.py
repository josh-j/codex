"""Pydantic models for the YAML-driven report schema format."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

# Re-export for backwards compatibility with tests that import from here
# (the actual evaluation now lives in normalization/_when.py)
__all__ = ["AlertRule", "FieldSpec", "ReportSchema", "ReportWidget", "ScriptSpec", "StyleRule"]


# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------


_TYPE_DEFAULT_FALLBACKS: dict[str, Any] = {
    "str": "",
    "int": 0,
    "float": 0.0,
    "bool": False,
    "list": [],
    "dict": {},
    "bytes": 0,
    "percentage": 0.0,
    "datetime": "",
    "duration_seconds": 0.0,
}

_SENTINEL_UNSET = object()


class ListFilterExclude(BaseModel):
    """Exclude list items where a field matches any of the given values or patterns."""

    model_config = ConfigDict(extra="allow")

    # Each key is a field name; value is a list of exact strings or regex patterns
    # (regex patterns start with ^). Items matching ANY exclude rule are removed.


class ListFilterSpec(BaseModel):
    """Declarative list filtering: exclude items by field value or pattern."""

    model_config = ConfigDict(extra="forbid")

    exclude: dict[str, list[str]] = Field(default_factory=dict)
    include: dict[str, list[str]] = Field(default_factory=dict)


class CountWhereSpec(BaseModel):
    """Count items in a list matching field=value filters (case-insensitive for strings)."""

    model_config = ConfigDict(extra="allow")

    # Each key is a field name, value is the required value.
    # All conditions must match (AND). Count of matching items is the result.


class ScriptSpec(BaseModel):
    """Nested script specification: path + optional args and timeout."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(validation_alias=AliasChoices("path", "run"))
    args: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("args", "script_args"))
    timeout: int = Field(default=30, validation_alias=AliasChoices("timeout", "script_timeout"))


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly one of path / compute / script must be set.
    # path    — dot-notation traversal with optional pipe transform
    # compute — arithmetic expression using {field_name} references
    # script  — nested spec with path, args, timeout; receives JSON on stdin, returns JSON on stdout
    path: str | None = Field(default=None, validation_alias=AliasChoices("path", "from"))
    compute: str | None = Field(default=None, validation_alias=AliasChoices("compute", "expr"))

    @field_validator("compute", mode="before")
    @classmethod
    def _coerce_compute(cls, v: Any) -> Any:
        return str(v) if v is not None and not isinstance(v, str) else v
    script: ScriptSpec | None = Field(default=None)

    @model_validator(mode="before")
    @classmethod
    def _normalise_script(cls, values: Any) -> Any:
        """Accept both flat and nested script forms.

        Flat (legacy):
            script: "foo.py"
            script_args: {k: v}
            script_timeout: 30

        Nested (preferred):
            script:
              path: "foo.py"
              args: {k: v}
              timeout: 30
        """
        if not isinstance(values, dict):
            return values
        raw = values.get("script") or values.get("run")
        if isinstance(raw, str):
            # Flat form — hoist into nested dict
            nested: dict[str, Any] = {"path": raw}
            for src in ("script_args", "args"):
                if src in values:
                    nested["args"] = values.pop(src)
                    break
            for src in ("script_timeout", "timeout"):
                if src in values:
                    nested["timeout"] = values.pop(src)
                    break
            values["script"] = nested
            values.pop("run", None)
        elif raw is None:
            # No script — still strip stale flat keys so extra="forbid" doesn't reject them
            for src in ("script_args", "args", "script_timeout", "timeout", "run"):
                values.pop(src, None)
        return values

    type: Literal[
        "str", "int", "float", "bool", "list", "dict", "bytes", "percentage", "datetime", "duration_seconds"
    ] = "str"
    fallback: Any = Field(default=_SENTINEL_UNSET, validation_alias=AliasChoices("fallback", "default"))
    # Value used instead of fallback when the path is *provably broken* (i.e. does
    # not resolve against the example bundle).  None means use a type-appropriate
    # default: "ERROR" for str, -1 for int/float.  Set explicitly to override.
    sentinel: Any = None

    # Optional default format string applied during view model rendering
    format: str | None = None

    # --- List processing (applied after path/compute/script resolution) ---
    # Filter list items by field values. Applied before list_map.
    list_filter: ListFilterSpec | None = None
    # Compute derived fields on each list item using arithmetic expressions.
    # Keys are new field names, values are expressions using {item_field} refs.
    list_map: dict[str, str] = Field(default_factory=dict)
    # Count list items matching field=value conditions. Overrides the resolved
    # value with the integer count. Useful for aggregation without scripts.
    count_where: dict[str, Any] | None = None
    # True if ANY list item matches all field=value conditions.
    any_where: dict[str, Any] | None = None
    # True if ALL list items match all field=value conditions.
    all_where: dict[str, Any] | None = None
    # Sum a numeric field across all list items (after list_filter if set).
    sum_field: str | None = None
    # Display thresholds: { value: color } for widgets that show this var.
    thresholds: dict[int, str] | None = None

    @model_validator(mode="after")
    def _require_one_source(self) -> "FieldSpec":
        sources = sum(x is not None for x in [self.path, self.compute, self.script])
        # Allow metadata-only vars (e.g., just thresholds on auto-imported data)
        has_metadata = self.thresholds is not None
        if sources == 0 and not has_metadata:
            raise ValueError("FieldSpec requires one of: 'path', 'compute', 'script', or 'thresholds'")
        if sources > 1:
            raise ValueError("FieldSpec: 'path', 'compute', and 'script' are mutually exclusive")
        # At most one aggregation mode
        agg_count = sum(x is not None for x in [self.count_where, self.any_where, self.all_where, self.sum_field])
        if agg_count > 1:
            raise ValueError("FieldSpec: 'count_where', 'any_where', 'all_where', and 'sum_field' are mutually exclusive")
        # Auto-derive fallback from type when not explicitly set
        if self.fallback is _SENTINEL_UNSET:
            self.fallback = _TYPE_DEFAULT_FALLBACKS.get(self.type)
        return self


# ---------------------------------------------------------------------------
# Alert rule
# ---------------------------------------------------------------------------


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    severity: Literal["CRITICAL", "WARNING", "INFO"] = "WARNING"
    when: str  # Jinja2 expression evaluated against extracted fields
    action: str | None = None  # Optional command to run when alert fires
    cooldown: str = "7d"  # Minimum time between re-firing (e.g., "7d", "24h", "1h")
    msg: str = Field(validation_alias=AliasChoices("msg", "message"))
    suppress_if: str | list[str] | None = None


# ---------------------------------------------------------------------------
# Report widgets (discriminated union on `type`)
# ---------------------------------------------------------------------------


class WidgetLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: Literal["full", "half", "third", "quarter"] = "full"
    row: int | None = None

    @model_validator(mode="before")
    @classmethod
    def _accept_string(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"width": v}
        return v


class KeyValueField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(validation_alias=AliasChoices("label", "title"))
    field: str
    format: str | None = None
    badge: bool = False


class KeyValueWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["key_value"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    fields: list[KeyValueField]


class StyleRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: str  # Jinja2 expression evaluated per table row
    css_class: str


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(validation_alias=AliasChoices("label", "title"))
    field: str
    badge: bool = False
    format: str | None = None
    link_field: str | None = None
    style_rules: list[StyleRule] = Field(default_factory=list)


class TableWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["table"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    columns: list[TableColumn]


class AlertPanelWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["alert_panel"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))


class ProgressBarWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["progress_bar"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    field: str  # Field containing a 0-100 percentage
    label: str | None = None  # Optional secondary field for text label
    color: Literal["auto", "green", "yellow", "red", "blue"] = "auto"
    thresholds: dict[int, str] | None = None  # e.g., { 75: "yellow", 90: "red" }


class MarkdownWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["markdown"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    content: str


class StatCardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field: str
    label: str
    format: str | None = None
    color: Literal["auto", "green", "yellow", "red", "blue"] = "auto"
    thresholds: dict[int, str] | None = None


class StatCardsWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["stat_cards"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    cards: list[StatCardSpec]


class BarChartWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["bar_chart"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    label_field: str
    value_field: str
    max: float = 100
    thresholds: dict[int, str] | None = None


class ListWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["list"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    items_field: str
    display_field: str | None = None
    style: Literal["bullet", "numbered", "comma"] = "bullet"
    empty_text: str = "None"


class GroupedTableWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = ""
    title: str
    type: Literal["grouped_table"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    group_by: str
    columns: list[TableColumn]


ReportWidget = Annotated[
    Union[
        KeyValueWidget,
        TableWidget,
        AlertPanelWidget,
        ProgressBarWidget,
        MarkdownWidget,
        StatCardsWidget,
        BarChartWidget,
        ListWidget,
        GroupedTableWidget,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------


class DetectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys_any: list[str] = Field(default_factory=list, validation_alias=AliasChoices("keys_any", "any"))
    keys_all: list[str] = Field(default_factory=list, validation_alias=AliasChoices("keys_all", "all"))


# ---------------------------------------------------------------------------
# Embedded platform metadata (replaces platforms_default.yaml)
# ---------------------------------------------------------------------------


class PlatformSpec(BaseModel):
    """Platform routing metadata embedded in a schema YAML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = ""  # platform group name (e.g. "linux", "vmware", "windows")
    input_dir: str = Field(default="", validation_alias=AliasChoices("input_dir", "path"))
    report_dir: str = ""  # defaults to input_dir if not set
    render: bool = True  # False = STIG/routing only, no fleet/site reports

    @model_validator(mode="before")
    @classmethod
    def _derive_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        # Normalize path → input_dir (path is shorthand when input_dir == report_dir)
        if "path" in values:
            if not values.get("input_dir"):
                values["input_dir"] = values["path"]
            if not values.get("report_dir"):
                values["report_dir"] = values["path"]
            del values["path"]
        input_dir = values.get("input_dir", "")
        if not values.get("report_dir"):
            values["report_dir"] = input_dir
        # Derive platform group name from report_dir (the schema identity path)
        report_dir = values.get("report_dir", "") or input_dir
        if not values.get("name") and report_dir:
            values["name"] = report_dir.split("/")[0]
        return values


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


class FleetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(validation_alias=AliasChoices("label", "title"))
    field: str
    width: str | None = None


class AnsiblePlaybookConfig(BaseModel):
    """ansible-playbook invocation config for STIG remediation."""

    model_config = ConfigDict(extra="forbid")

    path: str = ""
    target_var: str = ""


class StigConfig(BaseModel):
    """STIG compliance configuration nested under config.stig in YAML."""

    model_config = ConfigDict(extra="forbid")

    ansible_playbook: AnsiblePlaybookConfig = Field(default_factory=AnsiblePlaybookConfig)
    platform_to_checklist: dict[str, str] = Field(default_factory=dict)
    rule_prefix_to_platform: dict[str, str] = Field(default_factory=dict)


class ReportSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""  # derived from platform path if not set
    platform: str = ""
    platform_spec: PlatformSpec | None = Field(default=None, exclude=True)
    display_name: str = Field(default="", validation_alias=AliasChoices("display_name", "title"))
    path_prefix: str | None = None
    detection: DetectionSpec = Field(default_factory=DetectionSpec)  # auto-derived from name
    fields: dict[str, FieldSpec] = Field(default_factory=dict, validation_alias=AliasChoices("fields", "vars"))
    alerts: list[AlertRule] = Field(default_factory=list)
    widgets: list[ReportWidget] = Field(default_factory=list)
    fleet_columns: list[FleetColumn] = Field(
        default_factory=list,
        validation_alias=AliasChoices("fleet_columns", "extra_fleet_widget_columns"),
    )
    template_override: str | None = None
    split_field: str | None = None
    split_name_key: str = "name"
    stig: StigConfig = Field(default_factory=StigConfig)

    # Track where this schema was loaded from (set post-load, not from YAML)
    _source_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Hoist config: block fields to top level
        config = values.pop("config", None)
        if isinstance(config, dict):
            for key, val in config.items():
                if key not in values:
                    values[key] = val

        # Handle platform field: can be str path or dict (PlatformSpec)
        raw_platform = values.get("platform")
        if isinstance(raw_platform, str) and raw_platform:
            # String path form: "vmware/esxi" or "windows"
            platform_group = raw_platform.split("/")[0]
            schema_name = raw_platform.rsplit("/", 1)[-1]
            values["platform_spec"] = {"input_dir": raw_platform, "report_dir": raw_platform, "name": platform_group}
            values["platform"] = platform_group
            if not values.get("name"):
                values["name"] = schema_name
        elif isinstance(raw_platform, dict):
            values["platform_spec"] = raw_platform
            # report_dir is the schema identity path; path is shorthand for both dirs
            identity_dir = raw_platform.get("report_dir") or raw_platform.get("path") or raw_platform.get("input_dir") or ""
            values["platform"] = raw_platform.get("name") or identity_dir.split("/")[0] or values.get("name", "")
            if not values.get("name") and identity_dir:
                values["name"] = identity_dir.rsplit("/", 1)[-1]
        elif not raw_platform:
            values["platform"] = values.get("name", "")

        # Auto-derive detection from schema name (convention: raw_{name} key in bundle)
        name = values.get("name", "")
        if not values.get("detection") and name:
            values["detection"] = {"keys_any": [f"raw_{name}"]}

        # Auto-derive path_prefix from schema name
        if not values.get("path_prefix") and name:
            values["path_prefix"] = f"raw_{name}.data"

        # Auto-derive display_name from name
        if not values.get("display_name") and not values.get("title"):
            values["display_name"] = name.replace("_", " ").title() if name else ""

        # Normalize hyphenated widget types to underscored (key-value → key_value)
        widgets = values.get("widgets")
        if isinstance(widgets, list):
            for w in widgets:
                if isinstance(w, dict) and isinstance(w.get("type"), str):
                    w["type"] = w["type"].replace("-", "_")

        # Normalize extra_fleet_widget_columns dict form → list form
        import re as _re
        for key in ("extra_fleet_widget_columns", "fleet_columns"):
            fc = values.get(key)
            if isinstance(fc, dict):
                values[key] = [
                    {"label": label, "field": _re.sub(r"\{\{\s*(\w+)\s*\}\}", r"\1", expr).strip()}
                    for label, expr in fc.items()
                ]
                break

        # Normalize vars → fields (accept both keys)
        if "vars" in values and "fields" not in values:
            values["fields"] = values.pop("vars")
        # Expand short-form fields: bare string → path-only FieldSpec
        fields = values.get("fields")
        if isinstance(fields, dict):
            for key, val in fields.items():
                if isinstance(val, str):
                    fields[key] = {"path": val}
        # Expand path_prefix: prepend to all relative paths (starting with '.')
        prefix = values.get("path_prefix")
        if prefix and isinstance(fields, dict):
            for key, val in fields.items():
                if isinstance(val, dict) and isinstance(val.get("path"), str) and val["path"].startswith("."):
                    val["path"] = prefix + val["path"]  # ".foo" → "prefix.foo"
                elif isinstance(val, dict) and isinstance(val.get("from"), str) and val["from"].startswith("."):
                    val["from"] = prefix + val["from"]
        return values

    @model_validator(mode="after")
    def _derive_widget_ids(self) -> "ReportSchema":
        """Auto-derive widget IDs from titles when not set."""
        import re as _re
        for widget in self.widgets:
            if not widget.id and hasattr(widget, "title"):
                widget.id = _re.sub(r"[^a-z0-9]+", "_", widget.title.lower()).strip("_")
        return self

    @model_validator(mode="after")
    def _cross_check_references(self) -> "ReportSchema":
        """Ensure all field references in alerts, widgets, and fleet columns exist in fields."""
        self._derive_widget_ids()

        # Skip cross-reference check when path_prefix is set — vars are
        # auto-imported from the raw data at runtime, not all declared.
        if self.path_prefix:
            return self

        import difflib

        declared = set(self.fields.keys())

        def _hint(name: str) -> str:
            matches = difflib.get_close_matches(name, list(declared), n=1, cutoff=0.6)
            return f" (did you mean '{matches[0]}'?)" if matches else ""

        errors: list[str] = []

        def _check(field_name: str, context: str) -> None:
            if field_name and not field_name.startswith("_") and field_name not in declared:
                errors.append(f"{context} references undeclared field '{field_name}'{_hint(field_name)}")

        for rule in self.alerts:
            pass  # when expression field refs are validated at runtime

        for widget in self.widgets:
            wctx = f"widget '{widget.id}'"
            if isinstance(widget, KeyValueWidget):
                for kv in widget.fields:
                    _check(kv.field, f"{wctx}: key_value")
            elif isinstance(widget, TableWidget):
                _check(widget.rows_field, f"{wctx}: rows_field")
            elif isinstance(widget, ProgressBarWidget):
                _check(widget.field, f"{wctx}: progress_bar")
                _check(widget.label or "", f"{wctx}: progress_bar label")
            elif isinstance(widget, StatCardsWidget):
                for card in widget.cards:
                    _check(card.field, f"{wctx}: stat_cards")
            elif isinstance(widget, BarChartWidget):
                _check(widget.rows_field, f"{wctx}: bar_chart rows_field")
            elif isinstance(widget, ListWidget):
                _check(widget.items_field, f"{wctx}: list")
            elif isinstance(widget, GroupedTableWidget):
                _check(widget.rows_field, f"{wctx}: grouped_table rows_field")

        for col in self.fleet_columns:
            _check(col.field, "fleet_column")

        if errors:
            raise ValueError("Schema cross-reference errors:\n" + "\n".join(f"  - {e}" for e in errors))

        return self
