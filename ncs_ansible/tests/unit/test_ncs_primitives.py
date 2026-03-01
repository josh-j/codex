import pathlib
import sys
import unittest

_NCS_SRC = str(pathlib.Path(__file__).resolve().parents[2] / "tools" / "ncs_reporter" / "src")
if _NCS_SRC not in sys.path:
    sys.path.insert(0, _NCS_SRC)

from ncs_reporter.primitives import (  # noqa: E402
    build_alert,
    build_count_alert,
    build_threshold_alert,
    canonical_severity,
    normalize_detail,
    safe_list,
    threshold_severity,
    to_float,
    to_int,
)


class NcsPrimitivesTests(unittest.TestCase):
    def test_safe_list(self):
        self.assertEqual(safe_list([1, 2]), [1, 2])
        self.assertEqual(safe_list(None), [])
        self.assertEqual(safe_list("string"), [])
        self.assertEqual(safe_list({"a": 1}), ["a"])

    def test_to_int(self):
        self.assertEqual(to_int(10), 10)
        self.assertEqual(to_int("10"), 10)
        self.assertEqual(to_int("abc", 5), 5)
        self.assertEqual(to_int(None, 0), 0)

    def test_to_float(self):
        self.assertEqual(to_float(10.5), 10.5)
        self.assertEqual(to_float("10.5"), 10.5)
        self.assertEqual(to_float("abc", 5.5), 5.5)
        self.assertEqual(to_float(None, 0.0), 0.0)

    def test_normalize_detail(self):
        self.assertEqual(normalize_detail({"a": 1}), {"a": 1})
        self.assertEqual(normalize_detail(None), {})
        self.assertEqual(normalize_detail("string"), {"value": "string"})
        self.assertEqual(normalize_detail(123), {"value": 123})

    def test_build_alert(self):
        alert = build_alert("CRITICAL", "disk", "Disk Full", detail="High usage", extra_key="foo")
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertEqual(alert["category"], "disk")
        self.assertEqual(alert["message"], "Disk Full")
        self.assertEqual(alert["detail"], {"value": "High usage"})
        self.assertEqual(alert["extra_key"], "foo")

        alert = build_alert("WARNING", "cpu", "High CPU", affected_items=["host1"])
        self.assertEqual(alert["affected_items"], ["host1"])

    def test_canonical_severity(self):
        self.assertEqual(canonical_severity("critical"), "CRITICAL")
        self.assertEqual(canonical_severity("CAT_I"), "CRITICAL")
        self.assertEqual(canonical_severity("warn"), "WARNING")
        self.assertEqual(canonical_severity("info"), "INFO")
        self.assertEqual(canonical_severity(None), "INFO")

    def test_threshold_severity(self):
        self.assertEqual(threshold_severity(95, 90, 80), ("CRITICAL", 90.0))
        self.assertEqual(threshold_severity(85, 90, 80), ("WARNING", 80.0))
        self.assertEqual(threshold_severity(75, 90, 80), (None, None))

    def test_build_threshold_alert(self):
        # gt direction (default)
        alert = build_threshold_alert(95, 90, 80, "capacity", "High usage")
        assert alert is not None
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertEqual(alert["detail"]["threshold_pct"], 90.0)
        self.assertEqual(alert["detail"]["usage_pct"], 95.0)

        alert = build_threshold_alert(85, 90, 80, "capacity", "High usage")
        assert alert is not None
        self.assertEqual(alert["severity"], "WARNING")

        alert = build_threshold_alert(75, 90, 80, "capacity", "High usage")
        self.assertIsNone(alert)

        # le direction
        alert = build_threshold_alert(5, 10, 20, "time", "Too fast", direction="le")
        assert alert is not None
        self.assertEqual(alert["severity"], "CRITICAL")

        alert = build_threshold_alert(15, 10, 20, "time", "Fast", direction="le")
        assert alert is not None
        self.assertEqual(alert["severity"], "WARNING")

        alert = build_threshold_alert(25, 10, 20, "time", "Slow", direction="le")
        self.assertIsNone(alert)

    def test_build_count_alert(self):
        alert = build_count_alert(5, "CRITICAL", "errors", "Too many errors")
        assert alert is not None
        self.assertEqual(alert["severity"], "CRITICAL")
        self.assertEqual(alert["detail"]["count"], 5)

        alert = build_count_alert(0, "CRITICAL", "errors", "Too many errors")
        self.assertIsNone(alert)

        alert = build_count_alert(2, "WARNING", "updates", "Updates pending", min_count=1)
        self.assertIsNotNone(alert)


if __name__ == "__main__":
    unittest.main()
