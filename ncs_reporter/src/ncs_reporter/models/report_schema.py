"""Pydantic models for the YAML-driven report schema format."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

# Re-export for backwards compatibility with tests that import from here
# (the actual evaluation now lives in normalization/_when.py)
__all__ = ["AlertRule", "FieldSpec", "ReportSchema", "ReportWidget", "StyleRule"]


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


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly one of path / compute / script must be set.
    # path    — dot-notation traversal with optional pipe transform
    # compute — arithmetic expression using {field_name} references
    # script  — path to an executable; receives JSON on stdin, returns JSON on stdout
    path: str | None = Field(default=None, validation_alias=AliasChoices("path", "from"))
    compute: str | None = Field(default=None, validation_alias=AliasChoices("compute", "expr"))
    script: str | None = Field(default=None, validation_alias=AliasChoices("script", "run"))

    # Static key/value args passed to the script alongside extracted fields.
    script_args: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("script_args", "args"))
    # Seconds before a script invocation is killed and the fallback is used.
    script_timeout: int = Field(default=30, validation_alias=AliasChoices("script_timeout", "timeout"))

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

    @model_validator(mode="after")
    def _require_one_source(self) -> "FieldSpec":
        sources = sum(x is not None for x in [self.path, self.compute, self.script])
        if sources == 0:
            raise ValueError("FieldSpec requires one of: 'path', 'compute', or 'script'")
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
    message: str
    detail_fields: list[str] = Field(default_factory=list)
    affected_items_field: str | None = None
    # Suppress this alert if another alert (by id) already fired.
    suppress_if: str | list[str] | None = None


# ---------------------------------------------------------------------------
# Report widgets (discriminated union on `type`)
# ---------------------------------------------------------------------------


class WidgetLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: Literal["full", "half", "third", "quarter"] = "full"
    row: int | None = None


class KeyValueField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str = Field(validation_alias=AliasChoices("label", "title"))
    field: str
    format: str | None = None
    badge: bool = False


class KeyValueWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["key_value"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
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

    id: str
    title: str
    type: Literal["table"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    columns: list[TableColumn]


class AlertPanelWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["alert_panel"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression


class ProgressBarWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["progress_bar"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
    field: str  # Field containing a 0-100 percentage
    label: str | None = None  # Optional secondary field for text label
    color: Literal["auto", "green", "yellow", "red", "blue"] = "auto"
    thresholds: dict[int, str] | None = None  # e.g., { 75: "yellow", 90: "red" }


class MarkdownWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["markdown"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
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

    id: str
    title: str
    type: Literal["stat_cards"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
    cards: list[StatCardSpec]


class BarChartWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["bar_chart"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    label_field: str
    value_field: str
    max: float = 100
    thresholds: dict[int, str] | None = None


class ListWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["list"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
    items_field: str
    display_field: str | None = None
    style: Literal["bullet", "numbered", "comma"] = "bullet"
    empty_text: str = "None"


class GroupedTableWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["grouped_table"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: str | None = None  # Jinja2 expression
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


class SubEntry(BaseModel):
    """A STIG-only sub-entry under a parent platform (e.g. vcsa, esxi, vm under vmware)."""

    model_config = ConfigDict(extra="forbid")

    input_dir: str
    report_dir: str
    stig_checklist_map: dict[str, str] = Field(default_factory=dict)
    stig_playbook: str = ""
    stig_target_var: str = ""


class PlatformSpec(BaseModel):
    """Platform routing metadata embedded in a schema YAML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = ""  # platform group name (e.g. "linux", "vmware", "windows")
    input_dir: str = Field(default="", validation_alias=AliasChoices("input_dir", "path"))
    report_dir: str = ""  # defaults to input_dir if not set
    render: bool = True  # False = STIG/routing only, no fleet/site reports
    sub_entries: list[SubEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("sub_entries", "children"),
    )
    site_infra_fields: list[str] = Field(default_factory=list)
    site_compute_node: bool = False

    @model_validator(mode="before")
    @classmethod
    def _derive_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values
        input_dir = values.get("input_dir") or values.get("path") or ""
        if not values.get("report_dir"):
            values["report_dir"] = input_dir
        if not values.get("name") and input_dir:
            values["name"] = input_dir.split("/")[0]
        return values

    @field_validator("sub_entries", mode="before")
    @classmethod
    def _coerce_sub_entries(cls, v: Any) -> Any:
        if v is None:
            return []
        return v


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


class FleetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str = Field(validation_alias=AliasChoices("label", "title"))
    field: str
    width: str | None = None


class ReportSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""  # derived from platform path if not set
    platform: str = ""
    platform_spec: PlatformSpec | None = Field(default=None, exclude=True)
    display_name: str = Field(default="", validation_alias=AliasChoices("display_name", "title"))
    path_prefix: str | None = None
    detection: DetectionSpec
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    alerts: list[AlertRule] = Field(default_factory=list)
    widgets: list[ReportWidget] = Field(default_factory=list)
    fleet_columns: list[FleetColumn] = Field(default_factory=list)
    template_override: str | None = None
    # When set, the raw bundle is split into multiple synthetic host entries
    # by iterating the list at this path. Each item becomes its own host
    # using the item's "name" field as the hostname.
    split_field: str | None = None
    split_name_key: str = "name"
    # STIG compliance fields
    stig_checklist_map: dict[str, str] = Field(default_factory=dict)
    stig_rule_prefixes: dict[str, str] = Field(default_factory=dict)
    stig_playbook: str = ""
    stig_target_var: str = ""

    # Track where this schema was loaded from (set post-load, not from YAML)
    _source_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

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
            input_dir = raw_platform.get("input_dir") or raw_platform.get("path") or ""
            values["platform"] = raw_platform.get("name") or input_dir.split("/")[0] or values.get("name", "")
            if not values.get("name") and input_dir:
                values["name"] = input_dir.rsplit("/", 1)[-1]
        elif not raw_platform:
            values["platform"] = values.get("name", "")

        # Auto-derive display_name from name
        if not values.get("display_name") and not values.get("title"):
            name = values.get("name", "")
            values["display_name"] = name.replace("_", " ").title() if name else ""
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
    def _cross_check_references(self) -> "ReportSchema":
        """Ensure all field references in alerts, widgets, and fleet columns exist in fields."""
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
            for f in rule.detail_fields:
                _check(f, f"alert '{rule.id}': detail_fields")
            _check(rule.affected_items_field or "", f"alert '{rule.id}': affected_items_field")

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
