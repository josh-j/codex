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


class TypesCompatibleTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_dict_match(self):
        self.assertTrue(self.module._types_compatible({"a": 1}, {"b": 2}))

    def test_dict_mismatch(self):
        self.assertFalse(self.module._types_compatible("string", {"b": 2}))

    def test_list_match(self):
        self.assertTrue(self.module._types_compatible([1], [2]))

    def test_list_mismatch(self):
        self.assertFalse(self.module._types_compatible("string", [2]))

    def test_bool_match(self):
        self.assertTrue(self.module._types_compatible(True, False))

    def test_bool_rejects_int(self):
        self.assertFalse(self.module._types_compatible(1, False))

    def test_int_match(self):
        self.assertTrue(self.module._types_compatible(42, 0))

    def test_int_rejects_bool(self):
        self.assertFalse(self.module._types_compatible(True, 0))

    def test_float_match(self):
        self.assertTrue(self.module._types_compatible(3.14, 0.0))

    def test_float_accepts_int(self):
        self.assertTrue(self.module._types_compatible(42, 0.0))

    def test_float_rejects_bool(self):
        self.assertFalse(self.module._types_compatible(True, 0.0))

    def test_str_match(self):
        self.assertTrue(self.module._types_compatible("hello", ""))

    def test_str_mismatch(self):
        self.assertFalse(self.module._types_compatible(42, ""))

    def test_none_template_accepts_anything(self):
        self.assertTrue(self.module._types_compatible("anything", None))
        self.assertTrue(self.module._types_compatible(42, None))


class FindTypeMismatchesTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_matching_types_no_errors(self):
        data = {"name": "test", "count": 5, "active": True}
        template = {"name": "", "count": 0, "active": False}
        errors = self.module._find_type_mismatches(data, template)
        self.assertEqual(errors, [])

    def test_type_mismatch_detected(self):
        data = {"count": "not_a_number"}
        template = {"count": 0}
        errors = self.module._find_type_mismatches(data, template)
        self.assertEqual(len(errors), 1)
        self.assertIn("count", errors[0])

    def test_nested_mismatch_reports_path(self):
        data = {"system": {"uptime": "bad"}}
        template = {"system": {"uptime": 0}}
        errors = self.module._find_type_mismatches(data, template)
        self.assertIn("system.uptime", errors[0])

    def test_missing_keys_skipped(self):
        data: dict[str, Any] = {}
        template = {"name": ""}
        errors = self.module._find_type_mismatches(data, template)
        self.assertEqual(errors, [])

    def test_non_dict_where_dict_expected(self):
        errors = self.module._find_type_mismatches("not_dict", {"key": ""})
        self.assertEqual(len(errors), 1)

    def test_bool_int_distinction(self):
        data = {"flag": 1}
        template = {"flag": False}
        errors = self.module._find_type_mismatches(data, template)
        self.assertEqual(len(errors), 1)


class FindMissingKeysTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_no_missing_keys(self):
        data = {"a": 1, "b": {"c": 2}}
        template = {"a": 0, "b": {"c": 0}}
        missing = self.module._find_missing_keys(data, template)
        self.assertEqual(missing, [])

    def test_missing_top_level_key(self):
        data = {"a": 1}
        template = {"a": 0, "b": 0}
        missing = self.module._find_missing_keys(data, template)
        self.assertIn("b", missing)

    def test_missing_nested_key(self):
        data: dict[str, Any] = {"system": {}}
        template = {"system": {"hostname": ""}}
        missing = self.module._find_missing_keys(data, template)
        self.assertIn("system.hostname", missing)

    def test_non_dict_data(self):
        missing = self.module._find_missing_keys("string", {"key": ""})
        self.assertEqual(len(missing), 1)


class ValidateSchemaFromFileTests(unittest.TestCase):
    module: Any
    AnsibleFilterError: type

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        from ansible.errors import AnsibleFilterError
        cls.AnsibleFilterError = AnsibleFilterError

    def _write_schema(self, content, path="/tmp/test_validation_schema.yaml"):
        with open(path, "w") as f:
            yaml.dump(content, f)
        return path

    def test_valid_data_passes(self):
        path = self._write_schema({"test_ctx": {"name": "", "count": 0}})
        try:
            result = self.module.validate_schema_from_file(
                {"name": "hello", "count": 5}, path, "test_ctx"
            )
            self.assertTrue(result)
        finally:
            os.remove(path)

    def test_missing_key_raises(self):
        path = self._write_schema({"test_ctx": {"name": "", "count": 0}})
        try:
            with self.assertRaises(self.AnsibleFilterError):
                self.module.validate_schema_from_file({"name": "hello"}, path, "test_ctx")
        finally:
            os.remove(path)

    def test_missing_file_raises(self):
        with self.assertRaises(self.AnsibleFilterError):
            self.module.validate_schema_from_file({}, "/tmp/nonexistent_schema.yaml", "x")

    def test_wrong_root_key_raises(self):
        path = self._write_schema({"other_ctx": {"a": 1}})
        try:
            with self.assertRaises(self.AnsibleFilterError):
                self.module.validate_schema_from_file({}, path, "test_ctx")
        finally:
            os.remove(path)


class ValidateTypedSchemaFromFileTests(unittest.TestCase):
    module: Any
    AnsibleFilterError: type

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()
        from ansible.errors import AnsibleFilterError
        cls.AnsibleFilterError = AnsibleFilterError

    def _write_schema(self, content, path="/tmp/test_typed_schema.yaml"):
        with open(path, "w") as f:
            yaml.dump(content, f)
        return path

    def test_valid_types_pass(self):
        path = self._write_schema({"ctx": {"name": "default", "count": 0, "active": False}})
        try:
            result = self.module.validate_typed_schema_from_file(
                {"name": "test", "count": 5, "active": True}, path, "ctx"
            )
            self.assertTrue(result)
        finally:
            os.remove(path)

    def test_type_mismatch_raises(self):
        path = self._write_schema({"ctx": {"count": 0}})
        try:
            cm: Any
            with self.assertRaises(self.AnsibleFilterError) as cm:
                self.module.validate_typed_schema_from_file({"count": "not_int"}, path, "ctx")
            self.assertIn("Type validation failed", str(cm.exception))
        finally:
            os.remove(path)

    def test_missing_key_raises_before_type_check(self):
        path = self._write_schema({"ctx": {"a": 0, "b": ""}})
        try:
            cm: Any
            with self.assertRaises(self.AnsibleFilterError) as cm:
                self.module.validate_typed_schema_from_file({"a": 1}, path, "ctx")
            self.assertIn("Missing required keys", str(cm.exception))
        finally:
            os.remove(path)


class ToSkeletonTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_zeroes_scalar_types(self):
        template = {"s": "hello", "i": 42, "f": 3.14, "b": True}
        out = self.module._to_skeleton(template)
        self.assertEqual(out, {"s": "", "i": 0, "f": 0.0, "b": False})

    def test_empties_list(self):
        self.assertEqual(self.module._to_skeleton([1, 2, 3]), [])

    def test_recurses_into_dicts(self):
        template = {"nested": {"value": 10}}
        out = self.module._to_skeleton(template)
        self.assertEqual(out, {"nested": {"value": 0}})

    def test_none_returns_none(self):
        self.assertIsNone(self.module._to_skeleton(None))


class TypeNameTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls):
        cls.module = _load_module()

    def test_all_types(self):
        self.assertEqual(self.module._type_name(True), "bool")
        self.assertEqual(self.module._type_name(42), "int")
        self.assertEqual(self.module._type_name(3.14), "float")
        self.assertEqual(self.module._type_name("hi"), "str")
        self.assertEqual(self.module._type_name({}), "dict")
        self.assertEqual(self.module._type_name([]), "list")
        self.assertEqual(self.module._type_name(None), "null")


if __name__ == "__main__":
    unittest.main()
