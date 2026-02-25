import importlib.util
import pathlib
import tempfile
import unittest
import unittest.mock
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "report_aggregation.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_report_aggregation", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreReportAggregationTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        try:
            cls.module = _load_module()
        except ModuleNotFoundError as exc:
            if exc.name == "yaml":
                raise unittest.SkipTest("PyYAML not installed in local test runtime") from exc
            raise

    def test_load_all_reports_skips_windows_platform_container_and_windows_fleet_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = pathlib.Path(tmpdir)

            # Platform container / fleet state should be ignored as host entries.
            (root / "windows").mkdir(parents=True, exist_ok=True)
            (root / "windows_fleet_state.yaml").write_text("metadata:\n  host: ignored\n", encoding="utf-8")

            # Real host data under platform/windows/<host>/ should still be discovered.
            host_dir = root / "platform" / "windows" / "win01"
            host_dir.mkdir(parents=True, exist_ok=True)
            (host_dir / "windows_audit.yaml").write_text(
                "\n".join(
                    [
                        "metadata:",
                        "  host: win01",
                        "  audit_type: windows_audit",
                        "health: WARNING",
                        "summary:",
                        "  critical_count: 0",
                        "  warning_count: 1",
                        "alerts:",
                        "  - severity: WARNING",
                        "    message: test",
                        "data:",
                        "  audit_type: windows_audit",
                        "  health: WARNING",
                        "  summary:",
                        "    critical_count: 0",
                        "    warning_count: 1",
                    ]
                ),
                encoding="utf-8",
            )

            out = self.module.load_all_reports(str(root))

            self.assertIn("win01", out["hosts"])
            # Reports are deep-merged flat into the host dict (not nested under audit_type)
            self.assertEqual(out["hosts"]["win01"]["audit_type"], "windows_audit")
            self.assertEqual(out["hosts"]["win01"]["health"], "WARNING")
            self.assertNotIn("windows", out["hosts"])
            self.assertEqual(out["metadata"]["fleet_stats"]["total_hosts"], 1)


if __name__ == "__main__":
    unittest.main()
