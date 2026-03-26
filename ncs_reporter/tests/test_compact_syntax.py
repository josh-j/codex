"""Tests for compact YAML syntax expansion in platform configs."""

from __future__ import annotations

import pytest

from ncs_reporter.schema_loader import (
    _expand_compact_column,
    _expand_compact_field,
    _expand_compact_syntax,
    _expand_compact_widget,
    load_schema_from_file,
)


# ---------------------------------------------------------------------------
# Compact field expansion
# ---------------------------------------------------------------------------


class TestCompactField:
    def test_path_with_type(self):
        result = _expand_compact_field(".health.disk | list")
        assert result == {"path": ".health.disk", "type": "list"}

    def test_path_with_type_and_fallback(self):
        result = _expand_compact_field(".health.os_info | dict = {}")
        assert result == {"path": ".health.os_info", "type": "dict", "fallback": {}}

    def test_path_with_fallback_only(self):
        result = _expand_compact_field(".ccm_service.state = unknown")
        assert result == {"path": ".ccm_service.state", "fallback": "unknown"}

    def test_path_with_numeric_fallback(self):
        result = _expand_compact_field(".uptime_hours = 0")
        assert result == {"path": ".uptime_hours", "fallback": 0}

    def test_path_with_bool_fallback(self):
        result = _expand_compact_field(".reboot_pending = false")
        assert result == {"path": ".reboot_pending", "fallback": False}

    def test_path_with_empty_string_fallback(self):
        result = _expand_compact_field(".hostname = ''")
        assert result == {"path": ".hostname", "fallback": ""}

    def test_pipe_transform_not_confused_with_type(self):
        result = _expand_compact_field(".stdout_lines | len_if_list")
        assert result == {"path": ".stdout_lines | len_if_list"}

    def test_pipe_transform_with_type_after(self):
        result = _expand_compact_field(".items | flatten | list")
        assert result == {"path": ".items | flatten", "type": "list"}

    def test_float_type(self):
        result = _expand_compact_field(".memory_pct | float")
        assert result == {"path": ".memory_pct", "type": "float"}

    def test_float_with_fallback(self):
        result = _expand_compact_field(".memory_pct | float = 0.0")
        assert result == {"path": ".memory_pct", "type": "float", "fallback": 0.0}


# ---------------------------------------------------------------------------
# Compact column expansion
# ---------------------------------------------------------------------------


class TestCompactColumn:
    def test_label_and_field(self):
        assert _expand_compact_column("Hostname: health_hostname") == {
            "label": "Hostname",
            "field": "health_hostname",
        }

    def test_badge(self):
        assert _expand_compact_column("Status: status [badge]") == {
            "label": "Status",
            "field": "status",
            "badge": True,
        }

    def test_no_colon(self):
        result = _expand_compact_column("hostname")
        assert result == {"label": "hostname", "field": "hostname"}


# ---------------------------------------------------------------------------
# Compact widget expansion
# ---------------------------------------------------------------------------


class TestCompactWidget:
    def test_alert_panel(self):
        result = _expand_compact_widget({"alert_panel": "Active Alerts"})
        assert result == {"id": "active_alerts", "title": "Active Alerts", "type": "alert_panel"}

    def test_key_value(self):
        result = _expand_compact_widget({
            "key_value": "Overview",
            "fields": ["Hostname: hostname", "OS: os_name"],
        })
        assert result == {
            "id": "overview",
            "title": "Overview",
            "type": "key_value",
            "fields": [
                {"label": "Hostname", "field": "hostname"},
                {"label": "OS", "field": "os_name"},
            ],
        }

    def test_table(self):
        result = _expand_compact_widget({
            "table": "Disk Usage",
            "rows": "health_disk",
            "columns": ["Drive: DeviceID", "Used %: UsedPct [badge]"],
        })
        assert result == {
            "id": "disk_usage",
            "title": "Disk Usage",
            "type": "table",
            "rows_field": "health_disk",
            "columns": [
                {"label": "Drive", "field": "DeviceID"},
                {"label": "Used %", "field": "UsedPct", "badge": True},
            ],
        }

    def test_explicit_id_overrides_auto(self):
        result = _expand_compact_widget({
            "alert_panel": "Alerts",
            "id": "my_alerts",
        })
        assert result["id"] == "my_alerts"

    def test_full_format_passthrough(self):
        original = {"id": "x", "title": "X", "type": "key_value", "fields": []}
        result = _expand_compact_widget(dict(original))
        assert result["id"] == "x"

    def test_compact_columns_in_full_format(self):
        widget = {
            "id": "tbl",
            "title": "T",
            "type": "table",
            "rows_field": "data",
            "columns": ["Name: name", "Status: status [badge]"],
        }
        result = _expand_compact_widget(widget)
        assert result["columns"] == [
            {"label": "Name", "field": "name"},
            {"label": "Status", "field": "status", "badge": True},
        ]


# ---------------------------------------------------------------------------
# Full expansion integration
# ---------------------------------------------------------------------------


class TestExpandCompactSyntax:
    def test_mixed_fields(self):
        data = {
            "name": "test",
            "detection": {"keys_any": ["test_raw"]},
            "fields": {
                "simple": "test_raw.data.host",
                "typed": ".disk | list",
                "fallback": ".state = unknown",
                "full": {"path": ".x", "type": "int"},
            },
        }
        result = _expand_compact_syntax(data)
        # simple bare string is NOT expanded (no ' | ' or ' = ')
        assert result["fields"]["simple"] == "test_raw.data.host"
        assert result["fields"]["typed"] == {"path": ".disk", "type": "list"}
        assert result["fields"]["fallback"] == {"path": ".state", "fallback": "unknown"}
        assert result["fields"]["full"] == {"path": ".x", "type": "int"}

    def test_compact_alert_string_rejected(self):
        data = {
            "name": "test",
            "detection": {"keys_any": ["x"]},
            "fields": {"f": "x.f"},
            "alerts": [
                "a1 | WARNING Cat | f gt 10 | msg",
            ],
        }
        with pytest.raises(ValueError, match="no longer supported"):
            _expand_compact_syntax(data)

    def test_dict_alerts_pass_through(self):
        data = {
            "name": "test",
            "detection": {"keys_any": ["x"]},
            "fields": {"f": "x.f"},
            "alerts": [
                {"id": "a1", "severity": "WARNING", "category": "Cat",
                 "when": "f > 10", "msg": "msg"},
                {"id": "a2", "severity": "CRITICAL", "category": "Cat",
                 "when": "f is defined", "msg": "m"},
            ],
        }
        result = _expand_compact_syntax(data)
        assert result["alerts"][0]["id"] == "a1"
        assert result["alerts"][1]["id"] == "a2"

    def test_fleet_columns_expansion(self):
        data = {
            "name": "test",
            "detection": {"keys_any": ["x"]},
            "fields": {"f": "x.f"},
            "fleet_columns": ["Host: hostname", "Score: score [badge]"],
        }
        result = _expand_compact_syntax(data)
        assert result["fleet_columns"] == [
            {"label": "Host", "field": "hostname"},
            {"label": "Score", "field": "score", "badge": True},
        ]


# ---------------------------------------------------------------------------
# Round-trip: compact YAML → expand → model_validate
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# List aggregation
# ---------------------------------------------------------------------------


class TestListAggregation:
    def test_any_where_match(self):
        from ncs_reporter.normalization._fields import _apply_any_where

        items = [{"status": "active"}, {"status": "disabled"}, {"status": "active"}]
        assert _apply_any_where(items, {"status": "disabled"}) is True

    def test_any_where_no_match(self):
        from ncs_reporter.normalization._fields import _apply_any_where

        items = [{"status": "active"}, {"status": "active"}]
        assert _apply_any_where(items, {"status": "disabled"}) is False

    def test_any_where_empty(self):
        from ncs_reporter.normalization._fields import _apply_any_where

        assert _apply_any_where([], {"status": "disabled"}) is False

    def test_all_where_match(self):
        from ncs_reporter.normalization._fields import _apply_all_where

        items = [{"status": "active"}, {"status": "active"}]
        assert _apply_all_where(items, {"status": "active"}) is True

    def test_all_where_no_match(self):
        from ncs_reporter.normalization._fields import _apply_all_where

        items = [{"status": "active"}, {"status": "disabled"}]
        assert _apply_all_where(items, {"status": "active"}) is False

    def test_all_where_empty(self):
        from ncs_reporter.normalization._fields import _apply_all_where

        assert _apply_all_where([], {"status": "active"}) is True

    def test_sum_field(self):
        from ncs_reporter.normalization._fields import _apply_sum_field

        items = [{"cpu": 25.0}, {"cpu": 30.5}, {"cpu": 44.5}]
        assert _apply_sum_field(items, "cpu") == 100.0

    def test_sum_field_missing_values(self):
        from ncs_reporter.normalization._fields import _apply_sum_field

        items = [{"cpu": 10}, {"other": 20}, {"cpu": 30}]
        assert _apply_sum_field(items, "cpu") == 40.0

    def test_sum_field_empty(self):
        from ncs_reporter.normalization._fields import _apply_sum_field

        assert _apply_sum_field([], "cpu") == 0.0

    def test_aggregation_mutual_exclusion(self):
        from ncs_reporter.models.report_schema import FieldSpec

        with pytest.raises(Exception, match="mutually exclusive"):
            FieldSpec(path=".x", count_where={"a": 1}, any_where={"b": 2})

    def test_any_where_in_pipeline(self):
        from ncs_reporter.normalization._fields import _apply_list_processing

        class FakeSpec:
            list_filter = None
            list_map = {}
            count_where = None
            any_where = {"enabled": False}
            all_where = None
            sum_field = None

        items = [{"enabled": True}, {"enabled": False}]
        assert _apply_list_processing(items, FakeSpec()) is True


# ---------------------------------------------------------------------------
# $include for alerts/widgets
# ---------------------------------------------------------------------------


class TestIncludeAlerts:
    def test_include_alerts_loads(self):
        """Photon config loads alerts via $include."""
        from pathlib import Path

        path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "photon.yaml"
        schema = load_schema_from_file(path)
        assert len(schema.alerts) == 9

    def test_include_widgets_loads(self):
        """Photon config loads widgets via $include."""
        from pathlib import Path

        path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "photon.yaml"
        schema = load_schema_from_file(path)
        assert len(schema.widgets) == 5  # alert_panel is auto-injected, not declared

    def test_include_with_local_override(self):
        """$local items with matching id replace included items."""
        from ncs_reporter.schema_loader import _resolve_includes
        from pathlib import Path
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmpdir:
            # Write included alerts file
            inc_path = os.path.join(tmpdir, "base_alerts.yaml")
            with open(inc_path, "w") as f:
                f.write("- id: alert_a\n  severity: WARNING\n  category: Test\n  when: \"x > 0\"\n  message: original\n")
                f.write("- id: alert_b\n  severity: INFO\n  category: Test\n  when: \"y > 0\"\n  message: keep\n")

            # Write main config data
            config_path = Path(tmpdir) / "config.yaml"
            data = {
                "alerts": {
                    "$include": "base_alerts.yaml",
                    "$local": [
                        {"id": "alert_a", "severity": "CRITICAL", "category": "Test", "when": "x > 0", "msg": "overridden"},
                        {"id": "alert_c", "severity": "INFO", "category": "Test", "when": "z > 0", "msg": "appended"},
                    ],
                },
            }
            result = _resolve_includes(data, config_path)
            alerts = result["alerts"]
            assert len(alerts) == 3
            assert alerts[0]["id"] == "alert_a"
            assert alerts[0]["severity"] == "CRITICAL"  # overridden
            assert alerts[1]["id"] == "alert_b"  # kept from include
            assert alerts[2]["id"] == "alert_c"  # appended


class TestRoundTrip:
    def test_config_with_when_validates(self):
        from ncs_reporter.models.report_schema import ReportSchema

        data = {
            "name": "roundtrip_test",
            "detection": {"keys_any": ["test_raw"]},
            "fields": {
                "hostname": "test_raw.host",
                "uptime": ".uptime | float = 0.0",
                "services": ".services | list",
            },
            "alerts": [
                {"id": "uptime_high", "category": "Health", "severity": "WARNING",
                 "when": "uptime > 86400", "msg": "Uptime over 24h"},
            ],
            "widgets": [
                {"alert_panel": "Alerts"},
                {
                    "key_value": "Info",
                    "fields": ["Host: hostname", "Uptime: uptime"],
                },
            ],
        }
        expanded = _expand_compact_syntax(data)
        schema = ReportSchema.model_validate(expanded)
        assert schema.name == "roundtrip_test"
        assert len(schema.fields) == 3
        assert len(schema.alerts) == 1
        assert schema.alerts[0].when == "uptime > 86400"
        assert len(schema.widgets) == 2

    def test_builtin_windows_loads(self):
        """The compact windows.yaml loads without errors."""
        from pathlib import Path

        path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "configs" / "windows.yaml"
        schema = load_schema_from_file(path)
        assert schema.name == "windows"
        assert len(schema.fields) == 29
        assert len(schema.alerts) == 9
        assert len(schema.widgets) == 12  # alert_panel is auto-injected
