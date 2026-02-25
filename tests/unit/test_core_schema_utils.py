import importlib.util
import os
import pathlib
import unittest
from typing import Any

UTIL_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "module_utils"
    / "schema_utils.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_schema_utils", UTIL_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreSchemaUtilsTests(unittest.TestCase):
    module: Any
    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_resolve_schema_path_plain_file(self):
        # Create a temp file
        path = "/tmp/plain_schema.yaml"
        pathlib.Path(path).touch()
        try:
            resolved = self.module.resolve_schema_path(path)
            self.assertEqual(resolved, path)
        finally:
            os.remove(path)

    def test_resolve_schema_path_collection_ref(self):
        # Test internal.linux:schemas/ubuntu_ctx.yaml
        ref = "internal.linux:schemas/ubuntu_ctx.yaml"
        resolved = self.module.resolve_schema_path(ref)
        self.assertIsNotNone(resolved)
        self.assertTrue(resolved.endswith("internal/linux/schemas/ubuntu_ctx.yaml"))
        self.assertTrue(os.path.isfile(resolved))

    def test_resolve_schema_path_role_ref(self):
        # Test internal.windows:roles/windows_audit/defaults/context_init_schema.yaml
        ref = "internal.windows:roles/windows_audit/defaults/context_init_schema.yaml"
        resolved = self.module.resolve_schema_path(ref)
        self.assertIsNotNone(resolved)
        self.assertTrue("windows_audit/defaults" in resolved)
        self.assertTrue(os.path.isfile(resolved))

    def test_resolve_schema_path_invalid_ref(self):
        self.assertIsNone(self.module.resolve_schema_path(None))
        self.assertIsNone(self.module.resolve_schema_path(""))
        self.assertIsNone(self.module.resolve_schema_path("invalid:ref:format"))


if __name__ == "__main__":
    unittest.main()
