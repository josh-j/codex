import importlib.util
import pathlib
import unittest
from typing import Any

FILTER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "alerts.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_alerts_filter", FILTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreAlertsLogicTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_build_alerts_handles_truthy_variations(self):
        checks = [
            {"condition": True, "message": "Bool True", "severity": "CRITICAL"},
            {"condition": "yes", "message": "String yes", "severity": "WARNING"},
            {"condition": "1", "message": "String 1", "severity": "INFO"},
            {"condition": 1, "message": "Int 1"},
            {"condition": False, "message": "Bool False"},
            {"condition": "no", "message": "String no"},
        ]
        alerts = self.module.build_alerts(checks)
        self.assertEqual(len(alerts), 4)
        self.assertEqual(alerts[0]["message"], "Bool True")
        self.assertEqual(alerts[1]["severity"], "WARNING")

    def test_build_alerts_preserves_extra_keys(self):
        checks = [
            {
                "condition": True, 
                "message": "Extra keys", 
                "affected_items": ["item1"], 
                "remediation": "Fix it"
            }
        ]
        alerts = self.module.build_alerts(checks)
        self.assertEqual(alerts[0]["affected_items"], ["item1"])
        self.assertEqual(alerts[0]["remediation"], "Fix it")

    def test_threshold_alert_logic(self):
        # Fire Critical
        alert = self.module.threshold_alert(95, "capacity", "High Load", 90, 80)
        self.assertEqual(alert[0]["severity"], "CRITICAL")
        
        # Fire Warning
        alert = self.module.threshold_alert(85, "capacity", "Med Load", 90, 80)
        self.assertEqual(alert[0]["severity"], "WARNING")
        
        # Fire None
        alert = self.module.threshold_alert(75, "capacity", "Low Load", 90, 80)
        self.assertEqual(len(alert), 0)

    def test_health_rollup_priority(self):
        self.assertEqual(self.module.health_rollup([{"severity": "CRITICAL"}]), "CRITICAL")
        self.assertEqual(self.module.health_rollup([{"severity": "WARNING"}]), "WARNING")
        self.assertEqual(self.module.health_rollup([{"severity": "INFO"}]), "HEALTHY")
        self.assertEqual(self.module.health_rollup([]), "HEALTHY")
        
        # Mixed
        self.assertEqual(
            self.module.health_rollup([{"severity": "WARNING"}, {"severity": "CRITICAL"}]), 
            "CRITICAL"
        )


class ComputeAuditRollupsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_empty_alerts_returns_healthy(self):
        out = self.module.compute_audit_rollups([])
        self.assertEqual(out["health"], "HEALTHY")
        self.assertEqual(out["summary"]["total"], 0)
        self.assertEqual(out["summary"]["critical_count"], 0)

    def test_mixed_alerts_returns_critical_with_correct_counts(self):
        alerts = [
            {"severity": "warning", "category": "capacity"},
            {"severity": "CRITICAL", "category": "capacity"},
            {"severity": "INFO", "category": "inventory"},
        ]
        out = self.module.compute_audit_rollups(alerts)
        self.assertEqual(out["health"], "CRITICAL")
        self.assertEqual(out["summary"]["total"], 3)
        self.assertEqual(out["summary"]["critical_count"], 1)
        self.assertEqual(out["summary"]["warning_count"], 1)
        self.assertEqual(out["summary"]["info_count"], 1)
        self.assertEqual(out["summary"]["by_category"]["capacity"], 2)
        self.assertEqual(out["summary"]["by_category"]["inventory"], 1)

    def test_warning_only_returns_warning(self):
        alerts = [{"severity": "WARNING", "category": "test"}]
        out = self.module.compute_audit_rollups(alerts)
        self.assertEqual(out["health"], "WARNING")

    def test_none_input_returns_healthy(self):
        out = self.module.compute_audit_rollups(None)
        self.assertEqual(out["health"], "HEALTHY")
        self.assertEqual(out["summary"]["total"], 0)


class AppendAlertsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_append_list(self):
        result = self.module.append_alerts([{"m": 1}], [{"m": 2}, {"m": 3}])
        self.assertEqual(result, [{"m": 1}, {"m": 2}, {"m": 3}])

    def test_append_none(self):
        result = self.module.append_alerts([{"m": 1}], None)
        self.assertEqual(result, [{"m": 1}])

    def test_append_single_dict(self):
        result = self.module.append_alerts([{"m": 1}], {"m": 2})
        self.assertEqual(result, [{"m": 1}, {"m": 2}])

    def test_append_to_none_existing(self):
        result = self.module.append_alerts(None, [{"m": 1}])
        self.assertEqual(result, [{"m": 1}])

    def test_does_not_mutate_input(self):
        existing = [{"m": 1}]
        self.module.append_alerts(existing, [{"m": 2}])
        self.assertEqual(existing, [{"m": 1}])


if __name__ == "__main__":
    unittest.main()
