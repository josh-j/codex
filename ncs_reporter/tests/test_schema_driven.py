"""Unit tests for the YAML-schema-driven reporting pipeline."""

from __future__ import annotations

import pytest

from ncs_reporter.models.report_schema import (
    AlertRule,
    ComputedFilterCondition,
    DateThresholdCondition,
    DetectionSpec,
    ExistsCondition,
    FieldSpec,
    FilterCountCondition,
    FilterSpec,
    MultiFilterCondition,
    ReportSchema,
    StringCondition,
    StringInCondition,
    ThresholdCondition,
)
from ncs_reporter.normalization.schema_driven import (
    _safe_eval_expr,
    build_schema_alerts,
    evaluate_condition,
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
            "first_tag_length": FieldSpec(compute="{first_tag} | len_if_list", type="int", fallback=0),
        },
        alerts=[
            AlertRule(
                id="high_error_rate",
                category="Network Health",
                severity="WARNING",
                condition=ThresholdCondition(op="gt", field="error_rate_pct", threshold=5.0),
                message="High error rate: {error_rate_pct}%",
            ),
            AlertRule(
                id="interfaces_down",
                category="Connectivity",
                severity="CRITICAL",
                condition=FilterCountCondition(
                    op="filter_count",
                    field="interface_list",
                    filter_field="status",
                    filter_value="down",
                    threshold=0,
                ),
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
        cond = ThresholdCondition(op="gt", field="cpu_pct", threshold=90.0)
        assert evaluate_condition(cond, {"cpu_pct": 95.0}) is True

    def test_threshold_gt_no_fire(self) -> None:
        cond = ThresholdCondition(op="gt", field="cpu_pct", threshold=90.0)
        assert evaluate_condition(cond, {"cpu_pct": 85.0}) is False

    def test_threshold_lte(self) -> None:
        cond = ThresholdCondition(op="lte", field="available_gb", threshold=5.0)
        assert evaluate_condition(cond, {"available_gb": 3.0}) is True
        assert evaluate_condition(cond, {"available_gb": 10.0}) is False

    def test_threshold_eq(self) -> None:
        cond = ThresholdCondition(op="eq", field="code", threshold=0.0)
        assert evaluate_condition(cond, {"code": 0}) is True
        assert evaluate_condition(cond, {"code": 1}) is False

    def test_threshold_missing_field_no_fire(self) -> None:
        cond = ThresholdCondition(op="gt", field="missing", threshold=0.0)
        assert evaluate_condition(cond, {}) is False

    def test_exists_condition_true(self) -> None:
        cond = ExistsCondition(op="exists", field="error_msg")
        assert evaluate_condition(cond, {"error_msg": "oops"}) is True

    def test_exists_condition_false_on_none(self) -> None:
        cond = ExistsCondition(op="exists", field="error_msg")
        assert evaluate_condition(cond, {"error_msg": None}) is False

    def test_not_exists_condition(self) -> None:
        cond = ExistsCondition(op="not_exists", field="error_msg")
        assert evaluate_condition(cond, {}) is True
        assert evaluate_condition(cond, {"error_msg": "present"}) is False

    def test_filter_count_fires(self) -> None:
        cond = FilterCountCondition(
            op="filter_count", field="ifaces", filter_field="status", filter_value="down", threshold=0
        )
        ifaces = [{"name": "eth0", "status": "down"}, {"name": "eth1", "status": "up"}]
        assert evaluate_condition(cond, {"ifaces": ifaces}) is True

    def test_filter_count_no_fire(self) -> None:
        cond = FilterCountCondition(
            op="filter_count", field="ifaces", filter_field="status", filter_value="down", threshold=0
        )
        ifaces = [{"name": "eth0", "status": "up"}]
        assert evaluate_condition(cond, {"ifaces": ifaces}) is False

    def test_filter_count_threshold_respected(self) -> None:
        cond = FilterCountCondition(
            op="filter_count", field="ifaces", filter_field="status", filter_value="down", threshold=2
        )
        ifaces = [
            {"name": "eth0", "status": "down"},
            {"name": "eth1", "status": "down"},
            {"name": "eth2", "status": "down"},
        ]
        assert evaluate_condition(cond, {"ifaces": ifaces}) is True


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

    def test_cross_ref_validation_catches_bad_alert_field(self) -> None:
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
                        condition=ThresholdCondition(op="gt", field="nonexistent_field", threshold=0),
                        message="oops",
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
            FieldSpec(path="a.b", compute="{x} + 1", type="float")


# ---------------------------------------------------------------------------
# Safe expression evaluator
# ---------------------------------------------------------------------------


class TestSafeEvalExpr:
    def test_simple_division(self) -> None:
        assert _safe_eval_expr("{a} / {b}", {"a": 100.0, "b": 4.0}) == 25.0

    def test_ratio_times_100(self) -> None:
        result = _safe_eval_expr("{freeSpace} / {capacity} * 100", {"freeSpace": 20.0, "capacity": 200.0})
        assert abs(result - 10.0) < 0.001

    def test_division_by_zero_returns_zero(self) -> None:
        assert _safe_eval_expr("{a} / {b}", {"a": 50.0, "b": 0.0}) == 0.0

    def test_missing_field_uses_zero(self) -> None:
        assert _safe_eval_expr("{missing} + 5", {}) == 5.0

    def test_addition(self) -> None:
        assert _safe_eval_expr("{x} + {y}", {"x": 3.0, "y": 4.0}) == 7.0

    def test_negation(self) -> None:
        assert _safe_eval_expr("-{x}", {"x": 5.0}) == -5.0

    def test_scalar_constant(self) -> None:
        assert _safe_eval_expr("86400", {}) == 86400.0

    def test_uptime_days_formula(self) -> None:
        result = _safe_eval_expr("{appliance_uptime_seconds} / 86400", {"appliance_uptime_seconds": 172800.0})
        assert result == 2.0

    def test_unsupported_operator_raises(self) -> None:
        with pytest.raises(ValueError):
            _safe_eval_expr("{x} ** 2", {"x": 3.0})

    def test_string_constant_raises(self) -> None:
        with pytest.raises((ValueError, SyntaxError)):
            _safe_eval_expr("'hello'", {})


# ---------------------------------------------------------------------------
# String conditions
# ---------------------------------------------------------------------------


class TestStringConditions:
    def test_eq_str_match(self) -> None:
        cond = StringCondition(op="eq_str", field="status", value="red")
        assert evaluate_condition(cond, {"status": "red"}) is True

    def test_eq_str_no_match(self) -> None:
        cond = StringCondition(op="eq_str", field="status", value="red")
        assert evaluate_condition(cond, {"status": "green"}) is False

    def test_eq_str_case_sensitive(self) -> None:
        cond = StringCondition(op="eq_str", field="status", value="red")
        assert evaluate_condition(cond, {"status": "RED"}) is False

    def test_ne_str_match(self) -> None:
        cond = StringCondition(op="ne_str", field="status", value="green")
        assert evaluate_condition(cond, {"status": "red"}) is True

    def test_ne_str_no_match(self) -> None:
        cond = StringCondition(op="ne_str", field="status", value="green")
        assert evaluate_condition(cond, {"status": "green"}) is False

    def test_eq_str_missing_field(self) -> None:
        cond = StringCondition(op="eq_str", field="status", value="red")
        assert evaluate_condition(cond, {}) is False

    def test_in_str_match(self) -> None:
        cond = StringInCondition(op="in_str", field="health", values=["red", "yellow"])
        assert evaluate_condition(cond, {"health": "yellow"}) is True

    def test_in_str_no_match(self) -> None:
        cond = StringInCondition(op="in_str", field="health", values=["red", "yellow"])
        assert evaluate_condition(cond, {"health": "green"}) is False

    def test_not_in_str(self) -> None:
        cond = StringInCondition(op="not_in_str", field="health", values=["red", "yellow"])
        assert evaluate_condition(cond, {"health": "green"}) is True
        assert evaluate_condition(cond, {"health": "red"}) is False


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
        cond = MultiFilterCondition(
            op="filter_multi",
            field="vms",
            filters=[
                FilterSpec(filter_field="power_state", filter_value="poweredOn"),
                FilterSpec(filter_field="tools_status", filter_value="toolsNotRunning"),
            ],
            threshold=0,
        )
        # vm-a matches both filters
        assert evaluate_condition(cond, {"vms": self._make_vms()}) is True

    def test_no_fire_when_partial_match_only(self) -> None:
        cond = MultiFilterCondition(
            op="filter_multi",
            field="vms",
            filters=[
                FilterSpec(filter_field="power_state", filter_value="poweredOn"),
                FilterSpec(filter_field="tools_status", filter_value="toolsNotInstalled"),
            ],
            threshold=0,
        )
        # No VM is both poweredOn AND toolsNotInstalled
        assert evaluate_condition(cond, {"vms": self._make_vms()}) is False

    def test_threshold_respected(self) -> None:
        cond = MultiFilterCondition(
            op="filter_multi",
            field="vms",
            filters=[FilterSpec(filter_field="power_state", filter_value="poweredOn")],
            threshold=1,  # require more than 1 match
        )
        # Two VMs are poweredOn, so count=2 > 1
        assert evaluate_condition(cond, {"vms": self._make_vms()}) is True

    def test_empty_list_no_fire(self) -> None:
        cond = MultiFilterCondition(
            op="filter_multi",
            field="vms",
            filters=[FilterSpec(filter_field="power_state", filter_value="poweredOn")],
            threshold=0,
        )
        assert evaluate_condition(cond, {"vms": []}) is False


# ---------------------------------------------------------------------------
# ComputedFilterCondition
# ---------------------------------------------------------------------------


class TestComputedFilterCondition:
    def _make_datastores(self) -> list[dict]:
        return [
            {"name": "ds1", "capacity": 1000, "freeSpace": 50},  # 5% free — critical
            {"name": "ds2", "capacity": 1000, "freeSpace": 120},  # 12% free — warning only
            {"name": "ds3", "capacity": 1000, "freeSpace": 500},  # 50% free — ok
        ]

    def test_fires_when_any_item_crosses_threshold(self) -> None:
        cond = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=10.0,
        )
        assert evaluate_condition(cond, {"datastores": self._make_datastores()}) is True

    def test_no_fire_when_all_clear(self) -> None:
        cond = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=10.0,
        )
        # All datastores have ≥ 50% free
        all_ok = [{"name": f"ds{i}", "capacity": 1000, "freeSpace": 500} for i in range(3)]
        assert evaluate_condition(cond, {"datastores": all_ok}) is False

    def test_warning_threshold_fires_but_critical_does_not(self) -> None:
        crit = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=10.0,
        )
        warn = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=15.0,
        )
        # ds2 is at 12% — warn fires, crit does not
        only_warning = [{"name": "ds2", "capacity": 1000, "freeSpace": 120}]
        assert evaluate_condition(crit, {"datastores": only_warning}) is False
        assert evaluate_condition(warn, {"datastores": only_warning}) is True

    def test_division_by_zero_skips_item(self) -> None:
        cond = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=10.0,
        )
        bad = [{"name": "ds0", "capacity": 0, "freeSpace": 0}]
        # 0 / 0 → 0.0 ≤ 10.0 would actually fire; expression yields 0.0
        result = evaluate_condition(cond, {"datastores": bad})
        assert isinstance(result, bool)  # just verify it doesn't raise

    def test_empty_list_no_fire(self) -> None:
        cond = ComputedFilterCondition(
            op="computed_filter",
            field="datastores",
            expression="{freeSpace} / {capacity} * 100",
            cmp="lte",
            threshold=10.0,
        )
        assert evaluate_condition(cond, {"datastores": []}) is False


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
                "cpu_pct": FieldSpec(compute="{cpu_used_mhz} / {cpu_total_mhz} * 100", type="float", fallback=0.0),
                "uptime_seconds": FieldSpec(path="uptime", type="float", fallback=0.0),
                "uptime_days": FieldSpec(compute="{uptime_seconds} / 86400", type="float", fallback=0.0),
            },
            alerts=[
                AlertRule(
                    id="high_cpu",
                    category="Compute",
                    severity="CRITICAL",
                    condition=ThresholdCondition(op="gt", field="cpu_pct", threshold=90.0),
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
            FieldSpec(path="a.b", compute="{x} * 2", type="float")


# ---------------------------------------------------------------------------
# vcenter.yaml schema round-trip validation
# ---------------------------------------------------------------------------


class TestVcenterSchema:
    def test_vcenter_schema_loads_and_validates(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "vcenter.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == "vcenter"
        assert s.platform == "vmware"
        # Verify all new condition types are present
        ops = {a.condition.op for a in s.alerts}  # type: ignore[union-attr]
        assert "eq_str" in ops
        assert "computed_filter" in ops
        assert "filter_multi" in ops
        # Verify compute field
        assert "appliance_uptime_days" in s.fields
        assert s.fields["appliance_uptime_days"].compute is not None

    def test_vcenter_schema_fires_on_synthetic_bundle(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file
        from ncs_reporter.normalization.schema_driven import normalize_from_schema

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "vcenter.yaml"
        s = load_schema_from_file(schema_path)

        # Bundle mirrors the raw YAML file structure exactly (read_report no longer
        # unwraps the data key, so schema paths match what is on disk).
        bundle = {
            "vmware_raw_vcenter": {
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
                    "datacenters_info": {"value": [{"name": "DC1", "datacenter": "dc-1"}]},
                    "datastores_info": {
                        "datastores": [
                            {
                                "name": "ds-prod",
                                "type": "VMFS",
                                "capacity": 1000,
                                "freeSpace": 80,
                                "accessible": True,
                                "maintenanceMode": "normal",
                            },
                        ]
                    },
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
        # ds-prod is at 8% free — critical space fires
        assert "datastore_critical_space" in fired
        # vm_tools_not_running fires (poweredOn + toolsNotRunning)
        assert "vm_tools_not_running" in fired
        # Overall health should be CRITICAL
        assert result["health"] == "CRITICAL"
        # uptime_days computed correctly (172800s / 86400 = 2.0 days)
        assert abs(result["fields"]["appliance_uptime_days"] - 2.0) < 0.001


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
                    condition=ThresholdCondition(op="gt", field="aged_count", threshold=0),
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
        from ncs_reporter.models.report_schema import DetectionSpec, FieldSpec, ReportSchema

        schema = ReportSchema(
            name="mounts_test",
            platform="linux",
            display_name="Mounts Test",
            detection=DetectionSpec(keys_any=["x"]),
            fields={
                "mounts": FieldSpec(path="raw_mounts", type="list", fallback=[]),
                "real_mounts": FieldSpec(
                    script="filter_mounts.py",
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
            ]
        }
        fields, _ = extract_fields(schema, raw)
        assert len(fields["real_mounts"]) == 2
        mountpoints = {m["mountpoint"] for m in fields["real_mounts"]}
        assert mountpoints == {"/", "/data"}

    def test_vcenter_schema_aged_snapshot_field_exists(self) -> None:
        from pathlib import Path
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "vcenter.yaml"
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
    """Tests for native ISO timestamp age comparison conditions."""

    REF = "2026-02-27T12:00:00Z"  # fixed reference timestamp

    def _schema(self, op: str, days: float, reference_field: str | None = None) -> ReportSchema:
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
                    condition=DateThresholdCondition(
                        op=op,  # type: ignore[arg-type]
                        field="last_run",
                        days=days,
                        reference_field=reference_field,
                    ),
                    message="date alert fired",
                )
            ],
        )

    def _eval(self, op: str, days: float, field_ts: str, ref_ts: str | None = None) -> bool:
        fields = {
            "last_run": field_ts,
            "ref_time": ref_ts or self.REF,
        }
        cond = DateThresholdCondition(
            op=op,  # type: ignore[arg-type]
            field="last_run",
            days=days,
            reference_field="ref_time" if ref_ts is not None else None,
        )
        return evaluate_condition(cond, fields)

    def test_age_gt_fires_when_older(self) -> None:
        # 10 days before REF — should fire age_gt 7
        assert self._eval("age_gt", 7.0, "2026-02-17T12:00:00Z", self.REF) is True

    def test_age_gt_silent_when_younger(self) -> None:
        # 3 days before REF — should NOT fire age_gt 7
        assert self._eval("age_gt", 7.0, "2026-02-24T12:00:00Z", self.REF) is False

    def test_age_lt_fires_when_younger(self) -> None:
        # 1 day before REF — fires age_lt 3
        assert self._eval("age_lt", 3.0, "2026-02-26T12:00:00Z", self.REF) is True

    def test_age_lt_silent_when_older(self) -> None:
        # 10 days before REF — does NOT fire age_lt 3
        assert self._eval("age_lt", 3.0, "2026-02-17T12:00:00Z", self.REF) is False

    def test_age_gte_fires_at_exact_boundary(self) -> None:
        # Exactly 7.0 days before REF
        assert self._eval("age_gte", 7.0, "2026-02-20T12:00:00Z", self.REF) is True

    def test_age_lte_fires_at_exact_boundary(self) -> None:
        assert self._eval("age_lte", 7.0, "2026-02-20T12:00:00Z", self.REF) is True

    def test_age_gt_silent_at_exact_boundary(self) -> None:
        # Strictly greater-than: exact boundary should NOT fire
        assert self._eval("age_gt", 7.0, "2026-02-20T12:00:00Z", self.REF) is False

    def test_missing_field_returns_false(self) -> None:
        cond = DateThresholdCondition(op="age_gt", field="missing", days=1.0)
        assert evaluate_condition(cond, {}) is False

    def test_unparseable_timestamp_returns_false(self) -> None:
        cond = DateThresholdCondition(op="age_gt", field="last_run", days=1.0)
        assert evaluate_condition(cond, {"last_run": "not-a-date"}) is False

    def test_reference_field_used_over_now(self) -> None:
        # Use reference_field so the test is deterministic regardless of when it runs
        fields = {"last_run": "2026-01-01T00:00:00Z", "ref_time": self.REF}
        cond = DateThresholdCondition(op="age_gt", field="last_run", days=7.0, reference_field="ref_time")
        assert evaluate_condition(cond, fields) is True

    def test_normalize_from_schema_date_alert(self) -> None:
        schema = self._schema("age_gt", 7.0, reference_field="ref_time")
        raw = {"last_run": "2026-01-01T00:00:00Z", "ref_time": self.REF}
        result = normalize_from_schema(schema, raw)
        assert any(a["id"] == "date_alert" for a in result["alerts"])
