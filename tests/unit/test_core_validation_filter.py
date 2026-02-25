import importlib.util
import os
import pathlib
import unittest
from typing import Any

import yaml

FILTER_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "core"
    / "plugins"
    / "filter"
    / "validation.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("core_validation_filter", FILTER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreValidationFilterTests(unittest.TestCase):
    module: Any
    AnsibleFilterError: type

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        from ansible.errors import AnsibleFilterError
        cls.AnsibleFilterError = AnsibleFilterError

    def test_schema_to_skeleton_creates_zeroed_structure(self):
        # Create a temporary schema file
        schema_content = {
            "test_ctx": {
                "system": {
                    "hostname": "default",
                    "uptime": 10,
                    "load": 0.5,
                    "is_up": True
                },
                "list_data": ["item1", "item2"],
                "empty_dict": {}
            }
        }
        schema_path = "/tmp/test_schema.yaml"
        with open(schema_path, "w") as f:
            yaml.dump(schema_content, f)

        try:
            skeleton = self.module.schema_to_skeleton(schema_path, "test_ctx")
            
            expected = {
                "system": {
                    "hostname": "",
                    "uptime": 0,
                    "load": 0.0,
                    "is_up": False
                },
                "list_data": [],
                "empty_dict": {}
            }
            self.assertEqual(skeleton, expected)
            self.assertIsInstance(skeleton["system"]["load"], float)
            self.assertIsInstance(skeleton["system"]["uptime"], int)
            self.assertIsInstance(skeleton["system"]["is_up"], bool)
        finally:
            if os.path.exists(schema_path):
                os.remove(schema_path)

    def test_schema_to_skeleton_missing_root_key(self):
        schema_path = "/tmp/test_schema_missing.yaml"
        with open(schema_path, "w") as f:
            yaml.dump({"wrong_key": {}}, f)
        
        try:
            with self.assertRaises(self.AnsibleFilterError):
                self.module.schema_to_skeleton(schema_path, "test_ctx")
        finally:
            os.remove(schema_path)

    def test_schema_to_skeleton_invalid_file(self):
        with self.assertRaises(self.AnsibleFilterError):
            self.module.schema_to_skeleton("/tmp/non_existent_file.yaml", "any")


if __name__ == "__main__":
    unittest.main()
