import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

from ncs_reporter.view_models.common import (  # noqa: E402
    _count_alerts,
    _iter_hosts,
    _optional_float,
    _safe_pct,
    _severity_for_pct,
    _status_from_health,
    default_report_skip_keys,
    status_badge_meta,
)


class ReportViewModelCommonTests(unittest.TestCase):
    def test_status_from_health(self):
        self.assertEqual(_status_from_health("green"), "OK")
        self.assertEqual(_status_from_health("healthy"), "OK")
        self.assertEqual(_status_from_health("warning"), "WARNING")
        self.assertEqual(_status_from_health("degraded"), "WARNING")
        self.assertEqual(_status_from_health("critical"), "CRITICAL")
        self.assertEqual(_status_from_health("red"), "CRITICAL")
        self.assertEqual(_status_from_health("unknown"), "UNKNOWN")
        self.assertEqual(_status_from_health(None), "UNKNOWN")
        self.assertEqual(_status_from_health("weird"), "WEIRD")

        # Dict handling
        self.assertEqual(_status_from_health({"health": "green"}), "OK")
        self.assertEqual(_status_from_health({"overall": {"status": "red"}}), "CRITICAL")
        self.assertEqual(_status_from_health({"foo": "bar"}), "UNKNOWN")

    def test_safe_pct(self):
        self.assertEqual(_safe_pct(50, 100), 50.0)
        self.assertEqual(_safe_pct(1, 3), 33.3)
        self.assertEqual(_safe_pct(0, 0), 0.0)
        self.assertEqual(_safe_pct(150, 100), 150.0)

    def test_optional_float(self):
        self.assertEqual(_optional_float(1.5), 1.5)
        self.assertEqual(_optional_float("1.5"), 1.5)
        self.assertEqual(_optional_float(None), None)
        self.assertEqual(_optional_float("abc"), None)

    def test_severity_for_pct(self):
        self.assertEqual(_severity_for_pct(95), "CRITICAL")
        self.assertEqual(_severity_for_pct(88), "WARNING")
        self.assertEqual(_severity_for_pct(50), "OK")
        # Custom thresholds
        self.assertEqual(_severity_for_pct(50, warning=40, critical=60), "WARNING")
        self.assertEqual(_severity_for_pct(70, warning=40, critical=60), "CRITICAL")

    def test_count_alerts(self):
        alerts = [
            {"severity": "CRITICAL"},
            {"severity": "warning"},
            {"severity": "info"},
            "not a dict",
        ]
        counts = _count_alerts(alerts)
        self.assertEqual(counts["critical"], 1)
        self.assertEqual(counts["warning"], 1)
        self.assertEqual(counts["total"], 2)

    def test_iter_hosts(self):
        aggregated = {
            "host1": {"data": 1},
            "host2": {"data": 2},
            "platform": {"ignore": True},  # Should be skipped
            "not_a_dict": "string",  # Should be skipped
        }
        hosts = _iter_hosts(aggregated)
        self.assertEqual(len(hosts), 2)
        self.assertEqual(hosts[0][0], "host1")
        self.assertEqual(hosts[1][0], "host2")

        # Nested hosts key
        aggregated_nested = {"hosts": {"host3": {"data": 3}}}
        hosts = _iter_hosts(aggregated_nested)
        self.assertEqual(len(hosts), 1)
        self.assertEqual(hosts[0][0], "host3")

        self.assertEqual(_iter_hosts(None), [])

    def test_status_badge_meta(self):
        self.assertEqual(status_badge_meta("ok"), {"css_class": "status-ok", "label": "OK"})
        self.assertEqual(status_badge_meta("critical"), {"css_class": "status-fail", "label": "CRITICAL"})
        self.assertEqual(status_badge_meta("warning"), {"css_class": "status-warn", "label": "WARNING"})


    def test_default_report_skip_keys(self):
        keys = default_report_skip_keys()
        self.assertIn("platform", keys)
        self.assertIn("summary", keys)


if __name__ == "__main__":
    unittest.main()
