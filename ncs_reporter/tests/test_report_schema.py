"""Tests for report_schema model features: path_prefix, platform default, validation, list processing, suppress_if."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from ncs_reporter.models.report_schema import ReportSchema


# ---------------------------------------------------------------------------
# path_prefix expansion
# ---------------------------------------------------------------------------


class TestPathPrefix:
    def test_relative_paths_expanded(self) -> None:
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "path_prefix": "raw.data",
            "fields": {
                "hostname": {"path": ".facts.hostname"},
                "version": {"path": ".facts.version"},
            },
        }
        s = ReportSchema.model_validate(raw)
        assert s.fields["hostname"].path == "raw.data.facts.hostname"
        assert s.fields["version"].path == "raw.data.facts.version"

    def test_absolute_paths_unchanged(self) -> None:
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "path_prefix": "raw.data",
            "fields": {
                "hostname": {"path": ".facts.hostname"},
                "collected_at": {"path": "raw.metadata.timestamp"},
            },
        }
        s = ReportSchema.model_validate(raw)
        assert s.fields["hostname"].path == "raw.data.facts.hostname"
        assert s.fields["collected_at"].path == "raw.metadata.timestamp"

    def test_no_prefix_no_change(self) -> None:
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "fields": {
                "hostname": {"path": "raw.data.facts.hostname"},
            },
        }
        s = ReportSchema.model_validate(raw)
        assert s.fields["hostname"].path == "raw.data.facts.hostname"

    def test_short_form_with_prefix(self) -> None:
        """Short-form strings are expanded BEFORE prefix is applied (they become path dicts)."""
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "path_prefix": "raw.data",
            "fields": {
                "ts": "raw.metadata.timestamp",
            },
        }
        s = ReportSchema.model_validate(raw)
        # Short-form is an absolute path, no leading dot → unchanged
        assert s.fields["ts"].path == "raw.metadata.timestamp"

    def test_compute_and_script_unaffected(self) -> None:
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "path_prefix": "raw.data",
            "fields": {
                "a": {"path": ".some_val", "type": "float"},
                "b": {"compute": "{a} * 100", "type": "float"},
                "c": {"script": "test.py"},
            },
        }
        s = ReportSchema.model_validate(raw)
        assert s.fields["a"].path == "raw.data.some_val"
        assert s.fields["b"].compute == "{a} * 100"
        assert s.fields["c"].script == "test.py"

    def test_pipe_transform_preserved(self) -> None:
        raw: dict[str, Any] = {
            "name": "test",
            "detection": {"keys_any": ["raw"]},
            "path_prefix": "raw.data",
            "fields": {
                "count": {"path": ".items | len_if_list", "type": "int"},
            },
        }
        s = ReportSchema.model_validate(raw)
        assert s.fields["count"].path == "raw.data.items | len_if_list"


# ---------------------------------------------------------------------------
# platform defaults to name
# ---------------------------------------------------------------------------


class TestPlatformDefault:
    def test_platform_defaults_to_name(self) -> None:
        raw: dict[str, Any] = {
            "name": "linux",
            "detection": {"keys_any": ["raw"]},
        }
        s = ReportSchema.model_validate(raw)
        assert s.platform == "linux"

    def test_explicit_platform_preserved(self) -> None:
        raw: dict[str, Any] = {
            "name": "photon",
            "platform": "linux",
            "detection": {"keys_any": ["raw"]},
        }
        s = ReportSchema.model_validate(raw)
        assert s.platform == "linux"

    def test_empty_platform_defaults_to_name(self) -> None:
        raw: dict[str, Any] = {
            "name": "vcenter",
            "platform": "",
            "detection": {"keys_any": ["raw"]},
        }
        s = ReportSchema.model_validate(raw)
        assert s.platform == "vcenter"


# ---------------------------------------------------------------------------
# Built-in schemas load successfully
# ---------------------------------------------------------------------------


class TestBuiltinSchemas:
    @pytest.mark.parametrize("schema_name", ["linux", "photon", "windows", "vcenter"])
    def test_builtin_schema_loads(self, schema_name: str) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / f"{schema_name}.yaml"
        s = load_schema_from_file(schema_path)
        assert s.name == schema_name
        assert s.platform  # non-empty
        assert len(s.fields) > 0

    def test_linux_paths_expanded(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "linux.yaml"
        s = load_schema_from_file(schema_path)
        assert s.fields["hostname"].path == "ubuntu_raw_discovery.data.ansible_facts.hostname"
        assert s.fields["collected_at"].path == "ubuntu_raw_discovery.metadata.timestamp"

    def test_linux_platform_defaults_to_name(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "linux.yaml"
        s = load_schema_from_file(schema_path)
        assert s.platform == "linux"

    def test_vcenter_keeps_explicit_platform(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "vcenter.yaml"
        s = load_schema_from_file(schema_path)
        assert s.platform == "vmware"

    def test_photon_uses_include(self) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        schema_path = Path(__file__).parent.parent / "src" / "ncs_reporter" / "schemas" / "photon.yaml"
        s = load_schema_from_file(schema_path)
        # Fields from linux_base_fields.yaml should be included
        assert "hostname" in s.fields
        assert "disks" in s.fields
        # Plus the local override
        assert "collected_at" in s.fields
        assert s.fields["collected_at"].path == "raw_discovery.metadata.timestamp"


# ---------------------------------------------------------------------------
# Schema validation error formatting
# ---------------------------------------------------------------------------


class TestSchemaValidationErrors:
    def test_format_schema_validation_error(self) -> None:
        from pydantic import ValidationError

        from ncs_reporter.schema_loader import format_schema_validation_error

        try:
            ReportSchema.model_validate({"name": "bad"})
        except ValidationError as exc:
            msg = format_schema_validation_error(Path("test.yaml"), exc)
            assert "Invalid schema test.yaml:" in msg
            assert "detection" in msg


# ---------------------------------------------------------------------------
# list_filter
# ---------------------------------------------------------------------------


class TestListFilter:
    def test_exclude_by_exact_match(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "items": {
                        "path": "raw.data",
                        "type": "list",
                        "list_filter": {"exclude": {"fstype": ["tmpfs", "devtmpfs"]}},
                    }
                },
            }
        )
        bundle = {
            "raw": {
                "data": [
                    {"mount": "/", "fstype": "ext4"},
                    {"mount": "/dev/shm", "fstype": "tmpfs"},
                    {"mount": "/run", "fstype": "devtmpfs"},
                    {"mount": "/home", "fstype": "ext4"},
                ]
            }
        }
        fields, _ = extract_fields(s, bundle)
        assert len(fields["items"]) == 2
        assert fields["items"][0]["mount"] == "/"
        assert fields["items"][1]["mount"] == "/home"

    def test_exclude_by_regex(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "items": {
                        "path": "raw.data",
                        "type": "list",
                        "list_filter": {"exclude": {"device": ["^/dev/loop"]}},
                    }
                },
            }
        )
        bundle = {
            "raw": {
                "data": [
                    {"device": "/dev/sda1", "mount": "/"},
                    {"device": "/dev/loop0", "mount": "/snap/core"},
                    {"device": "/dev/loop1", "mount": "/snap/other"},
                ]
            }
        }
        fields, _ = extract_fields(s, bundle)
        assert len(fields["items"]) == 1
        assert fields["items"][0]["device"] == "/dev/sda1"


# ---------------------------------------------------------------------------
# list_map
# ---------------------------------------------------------------------------


class TestListMap:
    def test_computes_derived_fields(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "disks": {
                        "path": "raw.mounts",
                        "type": "list",
                        "list_map": {
                            "total_gb": "{size_total} / 1073741824",
                            "used_pct": "({size_total} - {size_available}) / {size_total} * 100",
                        },
                    }
                },
            }
        )
        bundle = {"raw": {"mounts": [{"size_total": 1073741824, "size_available": 536870912, "mount": "/"}]}}
        fields, _ = extract_fields(s, bundle)
        disks = fields["disks"]
        assert len(disks) == 1
        assert disks[0]["total_gb"] == 1.0
        assert abs(disks[0]["used_pct"] - 50.0) < 0.1
        # Original fields preserved
        assert disks[0]["mount"] == "/"

    def test_filter_and_map_combined(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "disks": {
                        "path": "raw.mounts",
                        "type": "list",
                        "list_filter": {"exclude": {"fstype": ["tmpfs"]}},
                        "list_map": {"used_pct": "({size_total} - {size_available}) / {size_total} * 100"},
                    }
                },
            }
        )
        bundle = {
            "raw": {
                "mounts": [
                    {"size_total": 100, "size_available": 50, "fstype": "ext4"},
                    {"size_total": 100, "size_available": 90, "fstype": "tmpfs"},
                ]
            }
        }
        fields, _ = extract_fields(s, bundle)
        assert len(fields["disks"]) == 1
        assert abs(fields["disks"][0]["used_pct"] - 50.0) < 0.1


# ---------------------------------------------------------------------------
# count_where
# ---------------------------------------------------------------------------


class TestCountWhere:
    def test_count_matching_items(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "critical_count": {
                        "path": "raw.alarms",
                        "type": "int",
                        "count_where": {"severity": "critical"},
                    }
                },
            }
        )
        bundle = {
            "raw": {
                "alarms": [
                    {"severity": "critical", "name": "a1"},
                    {"severity": "warning", "name": "a2"},
                    {"severity": "Critical", "name": "a3"},  # case-insensitive
                    {"severity": "warning", "name": "a4"},
                ]
            }
        }
        fields, _ = extract_fields(s, bundle)
        assert fields["critical_count"] == 2

    def test_count_where_no_matches(self) -> None:
        from ncs_reporter.normalization.schema_driven import extract_fields

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {
                    "count": {"path": "raw.items", "type": "int", "count_where": {"status": "failed"}}
                },
            }
        )
        bundle = {"raw": {"items": [{"status": "ok"}, {"status": "ok"}]}}
        fields, _ = extract_fields(s, bundle)
        assert fields["count"] == 0


# ---------------------------------------------------------------------------
# suppress_if on alerts
# ---------------------------------------------------------------------------


class TestSuppressIf:
    def test_suppress_if_single(self) -> None:
        from ncs_reporter.normalization.schema_driven import build_schema_alerts

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"val": {"path": "raw.val", "type": "float"}},
                "alerts": [
                    {
                        "id": "critical",
                        "category": "test",
                        "severity": "CRITICAL",
                        "condition": {"op": "gte", "field": "val", "threshold": 95},
                        "message": "critical",
                    },
                    {
                        "id": "warning",
                        "category": "test",
                        "severity": "WARNING",
                        "suppress_if": "critical",
                        "condition": {"op": "gte", "field": "val", "threshold": 80},
                        "message": "warning",
                    },
                ],
            }
        )
        # Both conditions match, but warning is suppressed
        fields = {"val": 99.0}
        alerts = build_schema_alerts(s, fields)
        ids = {a["id"] for a in alerts}
        assert "critical" in ids
        assert "warning" not in ids

    def test_suppress_if_not_triggered(self) -> None:
        from ncs_reporter.normalization.schema_driven import build_schema_alerts

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"val": {"path": "raw.val", "type": "float"}},
                "alerts": [
                    {
                        "id": "critical",
                        "category": "test",
                        "severity": "CRITICAL",
                        "condition": {"op": "gte", "field": "val", "threshold": 95},
                        "message": "critical",
                    },
                    {
                        "id": "warning",
                        "category": "test",
                        "severity": "WARNING",
                        "suppress_if": "critical",
                        "condition": {"op": "gte", "field": "val", "threshold": 80},
                        "message": "warning",
                    },
                ],
            }
        )
        # Only warning condition matches (critical threshold not reached)
        fields = {"val": 90.0}
        alerts = build_schema_alerts(s, fields)
        ids = {a["id"] for a in alerts}
        assert "critical" not in ids
        assert "warning" in ids

    def test_suppress_if_list(self) -> None:
        from ncs_reporter.normalization.schema_driven import build_schema_alerts

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"val": {"path": "raw.val", "type": "float"}},
                "alerts": [
                    {
                        "id": "a",
                        "category": "test",
                        "severity": "CRITICAL",
                        "condition": {"op": "gte", "field": "val", "threshold": 95},
                        "message": "a",
                    },
                    {
                        "id": "b",
                        "category": "test",
                        "severity": "WARNING",
                        "condition": {"op": "gte", "field": "val", "threshold": 90},
                        "message": "b",
                    },
                    {
                        "id": "c",
                        "category": "test",
                        "severity": "INFO",
                        "suppress_if": ["a", "b"],
                        "condition": {"op": "gte", "field": "val", "threshold": 80},
                        "message": "c",
                    },
                ],
            }
        )
        fields = {"val": 99.0}
        alerts = build_schema_alerts(s, fields)
        ids = {a["id"] for a in alerts}
        assert "a" in ids
        assert "b" in ids
        assert "c" not in ids


# ---------------------------------------------------------------------------
# Pipe transforms
# ---------------------------------------------------------------------------


class TestPipeTransforms:
    def test_join_lines(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"lines": ["hello", "world"]}
        result = resolve_field("lines | join_lines", data)
        assert result == "hello\nworld"

    def test_regex_extract(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"text": "3 upgraded, 0 newly installed, 0 to remove"}
        result = resolve_field("text | regex_extract('(\\d+) upgraded')", data)
        assert result == "3"

    def test_regex_extract_no_match(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"text": "no upgrades"}
        result = resolve_field("text | regex_extract('(\\d+) upgraded')", data)
        assert result == ""

    def test_parse_kv(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"lines": ["PermitRootLogin no", "# comment", "PasswordAuth yes # inline comment", ""]}
        result = resolve_field("lines | parse_kv(' ', '#')", data)
        assert result == {"PermitRootLogin": "no", "PasswordAuth": "yes"}

    def test_chained_transforms(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"lines": ["0 upgraded, 0 newly installed"]}
        result = resolve_field("lines | join_lines | regex_extract('(\\d+) upgraded')", data)
        assert result == "0"

    def test_keys_transform(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"d": {"a": 1, "b": 2}}
        result = resolve_field("d | keys", data)
        assert sorted(result) == ["a", "b"]

    def test_flatten_transform(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"nested": [[1, 2], [3, 4]]}
        result = resolve_field("nested | flatten", data)
        assert result == [1, 2, 3, 4]

    def test_round_transform(self) -> None:
        from ncs_reporter.normalization.schema_driven import resolve_field

        data = {"val": 3.14159}
        result = resolve_field("val | round(2)", data)
        assert result == 3.14


# ---------------------------------------------------------------------------
# $include for field groups
# ---------------------------------------------------------------------------


class TestFieldInclude:
    def test_include_merges_fields(self, tmp_path: Path) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        # Write base fields file
        base_fields = tmp_path / "base_fields.yaml"
        base_fields.write_text("hostname:\n  path: raw.hostname\n  fallback: unknown\nkernel:\n  path: raw.kernel\n")

        # Write schema that includes it
        schema_file = tmp_path / "test.yaml"
        schema_file.write_text(
            'name: test\ndetection:\n  keys_any: [raw]\nfields:\n  $include: "base_fields.yaml"\n  extra:\n    path: raw.extra\n'
        )

        s = load_schema_from_file(schema_file)
        assert "hostname" in s.fields
        assert "kernel" in s.fields
        assert "extra" in s.fields

    def test_include_local_overrides_base(self, tmp_path: Path) -> None:
        from ncs_reporter.schema_loader import load_schema_from_file

        base_fields = tmp_path / "base.yaml"
        base_fields.write_text('hostname:\n  path: base.hostname\n  fallback: "base"\n')

        schema_file = tmp_path / "test.yaml"
        schema_file.write_text(
            'name: test\ndetection:\n  keys_any: [raw]\nfields:\n  $include: "base.yaml"\n  hostname:\n    path: override.hostname\n    fallback: "override"\n'
        )

        s = load_schema_from_file(schema_file)
        assert s.fields["hostname"].path == "override.hostname"
        assert s.fields["hostname"].fallback == "override"


# ---------------------------------------------------------------------------
# New widget types
# ---------------------------------------------------------------------------


class TestNewWidgetModels:
    def test_stat_cards_widget(self) -> None:
        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"vm_count": {"path": "raw.count", "type": "int"}},
                "widgets": [
                    {
                        "id": "kpis",
                        "type": "stat_cards",
                        "title": "KPIs",
                        "cards": [{"field": "vm_count", "label": "VMs"}],
                    }
                ],
            }
        )
        assert s.widgets[0].type == "stat_cards"  # type: ignore[union-attr]

    def test_bar_chart_widget(self) -> None:
        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"datastores": {"path": "raw.ds", "type": "list"}},
                "widgets": [
                    {
                        "id": "cap",
                        "type": "bar_chart",
                        "title": "Capacity",
                        "rows_field": "datastores",
                        "label_field": "name",
                        "value_field": "used_pct",
                    }
                ],
            }
        )
        assert s.widgets[0].type == "bar_chart"  # type: ignore[union-attr]

    def test_list_widget(self) -> None:
        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"items": {"path": "raw.items", "type": "list"}},
                "widgets": [
                    {
                        "id": "svcs",
                        "type": "list",
                        "title": "Failed Services",
                        "items_field": "items",
                        "style": "numbered",
                    }
                ],
            }
        )
        assert s.widgets[0].type == "list"  # type: ignore[union-attr]

    def test_grouped_table_widget(self) -> None:
        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"vms": {"path": "raw.vms", "type": "list"}},
                "widgets": [
                    {
                        "id": "vms",
                        "type": "grouped_table",
                        "title": "VMs",
                        "rows_field": "vms",
                        "group_by": "cluster",
                        "columns": [{"label": "Name", "field": "name"}],
                    }
                ],
            }
        )
        assert s.widgets[0].type == "grouped_table"  # type: ignore[union-attr]

    def test_cross_ref_stat_cards(self) -> None:
        with pytest.raises(Exception, match="stat_cards references undeclared field"):
            ReportSchema.model_validate(
                {
                    "name": "test",
                    "detection": {"keys_any": ["raw"]},
                    "fields": {},
                    "widgets": [
                        {
                            "id": "kpis",
                            "type": "stat_cards",
                            "title": "KPIs",
                            "cards": [{"field": "nonexistent", "label": "X"}],
                        }
                    ],
                }
            )

    def test_cross_ref_bar_chart(self) -> None:
        with pytest.raises(Exception, match="bar_chart rows_field references undeclared field"):
            ReportSchema.model_validate(
                {
                    "name": "test",
                    "detection": {"keys_any": ["raw"]},
                    "fields": {},
                    "widgets": [
                        {
                            "id": "cap",
                            "type": "bar_chart",
                            "title": "Cap",
                            "rows_field": "nonexistent",
                            "label_field": "x",
                            "value_field": "y",
                        }
                    ],
                }
            )


# ---------------------------------------------------------------------------
# visible_if
# ---------------------------------------------------------------------------


class TestVisibleIf:
    def test_visible_if_hides_widget(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"count": {"path": "raw.count", "type": "int"}},
                "widgets": [
                    {
                        "id": "kv",
                        "type": "key_value",
                        "title": "Test",
                        "visible_if": {"op": "gt", "field": "count", "threshold": 0},
                        "fields": [{"label": "Count", "field": "count"}],
                    }
                ],
            }
        )
        # count = 0 → condition false → widget hidden
        result = _render_widget(s.widgets[0], {"count": 0}, [])
        assert result is None

    def test_visible_if_shows_widget(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"count": {"path": "raw.count", "type": "int"}},
                "widgets": [
                    {
                        "id": "kv",
                        "type": "key_value",
                        "title": "Test",
                        "visible_if": {"op": "gt", "field": "count", "threshold": 0},
                        "fields": [{"label": "Count", "field": "count"}],
                    }
                ],
            }
        )
        # count = 5 → condition true → widget shown
        result = _render_widget(s.widgets[0], {"count": 5}, [])
        assert result is not None
        assert result["id"] == "kv"

    def test_no_visible_if_always_shows(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"count": {"path": "raw.count", "type": "int"}},
                "widgets": [
                    {
                        "id": "kv",
                        "type": "key_value",
                        "title": "Test",
                        "fields": [{"label": "Count", "field": "count"}],
                    }
                ],
            }
        )
        result = _render_widget(s.widgets[0], {"count": 0}, [])
        assert result is not None


# ---------------------------------------------------------------------------
# Widget rendering
# ---------------------------------------------------------------------------


class TestWidgetRendering:
    def test_stat_cards_rendering(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"count": {"path": "raw.c", "type": "int"}},
                "widgets": [
                    {
                        "id": "kpis",
                        "type": "stat_cards",
                        "title": "KPIs",
                        "cards": [
                            {"field": "count", "label": "Total"},
                            {"field": "count", "label": "Fmt", "format": "{value} items"},
                            {"field": "count", "label": "Thresh", "thresholds": {5: "yellow", 10: "red"}},
                        ],
                    }
                ],
            }
        )
        result = _render_widget(s.widgets[0], {"count": 7}, [])
        assert result is not None
        assert result["type"] == "stat_cards"
        assert len(result["cards"]) == 3
        assert result["cards"][0]["value"] == "7"
        assert result["cards"][1]["value"] == "7 items"
        assert result["cards"][2]["color"] == "yellow"  # 7 >= 5 but < 10

    def test_bar_chart_rendering(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"ds": {"path": "raw.ds", "type": "list"}},
                "widgets": [
                    {
                        "id": "cap",
                        "type": "bar_chart",
                        "title": "Capacity",
                        "rows_field": "ds",
                        "label_field": "name",
                        "value_field": "used",
                        "max": 100,
                        "thresholds": {75: "yellow", 90: "red"},
                    }
                ],
            }
        )
        result = _render_widget(
            s.widgets[0], {"ds": [{"name": "ds1", "used": 80}, {"name": "ds2", "used": 95}]}, []
        )
        assert result is not None
        assert result["type"] == "bar_chart"
        assert len(result["bars"]) == 2
        assert result["bars"][0]["color"] == "yellow"
        assert result["bars"][1]["color"] == "red"
        assert result["bars"][0]["width_pct"] == 80.0

    def test_list_rendering_bullet(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"items": {"path": "raw.items", "type": "list"}},
                "widgets": [
                    {
                        "id": "lst",
                        "type": "list",
                        "title": "Items",
                        "items_field": "items",
                    }
                ],
            }
        )
        result = _render_widget(s.widgets[0], {"items": ["a", "b", "c"]}, [])
        assert result is not None
        assert result["type"] == "list"
        assert result["items"] == ["a", "b", "c"]
        assert result["style"] == "bullet"

    def test_list_rendering_display_field(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"items": {"path": "raw.items", "type": "list"}},
                "widgets": [
                    {
                        "id": "lst",
                        "type": "list",
                        "title": "Items",
                        "items_field": "items",
                        "display_field": "name",
                    }
                ],
            }
        )
        result = _render_widget(s.widgets[0], {"items": [{"name": "svc1"}, {"name": "svc2"}]}, [])
        assert result is not None
        assert result["items"] == ["svc1", "svc2"]

    def test_list_rendering_empty(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"items": {"path": "raw.items", "type": "list"}},
                "widgets": [
                    {
                        "id": "lst",
                        "type": "list",
                        "title": "Items",
                        "items_field": "items",
                        "empty_text": "No items found",
                    }
                ],
            }
        )
        result = _render_widget(s.widgets[0], {"items": []}, [])
        assert result is not None
        assert result["items"] == []
        assert result["empty_text"] == "No items found"

    def test_grouped_table_rendering(self) -> None:
        from ncs_reporter.view_models.generic import _render_widget

        s = ReportSchema.model_validate(
            {
                "name": "test",
                "detection": {"keys_any": ["raw"]},
                "fields": {"vms": {"path": "raw.vms", "type": "list"}},
                "widgets": [
                    {
                        "id": "vms",
                        "type": "grouped_table",
                        "title": "VMs",
                        "rows_field": "vms",
                        "group_by": "cluster",
                        "columns": [
                            {"label": "Name", "field": "name"},
                            {"label": "Power", "field": "power", "badge": True},
                        ],
                    }
                ],
            }
        )
        vms = [
            {"name": "vm1", "power": "on", "cluster": "A"},
            {"name": "vm2", "power": "off", "cluster": "B"},
            {"name": "vm3", "power": "on", "cluster": "A"},
        ]
        result = _render_widget(s.widgets[0], {"vms": vms}, [])
        assert result is not None
        assert result["type"] == "grouped_table"
        assert list(result["groups"].keys()) == ["A", "B"]
        assert len(result["groups"]["A"]) == 2
        assert len(result["groups"]["B"]) == 1
