"""Pydantic models for the YAML-driven report schema format."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator


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
# Alert conditions (discriminated union on `op`)
# ---------------------------------------------------------------------------


class ThresholdCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["gt", "lt", "gte", "lte", "eq", "ne"]
    field: str
    threshold: float


class RangeCondition(BaseModel):
    """Fires when field is between min and max (min <= val < max)."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["range"]
    field: str
    min: float
    max: float


class ExistsCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["exists", "not_exists"]
    field: str


class FilterCountCondition(BaseModel):
    model_config = ConfigDict(extra="forbid")

    op: Literal["filter_count"]
    field: str
    filter_field: str
    filter_value: Any
    threshold: float = 0


class StringCondition(BaseModel):
    """String equality / inequality. Case-sensitive."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["eq_str", "ne_str"]
    field: str
    value: str


class StringInCondition(BaseModel):
    """Membership test against a list of string values."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["in_str", "not_in_str"]
    field: str
    values: list[str]


class FilterSpec(BaseModel):
    """Single equality filter used inside MultiFilterCondition."""

    model_config = ConfigDict(extra="forbid")

    filter_field: str
    filter_value: Any


class MultiFilterCondition(BaseModel):
    """Fires when the count of list items matching ALL filters exceeds threshold."""

    model_config = ConfigDict(extra="forbid")

    op: Literal["filter_multi"]
    field: str
    filters: list[FilterSpec]
    threshold: float = 0


class ComputedFilterCondition(BaseModel):
    """
    Fires when any item in a list satisfies an arithmetic expression threshold.

    expression uses {field_name} references into each list item, e.g.:
      "{freeSpace} / {capacity} * 100"
    Supported operators: +  -  *  /  (numeric literals and {refs} only).
    Division by zero yields 0.0.
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["computed_filter"]
    field: str
    expression: str
    cmp: Literal["gt", "lt", "gte", "lte", "eq", "ne", "range"]
    threshold: float | None = None
    min: float | None = None
    max: float | None = None


class DateThresholdCondition(BaseModel):
    """
    Fires when an ISO-8601 timestamp field is older/younger than a day threshold.

    op:
      age_gt  — field timestamp is MORE than `days` days old  (older than threshold)
      age_lt  — field timestamp is LESS than `days` days old  (younger than threshold)
      age_gte / age_lte — inclusive variants

    reference_field: optional field name containing the reference ISO timestamp.
      Defaults to datetime.now(UTC) when absent or unparseable.
    """

    model_config = ConfigDict(extra="forbid")

    op: Literal["age_gt", "age_lt", "age_gte", "age_lte"]
    field: str
    days: float
    reference_field: str | None = None


AlertCondition = Annotated[
    Union[
        ThresholdCondition,
        RangeCondition,
        ExistsCondition,
        FilterCountCondition,
        StringCondition,
        StringInCondition,
        MultiFilterCondition,
        ComputedFilterCondition,
        DateThresholdCondition,
    ],
    Field(discriminator="op"),
]


# ---------------------------------------------------------------------------
# Alert rule
# ---------------------------------------------------------------------------


class AlertRule(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    category: str
    severity: Literal["CRITICAL", "WARNING", "INFO"] = "WARNING"
    condition: AlertCondition
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
    visible_if: AlertCondition | None = None
    fields: list[KeyValueField]


class StyleRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    condition: AlertCondition
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
    visible_if: AlertCondition | None = None
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    columns: list[TableColumn]


class AlertPanelWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["alert_panel"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: AlertCondition | None = None


class ProgressBarWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["progress_bar"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: AlertCondition | None = None
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
    visible_if: AlertCondition | None = None
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
    visible_if: AlertCondition | None = None
    cards: list[StatCardSpec]


class BarChartWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["bar_chart"]
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    visible_if: AlertCondition | None = None
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
    visible_if: AlertCondition | None = None
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
    visible_if: AlertCondition | None = None
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
    state_file: str = ""
    target_types: list[str] = Field(default_factory=list)
    stig_skeleton_map: dict[str, str] = Field(default_factory=dict)
    stig_playbook: str = ""
    stig_target_var: str = ""


class PlatformSpec(BaseModel):
    """Platform routing metadata embedded in a schema YAML."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str = ""  # platform name (e.g. "linux", "vmware", "windows")
    input_dir: str = ""
    report_dir: str = ""
    target_types: list[str] = Field(default_factory=list)
    state_file: str = ""
    display_name: str | None = None
    asset_label: str = "Nodes"
    inventory_groups: list[str] = Field(default_factory=list)
    stig_skeleton_map: dict[str, str] = Field(default_factory=dict)
    stig_rule_prefixes: dict[str, str] = Field(default_factory=dict)
    render: bool = True  # False = STIG/routing only, no fleet/site reports
    site_category: str | None = None
    sub_entries: list[SubEntry] = Field(
        default_factory=list,
        validation_alias=AliasChoices("sub_entries", "children"),
    )
    # Registry-driven extensions (see PlatformEntry for docs)
    legacy_raw_keys: dict[str, str] = Field(default_factory=dict)
    legacy_audit_key: str | None = None
    site_infra_fields: list[str] = Field(default_factory=list)
    site_compute_node: bool = False
    stig_playbook: str = ""
    stig_target_var: str = ""

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

    name: str
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

    # Track where this schema was loaded from (set post-load, not from YAML)
    _source_path: str | None = None

    @model_validator(mode="before")
    @classmethod
    def _apply_defaults(cls, values: Any) -> Any:
        if not isinstance(values, dict):
            return values

        # Handle platform field: can be str or dict (PlatformSpec)
        raw_platform = values.get("platform")
        if isinstance(raw_platform, dict):
            # Dict form: extract platform name for the str field, store spec separately
            values["platform_spec"] = raw_platform
            values["platform"] = raw_platform.get("name", values.get("name", ""))
        elif not raw_platform:
            # Auto-derive platform from name when not explicitly set
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

        for rule in self.alerts:
            cond = rule.condition
            if hasattr(cond, "field") and not cond.field.startswith("_") and cond.field not in declared:
                errors.append(f"alert '{rule.id}': condition references undeclared field '{cond.field}'{_hint(cond.field)}")
            for f in rule.detail_fields:
                if not f.startswith("_") and f not in declared:
                    errors.append(f"alert '{rule.id}': detail_fields references undeclared field '{f}'{_hint(f)}")
            if (
                rule.affected_items_field
                and not rule.affected_items_field.startswith("_")
                and rule.affected_items_field not in declared
            ):
                errors.append(
                    f"alert '{rule.id}': affected_items_field references undeclared field "
                    f"'{rule.affected_items_field}'{_hint(rule.affected_items_field)}"
                )

        for widget in self.widgets:
            if isinstance(widget, KeyValueWidget):
                for kv in widget.fields:
                    if not kv.field.startswith("_") and kv.field not in declared:
                        errors.append(f"widget '{widget.id}': key_value references undeclared field '{kv.field}'{_hint(kv.field)}")
            elif isinstance(widget, TableWidget):
                if not widget.rows_field.startswith("_") and widget.rows_field not in declared:
                    errors.append(f"widget '{widget.id}': rows_field references undeclared field '{widget.rows_field}'{_hint(widget.rows_field)}")
            elif isinstance(widget, ProgressBarWidget):
                if not widget.field.startswith("_") and widget.field not in declared:
                    errors.append(f"widget '{widget.id}': progress_bar references undeclared field '{widget.field}'{_hint(widget.field)}")
                if widget.label and not widget.label.startswith("_") and widget.label not in declared:
                    errors.append(
                        f"widget '{widget.id}': progress_bar label references undeclared field '{widget.label}'{_hint(widget.label)}"
                    )
            elif isinstance(widget, StatCardsWidget):
                for card in widget.cards:
                    if not card.field.startswith("_") and card.field not in declared:
                        errors.append(
                            f"widget '{widget.id}': stat_cards references undeclared field '{card.field}'{_hint(card.field)}"
                        )
            elif isinstance(widget, BarChartWidget):
                if not widget.rows_field.startswith("_") and widget.rows_field not in declared:
                    errors.append(
                        f"widget '{widget.id}': bar_chart rows_field references undeclared field '{widget.rows_field}'{_hint(widget.rows_field)}"
                    )
            elif isinstance(widget, ListWidget):
                if not widget.items_field.startswith("_") and widget.items_field not in declared:
                    errors.append(
                        f"widget '{widget.id}': list references undeclared field '{widget.items_field}'{_hint(widget.items_field)}"
                    )
            elif isinstance(widget, GroupedTableWidget):
                if not widget.rows_field.startswith("_") and widget.rows_field not in declared:
                    errors.append(
                        f"widget '{widget.id}': grouped_table rows_field references undeclared field '{widget.rows_field}'{_hint(widget.rows_field)}"
                    )

        for col in self.fleet_columns:
            if not col.field.startswith("_") and col.field not in declared:
                errors.append(f"fleet_column: references undeclared field '{col.field}'{_hint(col.field)}")

        if errors:
            raise ValueError("Schema cross-reference errors:\n" + "\n".join(f"  - {e}" for e in errors))

        return self
