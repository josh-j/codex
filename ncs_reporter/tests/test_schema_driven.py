"""Unit tests for the YAML-schema-driven reporting pipeline."""

from __future__ import annotations

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
                message="High error rate: {error_rate_pct}%",
            ),
            AlertRule(
                id="interfaces_down",
                category="Connectivity",
                severity="CRITICAL",
                when="interface_list | selectattr('status', 'eq', 'down') | list | length > 0",
                message="Interface(s) down detected",
                affected_items_field="interface_list",
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
        schema = ReportSchema(
            name="coerce_test",
            platform="test",
            display_name="Coerce Test",
            detection=DetectionSpec(keys_any=["x"]),
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
            assert "detail" in alert
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

    def test_cross_ref_validation_catches_bad_detail_field(self) -> None:
        with pytest.raises(ValueError, match="undeclared field"):
            ReportSchema(
                name="bad",
                platform="test",
                display_name="Bad",
                detection=DetectionSpec(keys_any=["x"]),
                fields={},
                alerts=[
                    AlertRule(
                        id="bad_alert",
                        category="Test",
                        severity="WARNING",
                        when="true",
                        message="oops",
                        detail_fields=["nonexistent_field"],
                    )
                ],
            )

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
                "title": "Alias Test",
                "detection": {"any": ["raw_test"]},
                "fields": {
                    "hostname": {"from": "raw_test.data.hostname", "default": "unknown"},
                    "uptime_days": {"expr": "uptime_seconds / 86400", "default": 0.0, "type": "float"},
                    "uptime_seconds": {"from": "raw_test.data.uptime", "type": "float", "default": 0.0},
                    "rows_data": {"from": "raw_test.data.rows", "type": "list", "default": []},
                },
                "widgets": [
                    {
                        "id": "summary",
                        "title": "Summary",
                        "type": "key_value",
                        "fields": [{"title": "Host", "field": "hostname"}],
                    },
                    {
                        "id": "table1",
                        "title": "Rows",
                        "type": "table",
                        "rows": "rows_data",
                        "columns": [{"title": "Name", "field": "name"}],
                    },
                ],
                "fleet_columns": [{"title": "Host", "field": "hostname"}],
            }
        )

        assert schema.display_name == "Alias Test"
        assert schema.detection.keys_any == ["raw_test"]
        assert schema.fields["hostname"].path == "raw_test.data.hostname"
        assert schema.fields["hostname"].fallback == "unknown"
        assert schema.fields["uptime_days"].compute == "uptime_seconds / 86400"
        assert schema.widgets[1].rows_field == "rows_data"
        assert schema.fleet_columns[0].label == "Host"


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
                    message="CPU usage is {cpu_pct:.1f}%",
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
# vcsa.yaml schema round-trip validation
# ---------------------------------------------------------------------------


class TestVcenterSchema:
    def test_vcenter_schema_loads_and_validates(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "vcsa.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "vcenter"
        assert s.platform == "vmware"
        # Verify when expressions are present
        when_exprs = {a.when for a in s.alerts}
        assert any("==" in w for w in when_exprs)  # string comparisons
        assert any("selectattr" in w for w in when_exprs)  # filter expressions
        # Verify compute field
        assert "appliance_uptime_days" in s.fields
        assert s.fields["appliance_uptime_days"].compute is not None

    def test_vcenter_schema_fires_on_synthetic_bundle(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "vcsa.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_vcenter": {
                "metadata": {"timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "appliance_health_info": {
                        "appliance": {
                            "summary": {
                                "version": "8.0.1",
                                "build_number": "12345",
                                "uptime": 172800,
                                "health": {
                                    "overall": "yellow",
                                    "cpu": "green",
                                    "memory": "green",
                                    "database": "green",
                                    "storage": "green",
                                },
                            },
                            "access": {"ssh": True, "shell": {"enabled": False}},
                            "time": {"time_sync": {"mode": "NTP"}},
                        }
                    },
                    "appliance_backup_info": {"schedules": []},
                    "alarms_info": {"alarms": [], "count": 0, "python": "/usr/bin/python3"},
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


class TestEsxiHealthSchema:
    def test_esxi_schema_loads_and_validates(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "esxi.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "esxi"
        assert s.platform == "vmware"
        assert s.split_field == "esxi_hosts"
        when_exprs = {a.when for a in s.alerts}
        assert any("disconnected" in w for w in when_exprs)  # host_disconnected
        assert "connection_state" in s.fields
        assert "cpu_used_pct" in s.fields

    def test_esxi_schema_fires_on_per_host_bundle(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "esxi.yaml"
        s = load_schema_from_file(schema_path)

        # Simulate a per-host bundle (after split_field expansion)
        bundle = {
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
        }

        result = normalize_from_schema(s, bundle)
        fired = {a["id"] for a in result["alerts"]}
        assert "host_disconnected" in fired
        assert "ssh_enabled" in fired


class TestVmHealthSchema:
    def test_vm_schema_loads_and_validates(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "vm.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "vm"
        assert s.platform == "vmware"
        when_exprs = {a.when for a in s.alerts}
        assert any("selectattr" in w for w in when_exprs)  # filter_multi equivalent
        assert "vm_count" in s.fields
        assert "snapshot_count" in s.fields

    def test_vm_schema_fires_on_synthetic_bundle(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "vm.yaml"
        s = load_schema_from_file(schema_path)

        bundle = {
            "raw_vm": {
                "metadata": {"timestamp": "2026-02-27T00:00:00Z"},
                "data": {
                    "datacenters_info": {"datacenter_info": [{"name": "DC1"}]},
                    "vms_info": {
                        "virtual_machines": [
                            {
                                "guest_name": "vm1",
                                "power_state": "poweredOn",
                                "tools_status": "toolsNotRunning",
                                "cluster": "cluster1",
                            },
                        ]
                    },
                    "snapshots_info": {"snapshots": []},
                },
            }
        }

        result = normalize_from_schema(s, bundle)
        fired = {a["id"] for a in result["alerts"]}
        # vm_tools_not_running fires (poweredOn + toolsNotRunning)
        assert "vm_tools_not_running" in fired


class TestPhotonSchema:
    def test_photon_schema_loads_and_detects_bundle(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import detect_schemas_for_bundle, load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "photon.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "photon"
        assert s.platform == "linux"

        bundle = {
            "raw_discovery": {
                "metadata": {"timestamp": "2026-03-02T00:00:00Z"},
                "data": {"ansible_facts": {"hostname": "photon-01"}},
            }
        }
        detected = detect_schemas_for_bundle(bundle)
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
                    message="{aged_count} aged snapshot(s)",
                    detail_fields=["aged_count"],
                )
            ],
        )

    def test_count_aged_snapshots_none_old(self) -> None:
        schema = self._schema_with_script("normalize_snapshots.py", {"age_days": 7, "mode": "count"})
        raw = {
            "snapshots": [{"creation_time": "2026-02-27T00:00:00Z"}],
            "collected_at": "2026-02-27T06:00:00Z",
        }
        fields, _ = extract_fields(schema, raw)
        assert fields["aged_count"] == 0

    def test_count_aged_snapshots_one_old(self) -> None:
        schema = self._schema_with_script("normalize_snapshots.py", {"age_days": 7, "mode": "count"})
        raw = {
            # snapshot created 10 days before collection
            "snapshots": [{"creation_time": "2026-02-17T00:00:00Z"}],
            "collected_at": "2026-02-27T00:00:00Z",
        }
        fields, _ = extract_fields(schema, raw)
        assert fields["aged_count"] == 1

    def test_count_aged_snapshots_mixed(self) -> None:
        schema = self._schema_with_script("normalize_snapshots.py", {"age_days": 7, "mode": "count"})
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
        schema = self._schema_with_script("normalize_snapshots.py", {"age_days": 7, "mode": "count"})
        raw = {
            "snapshots": [{"creation_time": "2026-01-01T00:00:00Z"}],
            "collected_at": "2026-02-27T00:00:00Z",
        }
        result = normalize_from_schema(schema, raw)
        assert any(a["id"] == "aged" for a in result["alerts"])

    def test_script_sentinel_on_missing_script(self) -> None:
        """If the script cannot be found, extract_fields returns the sentinel."""
        schema = self._schema_with_script("nonexistent_script_xyz.py")
        fields, _ = extract_fields(schema, {"snapshots": [], "collected_at": ""})
        assert fields["aged_count"] == -1  # sentinel (int field, script not found = broken)

    def test_filter_mounts_script(self) -> None:
        from ncs_reporter.models.report_schema import DetectionSpec, FieldSpec, ListFilterSpec, ReportSchema

        schema = ReportSchema(
            name="mounts_test",
            platform="linux",
            display_name="Mounts Test",
            detection=DetectionSpec(keys_any=["x"]),
            fields={
                "mounts": FieldSpec(path="raw_mounts", type="list", fallback=[]),
                "real_mounts": FieldSpec(
                    path="raw_mounts",
                    type="list",
                    list_filter=ListFilterSpec(exclude={"fstype": ["tmpfs", "squashfs"]}),
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
            ]
        }
        fields, _ = extract_fields(schema, raw)
        assert len(fields["real_mounts"]) == 2
        mountpoints = {m["mountpoint"] for m in fields["real_mounts"]}
        assert mountpoints == {"/", "/data"}

    def test_vm_schema_aged_snapshot_field_exists(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "vm.yaml"
        s = load_schema_from_file(schema_path)
        assert "aged_snapshot_count" in s.fields
        spec = s.fields["aged_snapshot_count"]
        assert spec.script == "normalize_snapshots.py"
        assert spec.script_args.get("age_days") == 7
        assert any(a.id == "aged_snapshots" for a in s.alerts)


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
                    message="date alert fired",
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
            id="prog1",
            title="Progress",
            type="progress_bar",
            field="used_pct",
            label="used_gb",
            color="auto",
            thresholds={75: "yellow", 90: "red"},
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

        w = MarkdownWidget(id="md1", title="Note", type="markdown", content="**bold**")
        r = _render_widget(w, {}, [])
        assert r["content"] == "**bold**"

    def test_conditional_table_styling(self) -> None:
        from ncs_reporter.models.report_schema import TableWidget, TableColumn, StyleRule
        from ncs_reporter.view_models.generic import _render_widget

        w = TableWidget(
            id="t1",
            title="T1",
            type="table",
            rows_field="my_rows",
            columns=[
                TableColumn(
                    label="Status",
                    field="status",
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
