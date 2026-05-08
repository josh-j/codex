"""Unit tests for the YAML-schema-driven reporting pipeline."""

from __future__ import annotations

from pathlib import Path
from conftest import CONFIGS_DIR

import pytest

from ncs_reporter.models.report_schema import (
    AlertRule,
    DetectionSpec,
    FieldSpec,
    ReportSchema,
)
from ncs_reporter.normalization._when import eval_expression, evaluate_when
from ncs_reporter.normalization.schema_driven import (
    build_schema_alerts,
    extract_fields,
    normalize_from_schema,
    resolve_field,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_schema(
    fields: dict[str, FieldSpec],
    *,
    name: str = "t",
    platform: str = "test",
    display_name: str | None = None,
    detection_keys: tuple[str, ...] = ("x",),
    alerts: list[AlertRule] | None = None,
) -> ReportSchema:
    """Compact builder for `ReportSchema(...)` test fixtures.

    Most tests in this module care only about the `fields=` payload;
    this helper hides the per-test name/platform/display_name/detection
    boilerplate.
    """
    return ReportSchema(
        name=name,
        platform=platform,
        display_name=display_name or name.replace("_", " ").title(),
        detection=DetectionSpec(keys_any=list(detection_keys)),
        fields=fields,
        alerts=alerts or [],
    )


def _simple_schema() -> ReportSchema:
    return ReportSchema(
        name="test_app",
        platform="test",
        display_name="Test App Report",
        detection=DetectionSpec(keys_any=["test_raw_discovery"]),
        fields={
            "hostname": FieldSpec(path="ansible_facts.hostname", type="str", fallback="unknown"),
            "error_rate_pct": FieldSpec(path="network_stats.error_rate", type="float", fallback=0.0),
            "interface_count": FieldSpec(path="interfaces | len_if_list", type="int", fallback=0),
            "interface_list": FieldSpec(path="interfaces", type="list", fallback=[]),
            "first_tag": FieldSpec(path="tags | first", type="str", fallback=None),
            "first_tag_length": FieldSpec(compute="first_tag | len_if_list", type="int", fallback=0),
        },
        alerts=[
            AlertRule(
                id="high_error_rate",
                category="Network Health",
                severity="WARNING",
                when="error_rate_pct > 5.0",
                msg="High error rate: {{ error_rate_pct }}%",
            ),
            AlertRule(
                id="interfaces_down",
                category="Connectivity",
                severity="CRITICAL",
                when="interface_list | selectattr('status', 'eq', 'down') | list | length > 0",
                msg="Interface(s) down detected",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# test_field_extraction
# ---------------------------------------------------------------------------


class TestFieldExtraction:
    def test_dot_path_resolution(self) -> None:
        raw = {"ansible_facts": {"hostname": "web-01"}}
        assert resolve_field("ansible_facts.hostname", raw) == "web-01"

    def test_missing_path_returns_none(self) -> None:
        raw: dict = {}
        assert resolve_field("missing.key", raw) is None

    def test_len_if_list_transform(self) -> None:
        raw = {"interfaces": [{"name": "eth0"}, {"name": "eth1"}]}
        assert resolve_field("interfaces | len_if_list", raw) == 2

    def test_len_if_list_non_list(self) -> None:
        raw = {"interfaces": "not-a-list"}
        assert resolve_field("interfaces | len_if_list", raw) == 0

    def test_first_transform(self) -> None:
        raw = {"tags": ["alpha", "beta"]}
        assert resolve_field("tags | first", raw) == "alpha"

    def test_first_empty_list(self) -> None:
        raw = {"tags": []}
        assert resolve_field("tags | first", raw) is None

    def test_extract_fields_with_schema(self) -> None:
        schema = _simple_schema()
        raw = {
            "ansible_facts": {"hostname": "server-01"},
            "network_stats": {"error_rate": 7.5},
            "interfaces": [{"name": "eth0", "status": "up"}],
            "tags": ["prod", "web"],
        }
        fields, coverage = extract_fields(schema, raw)
        assert fields["hostname"] == "server-01"
        assert fields["error_rate_pct"] == 7.5
        assert fields["interface_count"] == 1
        assert fields["interface_list"] == [{"name": "eth0", "status": "up"}]
        assert fields["first_tag"] == "prod"

    def test_extract_fields_fallback_on_missing(self) -> None:
        schema = _simple_schema()
        fields, coverage = extract_fields(schema, {})
        assert fields["hostname"] == "unknown"
        assert fields["error_rate_pct"] == 0.0
        assert fields["interface_count"] == 0
        assert fields["interface_list"] == []

    def test_type_coercion_str_to_int(self) -> None:
        schema = _make_schema(
            name="coerce_test",
            fields={"count": FieldSpec(path="count", type="int", fallback=0)},
        )
        fields, _ = extract_fields(schema, {"count": "42"})
        assert fields["count"] == 42


# ---------------------------------------------------------------------------
# test_condition_evaluation
# ---------------------------------------------------------------------------


class TestConditionEvaluation:
    def test_threshold_gt_fires(self) -> None:
        assert evaluate_when("cpu_pct > 90.0", {"cpu_pct": 95.0}) is True

    def test_threshold_gt_no_fire(self) -> None:
        assert evaluate_when("cpu_pct > 90.0", {"cpu_pct": 85.0}) is False

    def test_threshold_lte(self) -> None:
        assert evaluate_when("available_gb <= 5.0", {"available_gb": 3.0}) is True
        assert evaluate_when("available_gb <= 5.0", {"available_gb": 10.0}) is False

    def test_threshold_eq(self) -> None:
        assert evaluate_when("code == 0", {"code": 0}) is True
        assert evaluate_when("code == 0", {"code": 1}) is False

    def test_threshold_missing_field_no_fire(self) -> None:
        assert evaluate_when("missing > 0.0", {}) is False

    def test_exists_condition_true(self) -> None:
        assert evaluate_when("error_msg is defined and error_msg", {"error_msg": "oops"}) is True

    def test_exists_condition_false_on_none(self) -> None:
        assert evaluate_when("error_msg is defined and error_msg", {"error_msg": None}) is False

    def test_not_exists_condition(self) -> None:
        assert evaluate_when("error_msg is not defined", {}) is True
        assert evaluate_when("error_msg is not defined", {"error_msg": "present"}) is False

    def test_filter_count_fires(self) -> None:
        ifaces = [{"name": "eth0", "status": "down"}, {"name": "eth1", "status": "up"}]
        assert evaluate_when("ifaces | selectattr('status', 'eq', 'down') | list | length > 0", {"ifaces": ifaces}) is True

    def test_filter_count_no_fire(self) -> None:
        ifaces = [{"name": "eth0", "status": "up"}]
        assert evaluate_when("ifaces | selectattr('status', 'eq', 'down') | list | length > 0", {"ifaces": ifaces}) is False

    def test_filter_count_threshold_respected(self) -> None:
        ifaces = [
            {"name": "eth0", "status": "down"},
            {"name": "eth1", "status": "down"},
            {"name": "eth2", "status": "down"},
        ]
        assert evaluate_when("ifaces | selectattr('status', 'eq', 'down') | list | length > 2", {"ifaces": ifaces}) is True


# ---------------------------------------------------------------------------
# test_alert_generation
# ---------------------------------------------------------------------------


class TestAlertGeneration:
    def test_alert_fires_on_threshold(self) -> None:
        schema = _simple_schema()
        fields = {
            "hostname": "web-01",
            "error_rate_pct": 8.0,
            "interface_count": 1,
            "interface_list": [],
            "first_tag": None,
        }
        alerts = build_schema_alerts(schema, fields)
        ids = [a["id"] for a in alerts]
        assert "high_error_rate" in ids

    def test_alert_message_formatted(self) -> None:
        schema = _simple_schema()
        fields = {
            "hostname": "web-01",
            "error_rate_pct": 8.0,
            "interface_count": 0,
            "interface_list": [],
            "first_tag": None,
        }
        alerts = build_schema_alerts(schema, fields)
        rate_alert = next(a for a in alerts if a["id"] == "high_error_rate")
        assert "8.0" in rate_alert["message"]

    def test_no_alerts_when_conditions_clear(self) -> None:
        schema = _simple_schema()
        fields = {
            "hostname": "web-01",
            "error_rate_pct": 1.0,
            "interface_count": 2,
            "interface_list": [{"name": "eth0", "status": "up"}],
            "first_tag": None,
        }
        alerts = build_schema_alerts(schema, fields)
        assert alerts == []

    def test_alert_severity_canonical(self) -> None:
        schema = _simple_schema()
        fields = {
            "hostname": "web-01",
            "error_rate_pct": 0.0,
            "interface_count": 1,
            "interface_list": [{"name": "eth0", "status": "down"}],
            "first_tag": None,
        }
        alerts = build_schema_alerts(schema, fields)
        down_alert = next(a for a in alerts if a["id"] == "interfaces_down")
        assert down_alert["severity"] == "CRITICAL"

    def test_alert_dict_has_required_keys(self) -> None:
        schema = _simple_schema()
        fields = {
            "hostname": "web-01",
            "error_rate_pct": 9.0,
            "interface_count": 0,
            "interface_list": [],
            "first_tag": None,
        }
        alerts = build_schema_alerts(schema, fields)
        assert alerts
        for alert in alerts:
            assert "severity" in alert
            assert "category" in alert
            assert "message" in alert
            assert "affected_items" in alert


# ---------------------------------------------------------------------------
# test_normalize_from_schema
# ---------------------------------------------------------------------------


class TestNormalizeFromSchema:
    def test_returns_standard_keys(self) -> None:
        schema = _simple_schema()
        result = normalize_from_schema(schema, {})
        assert "metadata" in result
        assert "health" in result
        assert "summary" in result
        assert "alerts" in result
        assert "fields" in result
        assert "widgets_meta" in result

    def test_health_healthy_when_no_alerts(self) -> None:
        schema = _simple_schema()
        raw = {"ansible_facts": {"hostname": "ok-host"}, "network_stats": {"error_rate": 0.1}}
        result = normalize_from_schema(schema, raw)
        assert result["health"] == "HEALTHY"

    def test_health_warning_on_warning_alert(self) -> None:
        schema = _simple_schema()
        raw = {"network_stats": {"error_rate": 9.0}}
        result = normalize_from_schema(schema, raw)
        assert result["health"] == "WARNING"

    def test_health_critical_on_critical_alert(self) -> None:
        schema = _simple_schema()
        raw = {
            "network_stats": {"error_rate": 0.0},
            "interfaces": [{"name": "eth0", "status": "down"}],
        }
        result = normalize_from_schema(schema, raw)
        assert result["health"] == "CRITICAL"

    def test_metadata_contains_schema_name(self) -> None:
        schema = _simple_schema()
        result = normalize_from_schema(schema, {})
        assert result["metadata"]["schema_name"] == "test_app"

    def test_summary_counts_accurate(self) -> None:
        schema = _simple_schema()
        raw = {
            "network_stats": {"error_rate": 9.0},
            "interfaces": [{"name": "eth0", "status": "down"}],
        }
        result = normalize_from_schema(schema, raw)
        summary = result["summary"]
        assert summary["critical_count"] >= 1
        assert summary["warning_count"] >= 1
        assert summary["total"] >= 2


# ---------------------------------------------------------------------------
# Schema model validation
# ---------------------------------------------------------------------------


class TestSchemaModelValidation:
    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(Exception):
            FieldSpec(path="x", type="str", fallback=None, unknown_key="oops")  # type: ignore[call-arg]

    def test_valid_schema_parses_ok(self) -> None:
        schema = _simple_schema()
        assert schema.name == "test_app"
        assert len(schema.fields) == 6
        assert len(schema.alerts) == 2

    def test_fieldspec_requires_path_or_compute(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec(type="str", fallback=None)  # type: ignore[call-arg]

    def test_fieldspec_path_and_compute_mutually_exclusive(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec(path="a.b", compute="x + 1", type="float")

    def test_schema_alias_keys_parse(self) -> None:
        schema = ReportSchema.model_validate(
            {
                "name": "alias_test",
                "platform": "test",
                "display_name": "Alias Test",
                "detection": {"any": ["raw_test"]},
                "fields": {
                    "hostname": {"from": "raw_test.data.hostname", "default": "unknown"},
                    "uptime_days": {"expr": "uptime_seconds / 86400", "default": 0.0, "type": "float"},
                    "uptime_seconds": {"from": "raw_test.data.uptime", "type": "float", "default": 0.0},
                    "rows_data": {"from": "raw_test.data.rows", "type": "list", "default": []},
                },
                "widgets": [
                    {
                        "slug": "summary",
                        "name": "Summary",
                        "type": "key_value",
                        "fields": [{"name": "Host", "value": "{{ hostname }}"}],
                    },
                    {
                        "slug": "table1",
                        "name": "Rows",
                        "type": "table",
                        "rows": "rows_data",
                        "columns": [{"name": "Name", "value": "{{ name }}"}],
                    },
                ],
                "fleet_columns": [{"name": "Host", "value": "{{ hostname }}"}],
            }
        )

        assert schema.display_name == "Alias Test"
        assert schema.detection.keys_any == ["raw_test"]
        assert schema.fields["hostname"].path == "raw_test.data.hostname"
        assert schema.fields["hostname"].fallback == "unknown"
        assert schema.fields["uptime_days"].compute == "uptime_seconds / 86400"
        assert schema.widgets[1].rows_field == "rows_data"
        assert schema.fleet_columns[0].name == "Host"


# ---------------------------------------------------------------------------
# Expression evaluator (Jinja2-based)
# ---------------------------------------------------------------------------


class TestExpressionEvaluation:
    def test_simple_division(self) -> None:
        assert eval_expression("a / b", {"a": 100.0, "b": 4.0}) == 25.0

    def test_ratio_times_100(self) -> None:
        result = eval_expression("freeSpace / capacity * 100", {"freeSpace": 20.0, "capacity": 200.0})
        assert abs(result - 10.0) < 0.001

    def test_division_by_zero_returns_zero(self) -> None:
        assert eval_expression("a / b", {"a": 50.0, "b": 0.0}) == 0.0

    def test_missing_field_uses_zero(self) -> None:
        assert eval_expression("missing + 5", {}) == 5.0

    def test_addition(self) -> None:
        assert eval_expression("x + y", {"x": 3.0, "y": 4.0}) == 7.0

    def test_negation(self) -> None:
        assert eval_expression("-x", {"x": 5.0}) == -5.0

    def test_scalar_constant(self) -> None:
        assert eval_expression("86400", {}) == 86400.0

    def test_uptime_days_formula(self) -> None:
        result = eval_expression("appliance_uptime_seconds / 86400", {"appliance_uptime_seconds": 172800.0})
        assert result == 2.0

    def test_exponentiation(self) -> None:
        assert eval_expression("x ** 2", {"x": 3.0}) == 9.0

    def test_string_coerced_to_zero(self) -> None:
        assert eval_expression("'hello'", {}) == 0.0


# ---------------------------------------------------------------------------
# String conditions
# ---------------------------------------------------------------------------


class TestStringConditions:
    def test_eq_str_match(self) -> None:
        assert evaluate_when("status == 'red'", {"status": "red"}) is True

    def test_eq_str_no_match(self) -> None:
        assert evaluate_when("status == 'red'", {"status": "green"}) is False

    def test_eq_str_case_sensitive(self) -> None:
        assert evaluate_when("status == 'red'", {"status": "RED"}) is False

    def test_ne_str_match(self) -> None:
        assert evaluate_when("status != 'green'", {"status": "red"}) is True

    def test_ne_str_no_match(self) -> None:
        assert evaluate_when("status != 'green'", {"status": "green"}) is False

    def test_eq_str_missing_field(self) -> None:
        assert evaluate_when("status == 'red'", {}) is False

    def test_in_str_match(self) -> None:
        assert evaluate_when("health in ['red', 'yellow']", {"health": "yellow"}) is True

    def test_in_str_no_match(self) -> None:
        assert evaluate_when("health in ['red', 'yellow']", {"health": "green"}) is False

    def test_not_in_str(self) -> None:
        assert evaluate_when("health not in ['red', 'yellow']", {"health": "green"}) is True
        assert evaluate_when("health not in ['red', 'yellow']", {"health": "red"}) is False


# ---------------------------------------------------------------------------
# MultiFilterCondition
# ---------------------------------------------------------------------------


class TestMultiFilterCondition:
    def _make_vms(self) -> list[dict]:
        return [
            {"guest_name": "vm-a", "power_state": "poweredOn", "tools_status": "toolsNotRunning"},
            {"guest_name": "vm-b", "power_state": "poweredOn", "tools_status": "toolsOk"},
            {"guest_name": "vm-c", "power_state": "poweredOff", "tools_status": "toolsNotRunning"},
        ]

    def test_fires_when_all_filters_match(self) -> None:
        expr = "vms | selectattr('power_state', 'eq', 'poweredOn') | selectattr('tools_status', 'eq', 'toolsNotRunning') | list | length > 0"
        assert evaluate_when(expr, {"vms": self._make_vms()}) is True

    def test_no_fire_when_partial_match_only(self) -> None:
        expr = "vms | selectattr('power_state', 'eq', 'poweredOn') | selectattr('tools_status', 'eq', 'toolsNotInstalled') | list | length > 0"
        assert evaluate_when(expr, {"vms": self._make_vms()}) is False

    def test_threshold_respected(self) -> None:
        expr = "vms | selectattr('power_state', 'eq', 'poweredOn') | list | length > 1"
        assert evaluate_when(expr, {"vms": self._make_vms()}) is True

    def test_empty_list_no_fire(self) -> None:
        expr = "vms | selectattr('power_state', 'eq', 'poweredOn') | list | length > 0"
        assert evaluate_when(expr, {"vms": []}) is False


# ---------------------------------------------------------------------------
# ComputedFilterCondition
# ---------------------------------------------------------------------------


class TestComputedFilterCondition:
    """Tests for computed filter equivalents using selectattr with pre-computed fields.

    Note: The old computed_filter evaluated arithmetic expressions per list item.
    With Jinja2 `when` expressions, such filtering requires pre-computing the
    derived field via list_map in the schema's FieldSpec. These tests verify
    the selectattr approach on pre-computed values.
    """

    def _make_datastores(self) -> list[dict]:
        return [
            {"name": "ds1", "free_pct": 5.0},   # critical
            {"name": "ds2", "free_pct": 12.0},   # warning only
            {"name": "ds3", "free_pct": 50.0},   # ok
        ]

    def test_fires_when_any_item_crosses_threshold(self) -> None:
        expr = "datastores | selectattr('free_pct', 'le', 10.0) | list | length > 0"
        assert evaluate_when(expr, {"datastores": self._make_datastores()}) is True

    def test_no_fire_when_all_clear(self) -> None:
        expr = "datastores | selectattr('free_pct', 'le', 10.0) | list | length > 0"
        all_ok = [{"name": f"ds{i}", "free_pct": 50.0} for i in range(3)]
        assert evaluate_when(expr, {"datastores": all_ok}) is False

    def test_warning_threshold_fires_but_critical_does_not(self) -> None:
        crit_expr = "datastores | selectattr('free_pct', 'le', 10.0) | list | length > 0"
        warn_expr = "datastores | selectattr('free_pct', 'le', 15.0) | list | length > 0"
        only_warning = [{"name": "ds2", "free_pct": 12.0}]
        assert evaluate_when(crit_expr, {"datastores": only_warning}) is False
        assert evaluate_when(warn_expr, {"datastores": only_warning}) is True

    def test_empty_list_no_fire(self) -> None:
        expr = "datastores | selectattr('free_pct', 'le', 10.0) | list | length > 0"
        assert evaluate_when(expr, {"datastores": []}) is False


# ---------------------------------------------------------------------------
# Compute fields in FieldSpec
# ---------------------------------------------------------------------------


class TestComputeFields:
    def _make_schema_with_compute(self) -> ReportSchema:
        return ReportSchema(
            name="compute_test",
            platform="test",
            display_name="Compute Test",
            detection=DetectionSpec(keys_any=["x"]),
            fields={
                "cpu_used_mhz": FieldSpec(path="cpu.used", type="float", fallback=0.0),
                "cpu_total_mhz": FieldSpec(path="cpu.total", type="float", fallback=1.0),
                "cpu_pct": FieldSpec(compute="cpu_used_mhz / cpu_total_mhz * 100", type="float", fallback=0.0),
                "uptime_seconds": FieldSpec(path="uptime", type="float", fallback=0.0),
                "uptime_days": FieldSpec(compute="uptime_seconds / 86400", type="float", fallback=0.0),
            },
            alerts=[
                AlertRule(
                    id="high_cpu",
                    category="Compute",
                    severity="CRITICAL",
                    when="cpu_pct > 90.0",
                    msg="CPU usage is {cpu_pct:.1f}%",
                )
            ],
        )

    def test_compute_field_evaluated(self) -> None:
        schema = self._make_schema_with_compute()
        fields, _ = extract_fields(schema, {"cpu": {"used": 900.0, "total": 1000.0}, "uptime": 172800.0})
        assert abs(fields["cpu_pct"] - 90.0) < 0.001
        assert abs(fields["uptime_days"] - 2.0) < 0.001

    def test_compute_field_fallback_on_zero_denominator(self) -> None:
        schema = self._make_schema_with_compute()
        fields, _ = extract_fields(schema, {"cpu": {"used": 0.0, "total": 0.0}})
        # Division by zero yields 0.0, coerced to float
        assert fields["cpu_pct"] == 0.0

    def test_compute_alert_fires(self) -> None:
        schema = self._make_schema_with_compute()
        raw = {"cpu": {"used": 950.0, "total": 1000.0}, "uptime": 0.0}
        result = normalize_from_schema(schema, raw)
        assert result["health"] == "CRITICAL"
        assert any(a["id"] == "high_cpu" for a in result["alerts"])

    def test_compute_field_cannot_have_path_too(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec(path="a.b", compute="x * 2", type="float")


# ---------------------------------------------------------------------------
# Template fields
# ---------------------------------------------------------------------------


class TestTemplateFields:
    def test_template_field_returns_native_list_and_compute_can_reference_it(self) -> None:
        schema = _make_schema(
            name="template_test",
            fields={
                "items": FieldSpec(
                    template="{% set out = [] %}{% for i in raw_items %}{% set _ = out.append({'name': i.name, 'value': i.value}) %}{% endfor %}{{ out }}",
                    type="list",
                ),
                "item_count": FieldSpec(compute="{{ items | length }}", type="int"),
            },
        )

        fields, _ = extract_fields(
            schema,
            {"raw_template_test": {"data": {"raw_items": [{"name": "a", "value": 1}], "x": True}}},
        )

        assert fields["items"] == [{"name": "a", "value": 1}]
        assert fields["item_count"] == 1

    def test_template_field_helpers(self) -> None:
        schema = _make_schema(
            name="template_helpers_test",
            fields={
                "value": FieldSpec(
                    template="{{ {'picked': coalesce('', none, 'fallback'), 'truth': truthy('yes'), 'mapped': lookup('Weekly', {'Weekly': 7}, -1)} }}",
                    type="dict",
                )
            },
        )

        fields, _ = extract_fields(schema, {"x": True})

        assert fields["value"] == {"picked": "fallback", "truth": True, "mapped": 7}

    def test_template_field_cannot_have_path_too(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec(path="a.b", template="{{ a }}", type="str")


# ---------------------------------------------------------------------------
# Normalize DSL fields
# ---------------------------------------------------------------------------


class TestNormalizeFields:
    def test_normalize_field_shapes_lists_and_counts(self) -> None:
        schema = _make_schema(
            name="normalize_test",
            fields={
                "items": FieldSpec(
                    normalize={
                        "list": {
                            "source": {"flatten": "raw_groups[].items[]"},
                            "include_source": False,
                            "exclude_match_any": {"field": "name", "patterns": ["^infra-"]},
                            "map": {
                                "name": "name",
                                "owner": {
                                    "get": {
                                        "source": {"index": {"source": "owners", "key": "name", "value": "email"}},
                                        "key": "name",
                                        "default": "",
                                    }
                                },
                            },
                        }
                    },
                    type="list",
                ),
                "item_count": FieldSpec(normalize={"count": "items"}, type="int"),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_normalize_test": {
                    "data": {
                        "x": True,
                        "owners": [{"name": "app-1", "email": "owner@example.com"}],
                        "raw_groups": [{"items": [{"name": "app-1"}, {"name": "infra-vcenter"}]}],
                    }
                }
            },
        )

        assert fields["items"] == [{"name": "app-1", "owner": "owner@example.com"}]
        assert fields["item_count"] == 1

    def test_normalize_field_can_expand_parent_child_maps(self) -> None:
        schema = _make_schema(
            name="expand_test",
            fields={
                "hosts": FieldSpec(
                    normalize={
                        "list": {
                            "for_each": "cluster_results",
                            "expand": "clusters",
                            "include_source": False,
                            "map": {
                                "cluster": "item.key",
                                "datacenter": "parent.item",
                                "host_names": {"pluck": {"source": "item.value.hosts", "path": "name"}},
                            },
                        }
                    },
                    type="list",
                )
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_expand_test": {
                    "data": {
                        "x": True,
                        "cluster_results": [
                            {
                                "item": "DC1",
                                "clusters": {
                                    "ClusterA": {"hosts": [{"name": "esxi-01"}, {"name": "esxi-02"}]},
                                },
                            }
                        ],
                    }
                }
            },
        )

        assert fields["hosts"] == [{"cluster": "ClusterA", "datacenter": "DC1", "host_names": ["esxi-01", "esxi-02"]}]

    def test_normalize_list_supports_include_and_exclude_where(self) -> None:
        schema = _make_schema(
            name="where_test",
            fields={
                "powered_on": FieldSpec(
                    normalize={"list": {"source": "vms", "include_where": {"power_state": "on"}}},
                    type="list",
                ),
                "real_vms": FieldSpec(
                    normalize={
                        "list": {
                            "source": "vms",
                            "exclude_where": {"name": {"op": "matches", "value": "^infra-"}},
                        }
                    },
                    type="list",
                ),
                "big_vms": FieldSpec(
                    normalize={
                        "list": {
                            "source": "vms",
                            "include_where": [
                                {"power_state": "on"},
                                {"field": "memory_gb", "op": "gt", "value": 8},
                            ],
                        }
                    },
                    type="list",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_where_test": {
                    "data": {
                        "x": True,
                        "vms": [
                            {"name": "app-1", "power_state": "on", "memory_gb": 16},
                            {"name": "app-2", "power_state": "off", "memory_gb": 4},
                            {"name": "infra-vcenter", "power_state": "on", "memory_gb": 32},
                        ],
                    }
                }
            },
        )

        assert [v["name"] for v in fields["powered_on"]] == ["app-1", "infra-vcenter"]
        assert [v["name"] for v in fields["real_vms"]] == ["app-1", "app-2"]
        assert [v["name"] for v in fields["big_vms"]] == ["app-1", "infra-vcenter"]

    def test_normalize_for_each_accepts_dict_source(self) -> None:
        schema = _make_schema(
            name="dict_for_each",
            fields={
                "users": FieldSpec(
                    normalize={
                        "list": {
                            "for_each": "passwd",
                            "include_source": False,
                            "map": {
                                "name": "item.key",
                                "uid": "item.value.1",
                                "shell": "item.value.5",
                            },
                        }
                    },
                    type="list",
                )
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_dict_for_each": {
                    "data": {
                        "x": True,
                        "passwd": {
                            "alice": ["x", "1001", "1001", "Alice", "/home/alice", "/bin/bash"],
                            "bob": ["x", "1002", "1002", "Bob", "/home/bob", "/bin/zsh"],
                        },
                    }
                }
            },
        )

        names = sorted(u["name"] for u in fields["users"])
        assert names == ["alice", "bob"]
        alice = next(u for u in fields["users"] if u["name"] == "alice")
        assert alice["uid"] == "1001"
        assert alice["shell"] == "/bin/bash"

    def test_normalize_predicate_combinators(self) -> None:
        schema = _make_schema(
            name="combinator_test",
            fields={
                "kept_any": FieldSpec(
                    normalize={
                        "list": {
                            "source": "rows",
                            "exclude_where": {
                                "any": [
                                    {"role": "system"},
                                    {"field": "name", "op": "matches", "value": "^bot-"},
                                ]
                            },
                        }
                    },
                    type="list",
                ),
                "kept_not": FieldSpec(
                    normalize={
                        "list": {
                            "source": "rows",
                            "include_where": {"not": {"role": "system"}},
                        }
                    },
                    type="list",
                ),
                "kept_all": FieldSpec(
                    normalize={
                        "list": {
                            "source": "rows",
                            "include_where": {
                                "all": [
                                    {"role": "user"},
                                    {"field": "uid", "op": "gt", "value": 1000},
                                ]
                            },
                        }
                    },
                    type="list",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_combinator_test": {
                    "data": {
                        "x": True,
                        "rows": [
                            {"name": "alice", "role": "user", "uid": 1500},
                            {"name": "bob", "role": "user", "uid": 500},
                            {"name": "bot-cron", "role": "user", "uid": 2000},
                            {"name": "daemon", "role": "system", "uid": 1},
                        ],
                    }
                }
            },
        )

        assert {r["name"] for r in fields["kept_any"]} == {"alice", "bob"}
        assert {r["name"] for r in fields["kept_not"]} == {"alice", "bob", "bot-cron"}
        assert {r["name"] for r in fields["kept_all"]} == {"alice", "bot-cron"}

    def test_normalize_slice_op(self) -> None:
        schema = _make_schema(
            name="slice_test",
            fields={
                "first_three": FieldSpec(
                    normalize={"slice": {"source": "events", "stop": 3}},
                    type="list",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {"raw_slice_test": {"data": {"x": True, "events": [1, 2, 3, 4, 5]}}},
        )
        assert fields["first_three"] == [1, 2, 3]

    def test_normalize_sort_unique_merge_defined(self) -> None:
        schema = _make_schema(
            name="ops_test",
            fields={
                "sorted_desc": FieldSpec(
                    normalize={"sort": {"source": "rows", "by": "score", "reverse": True}},
                    type="list",
                ),
                "unique_by_label": FieldSpec(
                    normalize={"unique": {"source": "sorted_desc", "by": "label"}},
                    type="list",
                ),
                "merged": FieldSpec(
                    normalize={"merge": ["overrides", "defaults"]},
                    type="dict",
                ),
                "has_overrides": FieldSpec(
                    normalize={"defined": "overrides"},
                    type="bool",
                ),
                "missing": FieldSpec(
                    normalize={"defined": "not_present_anywhere"},
                    type="bool",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_ops_test": {
                    "data": {
                        "x": True,
                        "rows": [
                            {"label": "a", "score": 5},
                            {"label": "b", "score": 9},
                            {"label": "a", "score": 2},
                            {"label": "c", "score": 7},
                        ],
                        "defaults": {"timeout": 30, "retries": 3},
                        "overrides": {"timeout": 60},
                    }
                }
            },
        )

        # sort by score desc
        assert [r["score"] for r in fields["sorted_desc"]] == [9, 7, 5, 2]
        # unique by label, keeping first occurrence (which is the highest-score for that label)
        assert [r["label"] for r in fields["unique_by_label"]] == ["b", "c", "a"]
        # merge: overrides win over defaults
        assert fields["merged"] == {"timeout": 60, "retries": 3}
        assert fields["has_overrides"] is True
        assert fields["missing"] is False

    def test_normalize_defined_predicate_in_list(self) -> None:
        schema = _make_schema(
            name="defined_pred",
            fields={
                "with_owner": FieldSpec(
                    normalize={
                        "list": {
                            "source": "rows",
                            "include_where": {"defined": "owner_email"},
                        }
                    },
                    type="list",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_defined_pred": {
                    "data": {
                        "x": True,
                        "rows": [
                            {"name": "a", "owner_email": "a@x"},
                            {"name": "b"},
                            {"name": "c", "owner_email": None},
                        ],
                    }
                }
            },
        )
        assert {r["name"] for r in fields["with_owner"]} == {"a"}

    def test_normalize_if_op(self) -> None:
        schema = _make_schema(
            name="if_op_test",
            fields={
                "count_with_fallback": FieldSpec(
                    normalize={
                        "first_of": [
                            {"if": {"defined": "vcenters"}, "then": {"count": "vcenters"}},
                            {"const": 1},
                        ]
                    },
                    type="int",
                ),
            },
        )

        # Tree mode: vcenters present (even if empty list, 0 count is meaningful).
        fields_tree, _ = extract_fields(schema, {"raw_if_op_test": {"data": {"x": True, "vcenters": []}}})
        assert fields_tree["count_with_fallback"] == 0

        fields_tree2, _ = extract_fields(
            schema, {"raw_if_op_test": {"data": {"x": True, "vcenters": [{"a": 1}, {"b": 2}]}}}
        )
        assert fields_tree2["count_with_fallback"] == 2

        # Standalone: vcenters undefined → falls back to const 1.
        fields_solo, _ = extract_fields(schema, {"raw_if_op_test": {"data": {"x": True}}})
        assert fields_solo["count_with_fallback"] == 1

    def test_normalize_regex_replace_op(self) -> None:
        schema = _make_schema(
            name="regex_replace_test",
            fields={
                "interface_label": FieldSpec(
                    normalize={
                        "regex_replace": {
                            "value": "dn",
                            "pattern": r"^.*/(node-\d+)/.*?\[(.*?)\]/.*$",
                            "replacement": r"leaf \1 \2",
                        }
                    },
                    type="str",
                ),
                "scrubbed_count": FieldSpec(
                    normalize={
                        "regex_replace": {
                            "value": "log_line",
                            "pattern": r"\d+",
                            "replacement": "<n>",
                            "count": 1,
                        }
                    },
                    type="str",
                ),
                "case_insensitive_redact": FieldSpec(
                    normalize={
                        "regex_replace": {
                            "value": "msg",
                            "pattern": "ERROR",
                            "replacement": "[redacted]",
                            "ignorecase": True,
                        }
                    },
                    type="str",
                ),
            },
        )

        fields, _ = extract_fields(
            schema,
            {
                "raw_regex_replace_test": {
                    "data": {
                        "x": True,
                        "dn": "topology/pod-1/node-101/sys/phys-[eth1/1]/CDeqptIngrTotalHist15min",
                        "log_line": "saw 42 widgets and 7 gizmos",
                        "msg": "An error occurred and another Error too",
                    }
                }
            },
        )
        assert fields["interface_label"] == "leaf node-101 eth1/1"
        # count=1: only the first numeric group is replaced.
        assert fields["scrubbed_count"] == "saw <n> widgets and 7 gizmos"
        # Both "error" and "Error" replaced (case-insensitive).
        assert fields["case_insensitive_redact"] == "An [redacted] occurred and another [redacted] too"

    def test_topological_ordering_resolves_forward_references(self) -> None:
        """Compute → normalize → compute → template chain. Each producer
        runs exactly once because the topological pass orders by
        declared-field dependency, not declaration order."""
        from ncs_reporter.normalization.schema_driven import _producer_order

        schema = _make_schema(
            name="topo",
            fields={
                # Declared in reverse dependency order — the pass must
                # reorder to: rows → counts → total.
                "total": FieldSpec(compute="counts.total", type="int"),
                "counts": FieldSpec(
                    normalize={"object": {"total": {"count": "rows"}}},
                    type="dict",
                ),
                "rows": FieldSpec(template="{{ raw_rows }}", type="list"),
            },
        )
        order = _producer_order(schema)
        # `rows` must come before `counts`, which must come before `total`.
        assert order.index("rows") < order.index("counts") < order.index("total")

        fields, _ = extract_fields(
            schema,
            {"raw_topo": {"data": {"x": True, "raw_rows": [{"a": 1}, {"a": 2}, {"a": 3}]}}},
        )
        assert fields["rows"] == [{"a": 1}, {"a": 2}, {"a": 3}]
        assert fields["counts"] == {"total": 3}
        assert fields["total"] == 3

    def test_topological_ordering_tolerates_cycles(self) -> None:
        """Cyclic deps fall through to declaration-order evaluation; the
        legacy double-pass behaved similarly. Guarantee: no crash, both
        fields evaluate to a numeric value (Undefined → 0 via the
        NumericUndefined arithmetic env)."""
        from ncs_reporter.normalization.schema_driven import _producer_order

        schema = _make_schema(
            name="cyc",
            fields={
                "a": FieldSpec(compute="{{ b + 1 }}", type="int"),
                "b": FieldSpec(compute="{{ a + 1 }}", type="int"),
            },
        )
        assert set(_producer_order(schema)) == {"a", "b"}
        fields, _ = extract_fields(schema, {"raw_cyc": {"data": {"x": True}}})
        # Cyclic eval doesn't crash — both fields land at the
        # NumericUndefined-derived fallback (0 + 1 = 1).
        assert isinstance(fields["a"], int)
        assert isinstance(fields["b"], int)

    def test_normalize_field_cannot_have_path_too(self) -> None:
        with pytest.raises(ValueError):
            FieldSpec(path="a.b", normalize={"count": "items"}, type="int")


# ---------------------------------------------------------------------------
# aci.yaml schema round-trip validation
# ---------------------------------------------------------------------------


class TestAciSchema:
    def test_aci_schema_loads_and_validates(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "aci.yaml"
        s = load_schema_from_file(schema_path)
        assert s.platform == "aci"
        for name in ("active_faults", "ospf_down", "critical_fault_count", "active_fault_count"):
            spec = s.fields[name]
            assert spec.normalize is not None, f"{name} should be normalize-driven"
            assert spec.compute is None and spec.template is None

    def test_aci_schema_normalizes_raw_collector_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "aci.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_apic": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "apic_short": "tyfq-apic1",
                    "audit_failed": False,
                    "health_results": [
                        {"imdata": [{"fabricHealthTotal": {"attributes": {"cur": "92"}}}]},
                        {"imdata": [{"healthInst": {"attributes": {"cur": "88"}}}]},
                    ],
                    "faults": [
                        {"faultInst": {"attributes": {"severity": "critical", "descr": "link down", "dn": "topology/pod-1/node-101/fault-F1"}}},
                        {"faultInst": {"attributes": {"severity": "major", "descr": "memory pressure", "dn": "topology/pod-1/node-102/fault-F2"}}},
                        {"faultInst": {"attributes": {"severity": "warning", "descr": "noise", "dn": "topology/pod-1/node-103/fault-F3"}}},
                    ],
                    "cleared_faults": [
                        {"faultInst": {"attributes": {"severity": "warning", "descr": "TCA: ingress drop on eth1/1", "dn": "x"}}},
                        {"faultInst": {"attributes": {"severity": "warning", "descr": "policy applied", "dn": "y"}}},
                    ],
                    "ospf": [
                        {"ospfAdjEp": {"attributes": {"operSt": "full", "peerIp": "10.0.0.1", "dn": "a"}}},
                        {"ospfAdjEp": {"attributes": {"operSt": "exstart", "peerIp": "10.0.0.2", "dn": "b"}}},
                    ],
                    "ingress_high_util": [
                        {"interface_label": "eth1/1", "utilMax": 80, "utilAvg": 30},
                        {"interface_label": "eth1/2", "utilMax": 30, "utilAvg": 10},
                    ],
                    "egress_high_util": [],
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fields = result["fields"]

        assert fields["fabric_health_score"] == 92
        assert fields["tenant_health_score"] == 88
        assert len(fields["active_faults"]) == 3
        assert fields["active_fault_count"] == 3
        assert fields["critical_fault_count"] == 1
        assert fields["major_fault_count"] == 1
        assert fields["warning_fault_count"] == 1
        # The TCA ingress-drop entry is rejected; only the policy-applied entry remains.
        assert len(fields["recent_cleared_faults"]) == 1
        assert fields["recent_cleared_faults"][0]["descr"] == "policy applied"
        assert fields["ospf_down_count"] == 1
        assert fields["ospf_down"][0]["operSt"] == "exstart"
        assert fields["critical_ingress_util"] == 1
        assert fields["critical_egress_util"] == 0

        fired = {a["id"] for a in result["alerts"]}
        assert "active_critical_faults" in fired
        assert "active_major_faults" in fired
        assert "ospf_peers_down" in fired
        assert "link_utilization_critical_ingress" in fired

    def test_aci_schema_normalizes_raw_responses_bundle(self) -> None:
        """Verifies the schema can consume a *raw* `aci_responses_raw`
        bundle — i.e. the shape the playbook will produce once the
        `_aci_by_name`/`_aci_description_map` set_facts are stripped.
        """
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "aci.yaml"
        s = load_schema_from_file(schema_path)

        # Mirror what `_aci_responses.results` looks like: a list of
        # ansible-uri results, each with `item.name` and `json` payload.
        responses = [
            {"item": {"name": "fabric_health"}, "json": {"imdata": [{"fabricHealthTotal": {"attributes": {"cur": "92"}}}]}},
            {"item": {"name": "tenant_health"}, "json": {"imdata": [{"healthInst": {"attributes": {"cur": "88"}}}]}},
            {"item": {"name": "faults"}, "json": {"imdata": [
                {"faultInst": {"attributes": {"severity": "critical", "descr": "link down", "dn": "topology/pod-1/node-101/fault-F1"}}},
                {"faultInst": {"attributes": {"severity": "major", "descr": "memory pressure", "dn": "topology/pod-1/node-102/fault-F2"}}},
            ]}},
            {"item": {"name": "cleared_faults"}, "json": {"imdata": [
                {"faultInst": {"attributes": {"severity": "warning", "descr": "policy applied", "dn": "y"}}},
            ]}},
            {"item": {"name": "ospf"}, "json": {"imdata": [
                {"ospfAdjEp": {"attributes": {"operSt": "full", "peerIp": "10.0.0.1", "dn": "a"}}},
                {"ospfAdjEp": {"attributes": {"operSt": "exstart", "peerIp": "10.0.0.2", "dn": "b"}}},
            ]}},
        ]
        bundle = {
            "raw_apic": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "apic_short": "tyfq-apic1",
                    "audit_failed": False,
                    "aci_responses_raw": responses,
                    # Enrichment helper still pre-builds these:
                    "ingress_high_util": [],
                    "egress_high_util": [],
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fields = result["fields"]

        assert fields["fabric_health_score"] == 92
        assert fields["tenant_health_score"] == 88
        assert fields["active_fault_count"] == 2
        assert fields["critical_fault_count"] == 1
        assert fields["major_fault_count"] == 1
        assert fields["ospf_down_count"] == 1
        assert fields["recent_cleared_faults"][0]["descr"] == "policy applied"

    def test_aci_schema_derives_util_enrichment_from_raw_imdata(self) -> None:
        """Verifies that the schema reproduces what `_enrich_util.yaml`
        used to do (filter port-channel aggregates, threshold utilAvg,
        regex-decode interface_label, look up description, sort+unique+top-N).
        """
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "aci.yaml"
        s = load_schema_from_file(schema_path)

        # 4 ports: one port-channel (drop), one below threshold (drop),
        # two over threshold; one port appears twice with different utilMax
        # to test sort-then-unique keeps the higher.
        ingress = [
            {"eqptIngrTotalHist15min": {"attributes": {"dn": "topology/pod-1/node-101/sys/phys-[Po10]/CDeqptIngrTotalHist15min", "utilAvg": "60", "utilMax": "70"}}},
            {"eqptIngrTotalHist15min": {"attributes": {"dn": "topology/pod-1/node-101/sys/phys-[eth1/1]/CDeqptIngrTotalHist15min", "utilAvg": "50", "utilMax": "60"}}},
            {"eqptIngrTotalHist15min": {"attributes": {"dn": "topology/pod-1/node-101/sys/phys-[eth1/1]/CDeqptIngrTotalHist15min", "utilAvg": "40", "utilMax": "80"}}},
            {"eqptIngrTotalHist15min": {"attributes": {"dn": "topology/pod-1/node-101/sys/phys-[eth1/2]/CDeqptIngrTotalHist15min", "utilAvg": "10", "utilMax": "10"}}},
            {"eqptIngrTotalHist15min": {"attributes": {"dn": "topology/pod-1/node-102/sys/phys-[eth1/3]/CDeqptIngrTotalHist15min", "utilAvg": "30", "utilMax": "30"}}},
        ]
        interfaces = [
            {"l1PhysIf": {"attributes": {"dn": "topology/pod-1/node-101/sys/phys-[eth1/1]", "descr": "uplink to spine-1"}}},
            {"l1PhysIf": {"attributes": {"dn": "topology/pod-1/node-102/sys/phys-[eth1/3]", "descr": "uplink to spine-2"}}},
        ]
        responses = [
            {"item": {"name": "ingress"}, "json": {"imdata": ingress}},
            {"item": {"name": "egress"}, "json": {"imdata": []}},
            {"item": {"name": "interfaces"}, "json": {"imdata": interfaces}},
        ]
        bundle = {
            "raw_apic": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "apic_short": "tyfq-apic1",
                    "audit_failed": False,
                    "aci_responses_raw": responses,
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        rows = result["fields"]["ingress_high_util"]
        # Po10 dropped (port-channel), eth1/2 dropped (below threshold).
        assert {r["interface_label"] for r in rows} == {"leaf node-101 eth1/1", "leaf node-102 eth1/3"}
        # eth1/1 appears once after unique-by-interface; sort-by-utilMax desc kept the 80 entry.
        eth11 = next(r for r in rows if r["interface_label"] == "leaf node-101 eth1/1")
        assert eth11["utilMax"] == 80.0
        assert eth11["description"] == "uplink to spine-1"
        # Sort puts the higher utilMax first.
        assert rows[0]["utilMax"] >= rows[-1]["utilMax"]


# ---------------------------------------------------------------------------
# vcsa.yaml schema round-trip validation
# ---------------------------------------------------------------------------


class TestVcsaSchema:
    def test_vcsa_schema_loads_and_validates(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "vcsa.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "vcsa"
        assert s.platform == "vmware"
        # Verify when expressions are present
        when_exprs = {a.when for a in s.alerts}
        assert any("==" in w for w in when_exprs)  # string comparisons
        assert any("selectattr" in w for w in when_exprs)  # filter expressions
        # Verify compute field
        assert "appliance_uptime_days" in s.fields
        assert s.fields["appliance_uptime_days"].compute is not None

    def test_vcsa_schema_fires_on_synthetic_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "vcsa.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_vcsa": {
                "metadata": {"timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "appliance_version": "8.0.1",
                    "appliance_build": "12345",
                    "appliance_uptime_seconds": 172800,
                    "appliance_health_overall": "yellow",
                    "appliance_health_cpu": "green",
                    "appliance_health_memory": "green",
                    "appliance_health_database": "green",
                    "appliance_health_storage": "green",
                    "ssh_enabled": True,
                    "shell_enabled": False,
                    "ntp_mode": "NTP",
                    "backup_schedules": [],
                    "backup_schedule_count": 0,
                    "active_alarms": [],
                    "alarm_count": 0,
                    "vcenter_count": 1,
                    "datacenter_count": 0,
                    "cluster_count": 0,
                    "esxi_host_count": 0,
                    "datastore_count": 0,
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fired = {a["id"] for a in result["alerts"]}

        # appliance_health_yellow fires (eq_str on "yellow")
        assert "appliance_health_yellow" in fired
        # ssh_enabled fires (bool True == 1.0)
        assert "ssh_enabled" in fired
        # no_backup_schedule fires (count == 0)
        assert "no_backup_schedule" in fired
        # Overall health should be CRITICAL
        assert result["health"] == "CRITICAL"

    def test_vcsa_schema_normalizes_raw_collector_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "vcsa.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_vcsa": {
                "metadata": {"timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "appliance_about": {"about_info": {"version": "8.0.3", "build": "24022515"}},
                    "appliance_rest": {
                        "health/system": "yellow",
                        "health/load": "green",
                        "health/mem": "green",
                        "health/database-storage": "green",
                        "health/storage": "green",
                        "system/uptime": 172800,
                    },
                    "appliance_health": {
                        "appliance": {
                            "access": {"ssh": True, "shell": {"enabled": "False"}},
                            "time": {"time_sync": {"mode": "NTP", "servers": ["time.example"]}},
                        }
                    },
                    "appliance_backup": {"schedules": []},
                    "datacenters_raw": {"datacenter_info": [{"name": "DC1"}]},
                    "clusters_raw": {
                        "results": [
                            {
                                "item": "DC1",
                                "clusters": {
                                    "ClusterA": {
                                        "hosts": [{"name": "esxi-01"}, {"name": "esxi-02"}],
                                        "ha_enabled": True,
                                        "drs_enabled": False,
                                        "resource_summary": {
                                            "cpuCapacityMHz": 1000,
                                            "cpuUsedMHz": 250,
                                            "memCapacityMB": 2000,
                                            "memUsedMB": 500,
                                        },
                                    }
                                },
                            }
                        ]
                    },
                    "datastores_raw": {
                        "results": [
                            {
                                "datastores": [
                                    {
                                        "name": "ds1",
                                        "capacity": 1073741824,
                                        "freeSpace": 268435456,
                                        "type": "VMFS",
                                        "accessible": True,
                                    }
                                ]
                            }
                        ]
                    },
                    "vms_raw": [
                        {
                            "guest_name": "vm1",
                            "guest_fullname": "Ubuntu Linux",
                            "power_state": "poweredOn",
                            "ip_address": "10.0.0.10",
                            "esxi_hostname": "esxi-01",
                        }
                    ],
                    "snapshots_raw": {"results": [{"vmware_all_snapshots_info": [{"vm_name": "vm1"}]}]},
                    "alarms_raw": {"alarms": [{"severity": "warning"}]},
                    "infra_patterns": [],
                    "config": {},
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fields = result["fields"]

        assert fields["appliance_version"] == "8.0.3"
        assert fields["cluster_count"] == 1
        assert fields["esxi_host_count"] == 2
        assert fields["datastore_count"] == 1
        assert fields["datastores"][0]["used_pct"] == 75.0
        assert fields["vm_count"] == 1
        assert fields["snapshot_count"] == 1
        assert fields["alarm_count"] == 1
        fired = {a["id"] for a in result["alerts"]}
        assert "appliance_health_yellow" in fired
        assert "ssh_enabled" in fired
        assert "no_backup_schedule" in fired


class TestEsxiHealthSchema:
    def test_esxi_schema_loads_and_validates(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "esxi.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "esxi"
        assert s.platform == "vmware"
        when_exprs = {a.when for a in s.alerts}
        assert any("disconnected" in w for w in when_exprs)  # host_disconnected
        # connection_state and cpu_used_pct are auto-imported from raw data, not declared
        assert "uptime_days" in s.fields  # computed field IS declared

    def test_esxi_schema_fires_on_per_host_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "esxi.yaml"
        s = load_schema_from_file(schema_path)

        # Simulate a pre-assembled per-host bundle from the collector
        bundle = {
            "raw_esxi": {
                "metadata": {"host": "esxi-01", "timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "connection_state": "disconnected",
                    "overall_status": "red",
                    "cluster": "prod-cluster",
                    "datacenter": "dc01",
                    "cpu_used_pct": 42.0,
                    "mem_used_pct": 78.0,
                    "mem_mb_total": 131072,
                    "mem_mb_used": 102236,
                    "vm_count": 18,
                    "uptime_seconds": 4071600,
                    "ssh_enabled": True,
                    "shell_enabled": False,
                },
            },
        }

        result = normalize_from_schema(s, bundle)
        fired = {a["id"] for a in result["alerts"]}
        assert "host_disconnected" in fired
        assert "ssh_enabled" in fired


class TestVmHealthSchema:
    def test_vm_schema_loads_and_validates(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "vm.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "vm"
        assert s.platform == "vmware"
        assert "virtual_machines" in s.fields
        assert s.fields["virtual_machines"].normalize is not None
        assert "snapshot_count" in s.fields
        assert "powered_off_vms" in s.fields
        # All VM filter chains migrated to normalize:list+include_where.
        assert s.fields["powered_off_vms"].normalize is not None
        assert s.fields["powered_off_vms"].compute is None
        assert s.fields["aged_snapshots"].normalize is not None

    def test_vm_schema_fires_on_synthetic_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "vm.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_vm": {
                "metadata": {"timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "datacenters": [{"name": "DC1"}],
                    "vms_info_raw": {
                        "virtual_machines": [
                            {
                                "guest_name": "vm1",
                                "power_state": "poweredOn",
                                "tools_status": "toolsNotRunning",
                                "cluster": "cluster1",
                            },
                        ]
                    },
                    "virtual_machines": [
                        {
                            "guest_name": "vm1",
                            "power_state": "poweredOn",
                            "tools_status": "toolsNotRunning",
                            "cluster": "cluster1",
                        },
                    ],
                    "vm_count": 1,
                    "snapshots_raw": [],
                    "snapshot_count": 0,
                    "infra_patterns": [],
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fired = {a["id"] for a in result["alerts"]}
        # vm_tools_not_running fires (poweredOn + toolsNotRunning)
        assert "vm_tools_not_running" in fired


class TestWindowsSchema:
    def test_windows_schema_consumes_pre_shaped_bundle(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "windows.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_windows": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "ccm_service_state": "running",
                    "configmgr_apps": [],
                    "apps_to_update": [],
                    "installed_apps": [],
                    "update_results": [],
                    "health_hostname": "winsrv01",
                    "health_os_name": "Windows Server 2022",
                    "health_uptime_hours": 240.5,
                    "health_disk": [],
                    "health_memory_used_pct": 60,
                    "health_cpu_load_pct": 25,
                    "health_services": [],
                    "health_network": [],
                    "health_reboot_pending": False,
                    "health_reboot_reasons": [],
                    "health_event_count": 0,
                    "health_events": [],
                    "health_secure_channel": "OK",
                    "health_software_versions": [],
                    "vuln_total_findings": 0,
                    "vuln_remediated": 0,
                    "vuln_open": 0,
                    "vuln_findings": [],
                    "kb_detection": [],
                    "kb_install_results": [],
                    "audit_failed": False,
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        assert result["fields"]["health_uptime_hours"] == 240.5
        assert result["fields"]["ccm_service_state"] == "running"
        assert result["fields"]["health_reboot_pending"] is False

    def test_windows_schema_consumes_raw_register_subtrees(self) -> None:
        """Verifies the post-strip shape: the playbook emits raw
        `_health_os_info`/`_health_memory_cpu`/etc. subtrees and the
        schema's `first_of` chain extracts the typed fields.
        """
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = CONFIGS_DIR / "windows.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_windows": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "_ccm_service": {"state": "running"},
                    "_health_os_info": {"hostname": "winsrv02", "os_name": "Windows Server 2022", "uptime_hours": 100},
                    "_health_memory_cpu": {"memory_used_pct": 90, "cpu_load_pct": 40},
                    "_health_reboot_pending": {"reboot_pending": True, "reasons": ["Component-Based Servicing"]},
                    "_health_event_logs": {"event_count": 5, "events": [{"id": "1234"}]},
                    "_health_secure_channel": {"secure_channel": "FAILED"},
                    "_vuln_results": {"total_findings": 3, "remediated": 1, "open": 2, "findings": [{"id": "v1"}]},
                    "configmgr_apps": [],
                    "apps_to_update": [],
                    "installed_apps": [],
                    "update_results": [],
                    "health_disk": [{"DeviceID": "C:", "SizeGB": 100, "FreeGB": 10, "UsedPct": 90}],
                    "health_services": [],
                    "health_network": [],
                    "health_software_versions": [],
                    "kb_detection": [],
                    "kb_install_results": [],
                    "audit_failed": False,
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fields = result["fields"]
        assert fields["ccm_service_state"] == "running"
        assert fields["health_hostname"] == "winsrv02"
        assert fields["health_uptime_hours"] == 100.0
        assert fields["health_memory_used_pct"] == 90.0
        assert fields["health_reboot_pending"] is True
        assert fields["health_reboot_reasons"] == ["Component-Based Servicing"]
        assert fields["health_event_count"] == 5
        assert fields["health_secure_channel"] == "FAILED"
        assert fields["vuln_open"] == 2

        fired = {a["id"] for a in result["alerts"]}
        # Disk usage > 80% fires
        assert "disk_space_warning" in fired
        # Memory > 85% fires
        assert "memory_high" in fired
        # Reboot pending == 1 (True coerces to int 1)
        assert "reboot_pending" in fired
        # Secure channel == FAILED
        assert "secure_channel_failed" in fired
        # Critical events > 0
        assert "critical_events" in fired
        # vuln_open > 0
        assert "open_vulnerabilities" in fired


class TestUbuntuSchema:
    def test_ubuntu_schema_loads_and_users_field_is_normalize(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "ubuntu.yaml"
        s = load_schema_from_file(schema_path)
        # users was previously a `script:` field; must now be normalize-driven.
        users_spec = s.fields["users"]
        assert users_spec.script is None
        assert users_spec.normalize is not None
        # disks was previously list_filter/list_map; must now be normalize.
        disks_spec = s.fields["disks"]
        assert disks_spec.normalize is not None
        # non_standard_user_count must derive via normalize:count.
        ns_count_spec = s.fields["non_standard_user_count"]
        assert ns_count_spec.normalize is not None
        assert ns_count_spec.compute is None

    def test_ubuntu_schema_users_and_non_standard_users(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import extract_fields

        schema_path = CONFIGS_DIR / "ubuntu.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_ubuntu": {
                "metadata": {"timestamp": "2026-05-02T00:00:00Z"},
                "data": {
                    "ansible_facts": {
                        "hostname": "u-01",
                        "kernel": "5.15",
                        "distribution": "Ubuntu",
                        "distribution_version": "24.04",
                    },
                    "epoch_seconds": 86400 * 20000,
                    "getent_passwd": {
                        "root": ["x", "0", "0", "root", "/root", "/bin/bash"],
                        "daemon": ["x", "1", "1", "daemon", "/usr/sbin", "/usr/sbin/nologin"],
                        "alice": ["x", "1001", "1001", "Alice", "/home/alice", "/bin/bash"],
                        "bob": ["x", "12345", "12345", "Bob", "/home/bob", "/bin/zsh"],
                        "nobody": ["x", "65534", "65534", "nobody", "/nonexistent", "/usr/sbin/nologin"],
                    },
                    "shadow_raw": {
                        "stdout_lines": [
                            "alice:$6$abc:19500:0:99999:7:::",
                            "bob::19000:0:99999:7:::",
                            "# comment",
                            "",
                        ]
                    },
                    "getent_group": {
                        "root": ["x", "0", ""],
                        "users": ["x", "100", "alice,bob"],
                        "alice": ["x", "1001", ""],
                        "nobody": ["x", "65534", ""],
                    },
                    "mounts": [
                        {"mount": "/", "device": "/dev/sda1", "fstype": "ext4", "size_total": 10737418240, "size_available": 5368709120},
                        {"mount": "/run", "device": "tmpfs", "fstype": "tmpfs", "size_total": 1048576, "size_available": 1048576},
                        {"mount": "/snap/loop", "device": "/dev/loop0", "fstype": "squashfs", "size_total": 1024, "size_available": 0},
                    ],
                },
            }
        }

        fields, _ = extract_fields(s, bundle)

        users_by_name = {u["name"]: u for u in fields["users"]}
        assert {"root", "daemon", "alice", "bob", "nobody"} <= set(users_by_name)
        assert users_by_name["alice"]["uid"] == "1001"
        assert users_by_name["alice"]["shell"] == "/bin/bash"
        assert users_by_name["alice"]["password_age_days"] == 20000 - 19500
        # bob has no shadow hash but a last_change → still computes age.
        assert users_by_name["bob"]["password_age_days"] == 20000 - 19000
        # root has no shadow line at all.
        assert users_by_name["root"]["password_age_days"] == -1

        ns_users = {u["name"] for u in fields["non_standard_users"]}
        # alice (1001) and bob (12345) are operator-managed; root/daemon/nobody filtered out.
        assert ns_users == {"alice", "bob"}
        assert fields["non_standard_user_count"] == 2

        ns_groups = {g["name"] for g in fields["non_standard_groups"]}
        # alice (1001) only — root/users/nobody have system-account or 65534 GIDs.
        assert ns_groups == {"alice"}
        assert fields["non_standard_group_count"] == 1

        # disks: tmpfs + /dev/loop excluded, only ext4 root remains.
        assert len(fields["disks"]) == 1
        root_disk = fields["disks"][0]
        assert root_disk["fstype"] == "ext4"
        assert root_disk["used_pct"] == pytest.approx(50.0)


class TestPhotonSchema:
    def test_photon_schema_loads_and_detects_bundle(self) -> None:
        from ncs_reporter.schema_loader import detect_schemas_for_bundle, discover_schemas, load_schema_from_file

        schema_path = CONFIGS_DIR / "photon.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "photon"
        assert s.platform == "linux"

        discover_schemas.cache_clear()
        bundle = {
            "raw_photon": {
                "metadata": {"timestamp": "2026-03-02T00:00:00Z"},
                "data": {"ansible_facts": {"hostname": "photon-01"}},
            }
        }
        detected = detect_schemas_for_bundle(bundle, extra_dirs=(str(CONFIGS_DIR),))
        detected_names = {d.name for d in detected}
        assert "photon" in detected_names


# ---------------------------------------------------------------------------
# Script field execution
# ---------------------------------------------------------------------------


class TestScriptFields:
    """Tests for the script field escape hatch (subprocess JSON stdin/stdout)."""

    def _schema_with_script(self, script: str, script_args: dict | None = None) -> ReportSchema:
        return ReportSchema(
            name="script_test",
            platform="test",
            display_name="Script Test",
            detection=DetectionSpec(keys_any=["x"]),
            fields={
                "snapshots": FieldSpec(path="snapshots", type="list", fallback=[]),
                "collected_at": FieldSpec(path="collected_at", type="str", fallback=""),
                "aged_count": FieldSpec(
                    script=script,
                    script_args=script_args or {},
                    type="int",
                    fallback=0,
                ),
            },
            alerts=[
                AlertRule(
                    id="aged",
                    category="Snapshots",
                    severity="WARNING",
                    when="aged_count > 0",
                    msg="{{ aged_count }} aged snapshot(s)",
                )
            ],
        )

    def test_count_aged_snapshots_none_old(self) -> None:
        schema = self._schema_with_script(str(Path(__file__).parent / "fixtures" / "scripts" / "normalize_snapshots.py"), {"age_days": 7, "mode": "count"})
        raw = {
            "snapshots": [{"creation_time": "2026-02-27T00:00:00Z"}],
            "collected_at": "2026-02-27T06:00:00Z",
        }
        fields, _ = extract_fields(schema, raw)
        assert fields["aged_count"] == 0

    def test_count_aged_snapshots_one_old(self) -> None:
        schema = self._schema_with_script(str(Path(__file__).parent / "fixtures" / "scripts" / "normalize_snapshots.py"), {"age_days": 7, "mode": "count"})
        raw = {
            # snapshot created 10 days before collection
            "snapshots": [{"creation_time": "2026-02-17T00:00:00Z"}],
            "collected_at": "2026-02-27T00:00:00Z",
        }
        fields, _ = extract_fields(schema, raw)
        assert fields["aged_count"] == 1

    def test_count_aged_snapshots_mixed(self) -> None:
        schema = self._schema_with_script(str(Path(__file__).parent / "fixtures" / "scripts" / "normalize_snapshots.py"), {"age_days": 7, "mode": "count"})
        raw = {
            "snapshots": [
                {"creation_time": "2026-02-26T00:00:00Z"},  # 1 day — NOT old
                {"creation_time": "2026-02-10T00:00:00Z"},  # 17 days — old
                {"creation_time": "2026-02-05T00:00:00Z"},  # 22 days — old
            ],
            "collected_at": "2026-02-27T00:00:00Z",
        }
        fields, _ = extract_fields(schema, raw)
        assert fields["aged_count"] == 2

    def test_aged_snapshot_alert_fires(self) -> None:
        schema = self._schema_with_script(str(Path(__file__).parent / "fixtures" / "scripts" / "normalize_snapshots.py"), {"age_days": 7, "mode": "count"})
        raw = {
            "snapshots": [{"creation_time": "2026-01-01T00:00:00Z"}],
            "collected_at": "2026-02-27T00:00:00Z",
        }
        result = normalize_from_schema(schema, raw)
        assert any(a["id"] == "aged" for a in result["alerts"])

    def test_script_extract_key_does_not_change_cache_key(self, tmp_path: Path) -> None:
        script = tmp_path / "bundle.py"
        counter = tmp_path / "count.txt"
        script.write_text(
            "\n".join(
                [
                    "import json",
                    "import pathlib",
                    "import sys",
                    f"counter = pathlib.Path({str(counter)!r})",
                    "counter.write_text(str(int(counter.read_text() or '0') + 1) if counter.exists() else '1')",
                    "print(json.dumps({'alpha': 1, 'beta': 2}))",
                ]
            ),
            encoding="utf-8",
        )
        schema = _make_schema(
            name="script_cache_test",
            fields={
                "alpha": FieldSpec(script=str(script), script_args={"_extract_key": "alpha"}, type="int"),
                "beta": FieldSpec(script=str(script), script_args={"_extract_key": "beta"}, type="int"),
            },
        )

        fields, _ = extract_fields(schema, {"x": True})

        assert fields["alpha"] == 1
        assert fields["beta"] == 2
        assert counter.read_text(encoding="utf-8") == "1"

    def test_script_sentinel_on_missing_script(self) -> None:
        """If the script cannot be found, extract_fields returns the sentinel."""
        schema = self._schema_with_script("nonexistent_script_xyz.py")
        fields, _ = extract_fields(schema, {"snapshots": [], "collected_at": ""})
        assert fields["aged_count"] == -1  # sentinel (int field, script not found = broken)

    def test_filter_mounts_via_normalize(self) -> None:
        """The retired ListFilterSpec / list_filter pair was replaced by
        the `normalize: list:` DSL with `exclude_where`. This test pins
        the equivalent expression."""
        schema = _make_schema(
            name="mounts_test",
            fields={
                "raw_mounts": FieldSpec(path="raw_mounts", type="list", fallback=[]),
                "real_mounts": FieldSpec(
                    normalize={
                        "list": {
                            "source": "raw_mounts",
                            "exclude_where": {"field": "fstype", "op": "in", "value": ["tmpfs", "squashfs"]},
                        }
                    },
                    type="list",
                    fallback=[],
                ),
            },
        )
        raw = {
            "raw_mounts": [
                {"device": "/dev/sda1", "fstype": "ext4", "mountpoint": "/"},
                {"device": "tmpfs", "fstype": "tmpfs", "mountpoint": "/tmp"},
                {"device": "loop0", "fstype": "squashfs", "mountpoint": "/snap/core"},
                {"device": "/dev/sdb1", "fstype": "xfs", "mountpoint": "/data"},
            ],
        }
        fields, _ = extract_fields(schema, raw)
        assert len(fields["real_mounts"]) == 2
        mountpoints = {m["mountpoint"] for m in fields["real_mounts"]}
        assert mountpoints == {"/", "/data"}

    def test_vm_schema_snapshot_alerts_reference_list(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = CONFIGS_DIR / "vm.yaml"
        s = load_schema_from_file(schema_path)
        assert "snapshots" in s.fields
        spec = s.fields["snapshots"]
        assert spec.normalize is not None
        aged_alert = next((a for a in s.alerts if a.id == "aged_snapshots"), None)
        assert aged_alert is not None
        assert aged_alert.items is not None and "snapshots" in aged_alert.items

    def test_vmware_configs_do_not_use_scripts(self) -> None:
        configs_dir = Path(__file__).resolve().parents[2] / "ncs-ansible-vmware" / "ncs_configs"
        for schema_path in configs_dir.glob("*.yaml"):
            text = schema_path.read_text(encoding="utf-8")
            assert "script:" not in text
            assert "script_bundles:" not in text


# ---------------------------------------------------------------------------
# DateThresholdCondition
# ---------------------------------------------------------------------------


class TestDateThresholdCondition:
    """Tests for age_days Jinja2 filter used in when expressions."""

    REF = "2026-02-27T12:00:00Z"  # fixed reference timestamp

    def _schema(self, when_expr: str) -> ReportSchema:
        return ReportSchema(
            name="date_test",
            platform="test",
            display_name="Date Test",
            detection=DetectionSpec(keys_any=["x"]),
            fields={
                "last_run": FieldSpec(path="last_run", type="str", fallback=""),
                "ref_time": FieldSpec(path="ref_time", type="str", fallback=""),
            },
            alerts=[
                AlertRule(
                    id="date_alert",
                    category="Time",
                    severity="WARNING",
                    when=when_expr,
                    msg="date alert fired",
                )
            ],
        )

    def test_age_gt_fires_when_older(self) -> None:
        # 10 days before REF — should fire age_gt 7
        fields = {"last_run": "2026-02-17T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) > 7.0", fields) is True

    def test_age_gt_silent_when_younger(self) -> None:
        # 3 days before REF — should NOT fire age_gt 7
        fields = {"last_run": "2026-02-24T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) > 7.0", fields) is False

    def test_age_lt_fires_when_younger(self) -> None:
        # 1 day before REF — fires age_lt 3
        fields = {"last_run": "2026-02-26T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) < 3.0", fields) is True

    def test_age_lt_silent_when_older(self) -> None:
        # 10 days before REF — does NOT fire age_lt 3
        fields = {"last_run": "2026-02-17T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) < 3.0", fields) is False

    def test_age_gte_fires_at_exact_boundary(self) -> None:
        # Exactly 7.0 days before REF
        fields = {"last_run": "2026-02-20T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) >= 7.0", fields) is True

    def test_age_lte_fires_at_exact_boundary(self) -> None:
        fields = {"last_run": "2026-02-20T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) <= 7.0", fields) is True

    def test_age_gt_silent_at_exact_boundary(self) -> None:
        # Strictly greater-than: exact boundary should NOT fire
        fields = {"last_run": "2026-02-20T12:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) > 7.0", fields) is False

    def test_missing_field_returns_false(self) -> None:
        assert evaluate_when("missing | age_days > 1.0", {}) is False

    def test_unparseable_timestamp_returns_false(self) -> None:
        # age_days returns 0.0 for unparseable — 0.0 > 1.0 is False
        assert evaluate_when("last_run | age_days > 1.0", {"last_run": "not-a-date"}) is False

    def test_reference_field_used_over_now(self) -> None:
        fields = {"last_run": "2026-01-01T00:00:00Z", "ref_time": self.REF}
        assert evaluate_when("last_run | age_days(ref_time) > 7.0", fields) is True

    def test_normalize_from_schema_date_alert(self) -> None:
        schema = self._schema("last_run | age_days(ref_time) > 7.0")
        raw = {"last_run": "2026-01-01T00:00:00Z", "ref_time": self.REF}
        result = normalize_from_schema(schema, raw)
        assert any(a["id"] == "date_alert" for a in result["alerts"])


# ---------------------------------------------------------------------------
# TestPipes & Semantic Coercers
# ---------------------------------------------------------------------------


class TestPipes:
    def test_to_gb(self) -> None:
        raw = {"bytes": 10737418240}  # 10 GB
        assert resolve_field("bytes | to_gb", raw) == 10.0
        assert resolve_field("missing | to_gb", raw) == 0.0
        assert resolve_field("invalid | to_gb", {"invalid": "abc"}) == 0.0

    def test_to_mb(self) -> None:
        raw = {"bytes": 10485760}  # 10 MB
        assert resolve_field("bytes | to_mb", raw) == 10.0
        assert resolve_field("missing | to_mb", raw) == 0.0
        assert resolve_field("invalid | to_mb", {"invalid": "abc"}) == 0.0

    def test_to_days(self) -> None:
        raw = {"secs": 172800}  # 2 days
        assert resolve_field("secs | to_days", raw) == 2.0
        assert resolve_field("missing | to_days", raw) == 0.0
        assert resolve_field("invalid | to_days", {"invalid": "abc"}) == 0.0


class TestSemanticTypes:
    def test_coerce_bytes(self) -> None:
        from ncs_reporter.normalization.schema_driven import _coerce_bytes

        assert _coerce_bytes(1024) == 1024
        assert _coerce_bytes("2048.5") == 2048

    def test_coerce_percentage(self) -> None:
        from ncs_reporter.normalization.schema_driven import _coerce_percentage

        assert _coerce_percentage("85.5") == 85.5
        assert _coerce_percentage(100) == 100.0

    def test_coerce_datetime(self) -> None:
        from ncs_reporter.normalization.schema_driven import _coerce_datetime

        assert "2026-03-01T12:00:00+00:00" == _coerce_datetime("2026-03-01T12:00:00Z")
        assert _coerce_datetime("not-a-date") == "not-a-date"

    def test_coerce_duration(self) -> None:
        from ncs_reporter.normalization.schema_driven import _coerce_duration

        assert _coerce_duration("123.4") == 123.4
        assert _coerce_duration(500) == 500.0


# ---------------------------------------------------------------------------
# TestSchemaRefResolution
# ---------------------------------------------------------------------------


class TestSchemaRefResolution:
    def test_resolve_refs_with_json_pointer(self, tmp_path) -> None:
        from ncs_reporter.schema_loader import _resolve_refs

        shared_yaml = tmp_path / "shared.yaml"
        shared_yaml.write_text("fields:\n  uptime: { type: int, fallback: 0 }\n")

        main_dict = {"name": "test", "my_field": {"$ref": "shared.yaml#/fields/uptime"}}

        resolved = _resolve_refs(main_dict, tmp_path / "main.yaml")
        assert resolved["my_field"]["type"] == "int"
        assert resolved["my_field"]["fallback"] == 0

    def test_resolve_refs_overrides(self, tmp_path) -> None:
        from ncs_reporter.schema_loader import _resolve_refs

        shared_yaml = tmp_path / "shared.yaml"
        shared_yaml.write_text("fields:\n  uptime: { type: int, fallback: 0 }\n")

        main_dict = {
            "name": "test",
            "my_field": {
                "$ref": "shared.yaml#/fields/uptime",
                "fallback": 99,  # should override the ref
            },
        }

        resolved = _resolve_refs(main_dict, tmp_path / "main.yaml")
        assert resolved["my_field"]["type"] == "int"
        assert resolved["my_field"]["fallback"] == 99

    def test_resolve_refs_missing_file(self, tmp_path) -> None:
        from ncs_reporter.schema_loader import _resolve_refs

        main_dict = {"$ref": "nonexistent.yaml"}
        with pytest.raises(ValueError, match="Schema reference not found"):
            _resolve_refs(main_dict, tmp_path / "main.yaml")

    def test_resolve_refs_bad_pointer(self, tmp_path) -> None:
        from ncs_reporter.schema_loader import _resolve_refs

        shared_yaml = tmp_path / "shared.yaml"
        shared_yaml.write_text("a: 1")
        main_dict = {"$ref": "shared.yaml#/missing"}
        with pytest.raises(ValueError, match="Pointer /missing not found"):
            _resolve_refs(main_dict, tmp_path / "main.yaml")


# ---------------------------------------------------------------------------
# TestWidgetRendering
# ---------------------------------------------------------------------------


class TestWidgetRendering:
    def test_render_progress_bar_widget(self) -> None:
        from ncs_reporter.models.report_schema import ProgressBarWidget
        from ncs_reporter.view_models.generic import _render_widget

        w = ProgressBarWidget(
            slug="prog1",
            name="Progress",
            type="progress_bar",
            value="{{ used_pct }}",
            value_label="used_gb",
            color="auto",
            thresholds={"warn_if_above": 75, "crit_if_above": 90},
        )

        # Test ok range (below 75)
        fields = {"used_pct": 50.0, "used_gb": "50 GB"}
        r1 = _render_widget(w, fields, [])
        assert r1["percent"] == 50.0
        assert r1["label"] == "50 GB"
        assert r1["color"] == "green"

        # Test yellow range (75 to 89)
        fields2 = {"used_pct": 80.0}
        r2 = _render_widget(w, fields2, [])
        assert r2["color"] == "yellow"

        # Test red range (>= 90)
        fields3 = {"used_pct": 95.0}
        r3 = _render_widget(w, fields3, [])
        assert r3["color"] == "red"

        # Test out of bounds clamping
        fields4 = {"used_pct": 150.0}
        r4 = _render_widget(w, fields4, [])
        assert r4["percent"] == 100.0  # clamped

    def test_render_markdown_widget(self) -> None:
        from ncs_reporter.models.report_schema import MarkdownWidget
        from ncs_reporter.view_models.generic import _render_widget

        w = MarkdownWidget(slug="md1", name="Note", type="markdown", content="**bold**")
        r = _render_widget(w, {}, [])
        assert r["content"] == "**bold**"

    def test_conditional_table_styling(self) -> None:
        from ncs_reporter.models.report_schema import TableWidget, TableColumn, StyleRule
        from ncs_reporter.view_models.generic import _render_widget

        w = TableWidget(
            slug="t1",
            name="T1",
            type="table",
            rows_field="my_rows",
            columns=[
                TableColumn(
                    name="Status",
                    value="{{ status }}",
                    style_rules=[
                        StyleRule(when="status > 90", css_class="red")
                    ],
                )
            ],
        )

        fields = {"my_rows": [{"status": 80}, {"status": 95}]}
        r = _render_widget(w, fields, [])

        assert r["rows"][0][0]["css_class"] == ""  # 80 is not > 90
        assert r["rows"][1][0]["css_class"] == "red"  # 95 is > 90
