"""Pydantic models for the YAML-driven report schema format."""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import AfterValidator, AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["ActionSpec", "AlertRule", "FieldSpec", "ReportSchema", "ReportWidget", "ScriptSpec", "StyleRule"]


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


class ScriptSpec(BaseModel):
    """Nested script specification: path + optional args and timeout."""

    model_config = ConfigDict(extra="forbid")

    path: str = Field(validation_alias=AliasChoices("path", "run"))
    args: dict[str, Any] = Field(default_factory=dict, validation_alias=AliasChoices("args", "script_args"))
    timeout: int = Field(default=30, validation_alias=AliasChoices("timeout", "script_timeout"))


class ThresholdSpec(BaseModel):
    """Severity breakpoints for a numeric value.

    `warn_if_above: N` → yellow when the rendered value is ≥ N.
    `crit_if_above: N` → red when the rendered value is ≥ N.
    `crit_if_above` takes precedence when both match. Values below both
    thresholds render green (default/ok).
    """

    model_config = ConfigDict(extra="forbid")

    warn_if_above: float | None = None
    crit_if_above: float | None = None


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Exactly one of path / compute / normalize / template / script / const must be set.
    # path    — dot-notation traversal with optional pipe transform
    # compute — arithmetic expression using {field_name} references
    # normalize — declarative data shaping DSL for objects/lists/scalars
    # template — full Jinja template using current fields; preserves native values
    # script  — nested spec with path, args, timeout; receives JSON on stdin, returns JSON on stdout
    # const   — literal value (string, number, bool, list, dict) used as-is
    path: str | None = Field(
        default=None,
        validation_alias=AliasChoices("path", "from"),
        description="Dotted-path lookup into the raw bundle, with optional `| transform` pipeline. Alias: `from`. See `FIELDS.md` § path.",
    )
    compute: str | None = Field(
        default=None,
        validation_alias=AliasChoices("compute", "expr"),
        description="Jinja2 expression evaluated against other fields. Alias: `expr`. Use for one-line scalar derivations.",
    )
    normalize: dict[str, Any] | None = Field(
        default=None,
        description="Declarative DSL for shaping raw lists/dicts/scalars. Preferred over `compute` for multi-step or list-shaping logic. See `FIELDS.md` § normalize.",
    )
    template: str | None = Field(
        default=None,
        description="Multi-statement Jinja2 template. Lower-level fallback when `normalize:` cannot express the shape.",
    )
    const: Any = Field(
        default=_SENTINEL_UNSET,
        description="Hard-coded literal value (any type).",
    )

    @field_validator("compute", "template", mode="before")
    @classmethod
    def _coerce_expression(cls, v: Any) -> Any:
        return str(v) if v is not None and not isinstance(v, str) else v
    script: ScriptSpec | None = Field(
        default=None,
        description="Subprocess escape hatch — runs a Python helper from the collection's `ncs_configs/scripts/`. Avoid in new code; prefer `normalize:`.",
    )

    @model_validator(mode="before")
    @classmethod
    def _normalise_script(cls, values: Any) -> Any:
        """Accept both flat and nested script forms.

        Flat:
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
    ] = Field(
        default="str",
        description="Type coercion applied after the producer runs. Strict — failures fall through to `fallback:` or raise.",
    )
    fallback: Any = Field(
        default=_SENTINEL_UNSET,
        validation_alias=AliasChoices("fallback", "default"),
        description="Value used when the producer returns nothing or coercion fails.",
    )
    sentinel: Any = Field(
        default=None,
        description="Marks 'not applicable' (e.g. `'N/A'`) — renders as that literal and is excluded from threshold evaluation.",
    )
    format: str | None = Field(
        default=None,
        description="Python f-string-style format applied for display only (e.g. `{:.1f}%`). Does not affect alert evaluation.",
    )
    thresholds: ThresholdSpec | None = Field(
        default=None,
        description="Numeric breakpoints — produces boolean companions `<field>_exceeds_warn` / `<field>_exceeds_crit` referenceable from alerts and widgets.",
    )

    @model_validator(mode="after")
    def _require_one_source(self) -> "FieldSpec":
        has_const = self.const is not _SENTINEL_UNSET
        sources = sum(x is not None for x in [self.path, self.compute, self.normalize, self.template, self.script]) + int(has_const)
        # Allow metadata-only vars (e.g., just thresholds on auto-imported data)
        has_metadata = self.thresholds is not None
        if sources == 0 and not has_metadata:
            raise ValueError("FieldSpec requires one of: 'path', 'compute', 'normalize', 'template', 'script', 'const', or 'thresholds'")
        if sources > 1:
            raise ValueError("FieldSpec: 'path', 'compute', 'normalize', 'template', 'script', and 'const' are mutually exclusive")
        # Auto-derive fallback from type when not explicitly set
        if self.fallback is _SENTINEL_UNSET:
            self.fallback = _TYPE_DEFAULT_FALLBACKS.get(self.type)
        return self


# ---------------------------------------------------------------------------
# Alert action
# ---------------------------------------------------------------------------


class ActionSpec(BaseModel):
    """Structured alert action: ansible-playbook invocation or raw shell command."""

    model_config = ConfigDict(extra="forbid")

    playbook: str | None = None  # Path to ansible playbook (relative to --project-dir)
    extra_vars: dict[str, Any] = Field(default_factory=dict)
    timeout: int = 120  # Seconds — ansible-playbook can be slow
    command: str | None = None  # Raw shell command escape hatch

    @model_validator(mode="after")
    def _require_one(self) -> ActionSpec:
        if not self.playbook and not self.command:
            raise ValueError("ActionSpec requires 'playbook' or 'command'")
        if self.playbook and self.command:
            raise ValueError("'playbook' and 'command' are mutually exclusive")
        return self


# ---------------------------------------------------------------------------
# Alert rule
# ---------------------------------------------------------------------------


class AlertRule(BaseModel):
    """Alert rule — fires when `when:` is truthy. See `ALERTS.md`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Stable identifier for the alert. Used by `suppress_if:` and the alert rollup.")
    category: str = Field(description="Free-text category shown in the alert panel header (e.g. 'Patching', 'Health', 'Faults').")
    severity: Literal["CRITICAL", "WARNING", "INFO"] = Field(
        default="WARNING",
        description="CRITICAL / WARNING / INFO. Drives the report health rollup and color coding.",
    )
    when: str = Field(description="Jinja2 boolean expression — alert fires when truthy. Unquoted (Ansible convention).")
    action: ActionSpec | None = Field(
        default=None,
        description="Action to invoke when the alert fires (e.g. `playbook` or `command`). See `SCHEDULING_AND_ALERT_ACTIONS.md`.",
    )
    cooldown: str = Field(
        default="7d",
        description="Minimum interval between successive action invocations for the same alert id (e.g. `7d`, `24h`, `1h`).",
    )
    msg: str = Field(
        validation_alias=AliasChoices("msg", "message"),
        description="Alert message template. Alias: `message`. Rendered against the per-host context.",
    )
    items: str | None = Field(
        default=None,
        description="Optional Jinja2 expression returning the list of affected items. Defaults to the first list-typed field referenced in `when:`.",
    )
    suppress_if: str | list[str] | None = Field(
        default=None,
        description="Alert id (or list of ids) — when any listed alert fires, this one is suppressed.",
    )


# ---------------------------------------------------------------------------
# Report widgets (discriminated union on `type`)
# ---------------------------------------------------------------------------


class WidgetLayout(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: Literal["full", "half", "third", "quarter"] = Field(
        default="full",
        description="`full` / `half` / `third` / `quarter` — controls grid placement.",
    )
    row: int | None = Field(
        default=None,
        description="Row height hint for the widget.",
    )

    @model_validator(mode="before")
    @classmethod
    def _accept_string(cls, v: Any) -> Any:
        if isinstance(v, str):
            return {"width": v}
        return v


def _require_jinja_value(v: str) -> str:
    """Enforce that a value: reference is a Jinja2 expression ('{{ var }}')."""
    if "{{" not in v or "}}" not in v:
        raise ValueError(
            f"value: must be a Jinja2 expression like '{{{{ {v} }}}}', got {v!r}"
        )
    return v


JinjaValueRef = Annotated[str, AfterValidator(_require_jinja_value)]


class KeyValueField(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    value: JinjaValueRef
    format: str | None = None
    as_: Literal["status-badge", "severity-tally"] | None = Field(default=None, alias="as")


class _BaseWidget(BaseModel):
    """Common fields every widget shares — slug, name, layout, when.

    Each subclass narrows ``type`` with its own ``Literal[...]`` so the
    discriminator on ``ReportWidget`` still selects unambiguously."""
    model_config = ConfigDict(extra="forbid")

    slug: str = ""
    name: str
    layout: WidgetLayout = Field(default_factory=WidgetLayout)
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))


class KeyValueWidget(_BaseWidget):
    """Two-column label/value list. Use for host-identity blocks ('System Information', 'Memory & CPU')."""

    type: Literal["key_value"] = Field(description="Widget kind — must be `key-value`. Renders a label/value list.")
    fields: list[KeyValueField] = Field(description="List of `{name, value, ...}` entries — each is rendered as one label/value row.")


class StyleRule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    when: str  # Jinja2 expression evaluated per table row
    css_class: str


class TableColumn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Column header text.")
    value: JinjaValueRef = Field(description="Per-row Jinja2 expression resolving against each row dict (e.g. `\"{{ name }}\"`).")
    as_: Literal["status-badge", "severity-tally"] | None = Field(
        default=None,
        alias="as",
        description="Render hint: `status-badge` (color-coded chip), `severity-tally`.",
    )
    format: str | None = Field(default=None, description="Display format applied after `value:` resolves (e.g. `{:.1f}%`).")
    link_field: str | None = Field(default=None, description="Field name whose value is used as the link target for this cell.")
    style_rules: list[StyleRule] = Field(default_factory=list, description="Conditional CSS rules (e.g. apply `.sv-critical` when `value > 90`).")


class TableWidget(_BaseWidget):
    """Tabular widget — one row per item in `rows:`, one column per `columns[]` entry. See `WIDGETS.md` § table."""

    type: Literal["table"] = Field(description="Widget kind — must be `table`.")
    rows_field: str = Field(
        validation_alias=AliasChoices("rows_field", "rows"),
        description="Jinja2 expression returning the row list. Alias: `rows`.",
    )
    columns: list[TableColumn] = Field(description="Column definitions — each has `name`, `value`, optional `as`/`format`/`link_field`/`style_rules`.")


class AlertPanelWidget(_BaseWidget):
    """Lists fired alerts with severity badges. Auto-injected by the renderer; declare explicitly to control placement."""

    type: Literal["alert_panel"] = Field(description="Widget kind — must be `alert-panel`.")


class ProgressBarWidget(_BaseWidget):
    """Single horizontal bar with optional thresholds — useful for utilization metrics (CPU %, memory %, disk %)."""

    type: Literal["progress_bar"] = Field(description="Widget kind — must be `progress-bar`.")
    value: JinjaValueRef = Field(description="Jinja2 expression returning a numeric percentage 0–100.")
    value_label: str | None = Field(default=None, description="Optional override for the bar's text label (default: `value`).")
    color: Literal["auto", "green", "yellow", "red", "blue"] = Field(
        default="auto",
        description="Override the default green-bar color.",
    )
    thresholds: ThresholdSpec | None = Field(
        default=None,
        description="Numeric breakpoints (`warn_if_above`, `crit_if_above`) — colors the bar accordingly.",
    )


class MarkdownWidget(_BaseWidget):
    """Free-form Markdown content. `{{ … }}` Jinja expressions render against the per-host context."""

    type: Literal["markdown"] = Field(description="Widget kind — must be `markdown`.")
    content: str = Field(description="Markdown body. Jinja2 expressions inside `{{ ... }}` are rendered against the per-host context.")


class LogTailWidget(_BaseWidget):
    """Fixed-height scrollable log tail — typically wraps `auth_log_lines` or `recent_journal_events`."""

    type: Literal["log_tail"] = Field(description="Widget kind — must be `log-tail`. Renders a fixed-height scrollable log tail.")
    source: JinjaValueRef = Field(description="Jinja2 expression returning the list of log lines (e.g. `\"{{ auth_log_lines }}\"`).")
    max_height: str = Field(default="400px", description="Pixel height of the scroll viewport (default: 400px).")


class StatCardSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: JinjaValueRef
    name: str
    format: str | None = None
    color: Literal["auto", "green", "yellow", "red", "blue"] = "auto"
    thresholds: ThresholdSpec | None = None


class StatCardsWidget(_BaseWidget):
    """Row of headline stat cards rendered above other widgets. Each card shows a single label/value pair."""

    type: Literal["stat_cards"] = Field(description="Widget kind — must be `stat-cards`.")
    cards: list[StatCardSpec] = Field(description="Card definitions — each has `name`, `value`, optional `as`.")


class GroupedTableWidget(_BaseWidget):
    """Like `TableWidget` but rows are grouped under a sub-header derived from `group_by:`."""

    type: Literal["grouped_table"] = Field(description="Widget kind — must be `grouped-table`.")
    rows_field: str = Field(
        validation_alias=AliasChoices("rows_field", "rows"),
        description="Jinja2 expression returning the row list. Alias: `rows`.",
    )
    group_by: str = Field(description="Field on each row whose value forms the group header.")
    columns: list[TableColumn] = Field(description="Column definitions for the inner table.")


class InventorySection(BaseModel):
    """One section of an Inventory widget — a labelled table-of-rows.

    Each section is rendered as a collapsible sub-widget under the
    parent Inventory widget. The section title shows the row count
    so an operator can see ``vCenters (1) · Datacenters (1) · ESXi
    Hosts (2) · Virtual Machines (3)`` at a glance without
    expanding each one.
    """
    model_config = ConfigDict(extra="forbid")

    name: str
    when: str | None = Field(default=None, validation_alias=AliasChoices("when", "visible_if"))
    rows_field: str = Field(validation_alias=AliasChoices("rows_field", "rows"))
    columns: list[TableColumn]


class InventoryWidget(_BaseWidget):
    """Inventory landing-page widget — stat-card header + tree-walker children section + per-tier subtables."""

    type: Literal["inventory"] = Field(description="Widget kind — must be `inventory`. Renders a stat-card header plus a tree-walker-injected children section plus per-tier subtables.")
    stat_cards: list[StatCardSpec] = Field(
        default_factory=list,
        description="Optional headline stat cards rendered above the children section.",
    )
    sections: list[InventorySection] = Field(
        default_factory=list,
        description="Per-tier subtables — each has `name`, `rows`, `columns`, optional `when`.",
    )


ReportWidget = Annotated[
    Union[
        KeyValueWidget,
        TableWidget,
        AlertPanelWidget,
        ProgressBarWidget,
        MarkdownWidget,
        LogTailWidget,
        StatCardsWidget,
        GroupedTableWidget,
        InventoryWidget,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Detection rules
# ---------------------------------------------------------------------------


class DetectionSpec(BaseModel):
    """Rules that match a raw bundle to this schema."""

    model_config = ConfigDict(extra="forbid")

    keys_any: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("keys_any", "any"),
        description="Match if *any* listed bundle key is present (e.g. `[raw_apic]`, `[raw_vcsa]`). Alias: `any`.",
    )
    keys_all: list[str] = Field(
        default_factory=list,
        validation_alias=AliasChoices("keys_all", "all"),
        description="Match only if *all* listed bundle keys are present. Alias: `all`.",
    )


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
    name: str
    value: JinjaValueRef
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


class TreeLevel(BaseModel):
    """One tier in a hierarchical product tree.

    The reporter walks each level in declaration order: bundles whose
    on-disk path resolves to this level get instantiated as ``ReportNode``s
    with the named tier and schema. ``parent_tier`` says which previous
    level's nodes are this level's parents — when omitted the level
    attaches directly to the product root.
    """

    model_config = ConfigDict(extra="forbid")

    tier: str
    schema_name: str = Field(validation_alias=AliasChoices("schema_name", "schema"))
    bundle_key: str  # e.g. "raw_vcsa", "raw_esxi" — the dict key on the host bundle
    parent_tier: str | None = None
    children_label: str | None = None  # column label for "sub-count" on children widget


class TreeSpec(BaseModel):
    """Deprecated declarative tree shape for a product.

    Current inventory trees are inferred from collector-written folders.
    This model remains for backward compatibility with older configs and
    direct callers of ``build_tree_from_spec``.
    """

    model_config = ConfigDict(extra="forbid")

    root_slug: str
    root_title: str = ""
    # Schema name used to render the product root page. Defaults to
    # ``root_slug`` (e.g. vsphere → ``vsphere.yaml``). Flat products that
    # don't ship a dedicated root schema set this to ``inventory_root``.
    root_schema: str = ""
    levels: list[TreeLevel] = Field(default_factory=list)
    # Cross-tier list unions exposed on the root's data_source. For each
    # entry, the reporter walks the root's first-level children, resolves
    # the dotted path inside each child's bundle, and concatenates the
    # resulting lists. Lets a product surface aggregated tables (e.g.
    # vSphere "All ESXi Hosts" / "All VMs") on the root page without any
    # render-time Python.
    merge_from_children: list["MergeFromChildrenSpec"] = Field(default_factory=list)


class MergeFromChildrenSpec(BaseModel):
    """One union directive for ``TreeSpec.merge_from_children``."""

    model_config = ConfigDict(extra="forbid")

    field: str  # output key on root.data_source
    from_: str = Field(  # dotted path inside each child's bundle
        validation_alias=AliasChoices("from_", "from"),
        serialization_alias="from",
    )


class ReportSchema(BaseModel):
    """YAML-driven report schema for ncs_reporter (full report config)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(
        default="",
        description="Schema name (alphanumeric + underscore). Identifies the schema in logs and CLI flags.",
    )
    platform: str = Field(
        default="",
        description="Platform identifier — slash-separated for nested platforms (e.g. `vmware/vcsa`, `linux/ubuntu`, `aci/apic`). Becomes the join key between raw bundles, schemas, and the rendered report tree.",
    )
    platform_spec: PlatformSpec | None = Field(default=None, exclude=True)
    display_name: str = Field(
        default="",
        validation_alias=AliasChoices("display_name", "title"),
        description="Title shown in report headers and dashboards. Alias: `title`.",
    )
    path_prefix: str | None = Field(
        default=None,
        description="Override the default report-tree subdirectory. Most schemas leave this unset and inherit `<platform>/<hostname>/raw_*.yaml`.",
    )
    detection: DetectionSpec = Field(
        default_factory=DetectionSpec,
        description="Rules that match a raw bundle to this schema. See `docs/ncs-reporter-config/CONFIG_SCHEMA.md` § Detection.",
    )
    fields: dict[str, FieldSpec] = Field(
        default_factory=dict,
        validation_alias=AliasChoices("fields", "vars"),
        description="Field definitions — declared with `path`, `compute`, `normalize`, `template`, `script`, or `const`. Alias: `vars`. See `FIELDS.md`.",
    )
    alerts: list[AlertRule] = Field(
        default_factory=list,
        description="Alert rules — each with `id`, `severity`, `when`, `msg`. See `ALERTS.md`. Accepts `$include: <file>.yaml` to compose from a partial.",
    )
    widgets: list[ReportWidget] = Field(
        default_factory=list,
        description="Report-body widgets (stat-cards, key-value, table, grouped-table, alert-panel, progress-bar, markdown, log-tail, inventory). See `WIDGETS.md`. Accepts `$include`.",
    )
    fleet_columns: list[FleetColumn] = Field(
        default_factory=list,
        validation_alias=AliasChoices(
            "fleet_columns",
            "extra_inventory_widget_columns",
            "extra_product_widget_columns",
            "extra_fleet_widget_columns",
        ),
        description="Extra columns to inject into the fleet/inventory landing page beyond the platform's defaults.",
    )
    template_override: str | None = Field(
        default=None,
        description="Path to a Jinja2 template that replaces the default per-platform render template.",
    )
    split_field: str | None = Field(
        default=None,
        description="Bundle-key to split a multi-host raw payload by (used by per_host_split at emit time).",
    )
    split_name_key: str = Field(
        default="name",
        description="Inside each split shard, the key whose value names the resulting host file.",
    )
    stig: StigConfig = Field(
        default_factory=StigConfig,
        description="STIG-checklist wiring — only for platforms that ship a STIG remediation playbook.",
    )
    tree: TreeSpec | None = Field(
        default=None,
        description="Tree-rendering directives (legacy; most platforms inherit from `inventory_root.yaml`).",
    )

    # Post-load private state — populated outside the YAML by the
    # schema loader (`_source_path`, `_broken_paths`) and the
    # extractor (`_producer_order`).
    _source_path: str | None = None
    _broken_paths: frozenset[str] = frozenset()
    _producer_order: list[str] | None = None

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

        for key in ("extra_inventory_widget_columns", "extra_product_widget_columns", "extra_fleet_widget_columns", "fleet_columns"):
            fc = values.get(key)
            if isinstance(fc, dict):
                values[key] = [
                    {"name": label, "value": expr}
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
    def _derive_widget_slugs(self) -> "ReportSchema":
        """Auto-derive widget slugs from names when not set."""
        import re as _re
        for widget in self.widgets:
            if not widget.slug and hasattr(widget, "name"):
                widget.slug = _re.sub(r"[^a-z0-9]+", "_", widget.name.lower()).strip("_")
        return self

    @model_validator(mode="after")
    def _cross_check_references(self) -> "ReportSchema":
        """Ensure all field references in alerts, widgets, and fleet columns exist in fields."""
        import re as _re
        for widget in self.widgets:
            if not widget.slug and hasattr(widget, "name"):
                widget.slug = _re.sub(r"[^a-z0-9]+", "_", widget.name.lower()).strip("_")

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
            wctx = f"widget '{widget.slug}'"
            if isinstance(widget, KeyValueWidget):
                for kv in widget.fields:
                    _check(kv.value, f"{wctx}: key_value")
            elif isinstance(widget, TableWidget):
                _check(widget.rows_field, f"{wctx}: rows_field")
            elif isinstance(widget, ProgressBarWidget):
                _check(widget.value, f"{wctx}: progress_bar")
                _check(widget.value_label or "", f"{wctx}: progress_bar value_label")
            elif isinstance(widget, StatCardsWidget):
                for card in widget.cards:
                    _check(card.value, f"{wctx}: stat_cards")
            elif isinstance(widget, GroupedTableWidget):
                _check(widget.rows_field, f"{wctx}: grouped_table rows_field")

        for col in self.fleet_columns:
            _check(col.value, "fleet_column")

        if errors:
            raise ValueError("Schema cross-reference errors:\n" + "\n".join(f"  - {e}" for e in errors))

        return self
