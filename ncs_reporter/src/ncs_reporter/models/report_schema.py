"""Pydantic models for the YAML-driven report schema format."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, model_validator


# ---------------------------------------------------------------------------
# Field specification
# ---------------------------------------------------------------------------


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly one of path / compute / script must be set.
    # path    — dot-notation traversal with optional pipe transform
    # compute — arithmetic expression using {field_name} references
    # script  — path to an executable; receives JSON on stdin, returns JSON on stdout
    path: str | None = None
    compute: str | None = None
    script: str | None = None

    # Static key/value args passed to the script alongside extracted fields.
    script_args: dict[str, Any] = Field(default_factory=dict)
    # Seconds before a script invocation is killed and the fallback is used.
    script_timeout: int = 30

    type: Literal["str", "int", "float", "bool", "list", "dict"] = "str"
    fallback: Any = None
    # Value used instead of fallback when the path is *provably broken* (i.e. does
    # not resolve against the example bundle).  None means use a type-appropriate
    # default: "ERROR" for str, -1 for int/float.  Set explicitly to override.
    sentinel: Any = None

    @model_validator(mode="after")
    def _require_one_source(self) -> "FieldSpec":
        sources = sum(x is not None for x in [self.path, self.compute, self.script])
        if sources == 0:
            raise ValueError("FieldSpec requires one of: 'path', 'compute', or 'script'")
        if sources > 1:
            raise ValueError("FieldSpec: 'path', 'compute', and 'script' are mutually exclusive")
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


# ---------------------------------------------------------------------------
# Report widgets (discriminated union on `type`)
# ---------------------------------------------------------------------------


class KeyValueField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    field: str
    format: str | None = None


class KeyValueWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["key_value"]
    fields: list[KeyValueField]


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    label: str
    field: str
    badge: bool = False
    format: str | None = None
    link_field: str | None = None


class TableWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["table"]
    rows_field: str
    columns: list[TableColumn]


class AlertPanelWidget(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    title: str
    type: Literal["alert_panel"]


ReportWidget = Annotated[
    Union[KeyValueWidget, TableWidget, AlertPanelWidget],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------


class DetectionSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    keys_any: list[str] = Field(default_factory=list)
    keys_all: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level schema
# ---------------------------------------------------------------------------


class FleetColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    label: str
    field: str
    width: str | None = None


class ReportSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    platform: str
    display_name: str
    detection: DetectionSpec
    fields: dict[str, FieldSpec] = Field(default_factory=dict)
    alerts: list[AlertRule] = Field(default_factory=list)
    widgets: list[ReportWidget] = Field(default_factory=list)
    fleet_columns: list[FleetColumn] = Field(default_factory=list)
    template_override: str | None = None

    # Track where this schema was loaded from (set post-load, not from YAML)
    _source_path: str | None = None

    @model_validator(mode="after")
    def _cross_check_references(self) -> "ReportSchema":
        """Ensure all field references in alerts, widgets, and fleet columns exist in fields."""
        declared = set(self.fields.keys())
        errors: list[str] = []

        for rule in self.alerts:
            cond = rule.condition
            if hasattr(cond, "field") and not cond.field.startswith("_") and cond.field not in declared:
                errors.append(f"alert '{rule.id}': condition references undeclared field '{cond.field}'")
            for f in rule.detail_fields:
                if not f.startswith("_") and f not in declared:
                    errors.append(f"alert '{rule.id}': detail_fields references undeclared field '{f}'")
            if rule.affected_items_field and not rule.affected_items_field.startswith("_") and rule.affected_items_field not in declared:
                errors.append(f"alert '{rule.id}': affected_items_field references undeclared field '{rule.affected_items_field}'")

        for widget in self.widgets:
            if isinstance(widget, KeyValueWidget):
                for kv in widget.fields:
                    if not kv.field.startswith("_") and kv.field not in declared:
                        errors.append(f"widget '{widget.id}': key_value references undeclared field '{kv.field}'")
            elif isinstance(widget, TableWidget):
                if not widget.rows_field.startswith("_") and widget.rows_field not in declared:
                    errors.append(f"widget '{widget.id}': rows_field references undeclared field '{widget.rows_field}'")

        for col in self.fleet_columns:
            if not col.field.startswith("_") and col.field not in declared:
                errors.append(f"fleet_column: references undeclared field '{col.field}'")

        if errors:
            raise ValueError("Schema cross-reference errors:\n" + "\n".join(f"  - {e}" for e in errors))

        return self
