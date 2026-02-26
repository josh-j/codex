import importlib.util
import pathlib
import unittest
from typing import Any

MODULE_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "date_utils.py"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("core_date_utils", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreDateUtilsTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_parse_iso_epoch(self) -> None:
        parse_iso_epoch = self.module.parse_iso_epoch
        # Standard ISO
        self.assertIsNotNone(parse_iso_epoch("2026-02-24T12:00:00Z"))
        self.assertIsNotNone(parse_iso_epoch("2026-02-24 12:00:00"))

        # With milliseconds
        self.assertIsNotNone(parse_iso_epoch("2026-02-24T12:00:00.123Z"))

        # Fallback format (e.g. from some older tools)
        self.assertIsNotNone(parse_iso_epoch("2026-02-24T12:00:00"))
        # Trigger regex fallback with trailing noise
        self.assertIsNotNone(parse_iso_epoch("2026-02-24T12:00:00 noise"))

        # Invalid
        self.assertIsNone(parse_iso_epoch("not a date"))
        self.assertIsNone(parse_iso_epoch(None))
        self.assertIsNone(parse_iso_epoch(123))
        # Valid date but unparseable by regex or fromisoformat
        self.assertIsNone(parse_iso_epoch("2026/02/24"))

    def test_safe_iso_to_epoch(self) -> None:
        safe_iso_to_epoch = self.module.safe_iso_to_epoch
        self.assertGreater(safe_iso_to_epoch("2026-02-24T12:00:00Z"), 0)
        self.assertEqual(safe_iso_to_epoch("invalid", default=123), 123)
        self.assertEqual(safe_iso_to_epoch(None, default=456), 456)


if __name__ == "__main__":
    unittest.main()
