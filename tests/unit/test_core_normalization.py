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
    / "normalization.py"
)


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("core_normalization", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CoreNormalizationTests(unittest.TestCase):
    module: Any

    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_module()

    def test_result_envelope(self) -> None:
        result_envelope = self.module.result_envelope
        payload = {"data": 1}
        env = result_envelope(payload, collected_at="now")
        self.assertEqual(env["data"], 1)
        self.assertEqual(env["status"], "SUCCESS")
        self.assertEqual(env["collected_at"], "now")

        env_fail = result_envelope({}, failed=True, error="bad", status="ERROR")
        self.assertEqual(env_fail["status"], "ERROR")
        self.assertEqual(env_fail["error"], "bad")

    def test_section_defaults(self) -> None:
        section_defaults = self.module.section_defaults
        defaults = section_defaults("now")
        self.assertEqual(defaults["status"], "NOT_RUN")
        self.assertEqual(defaults["collected_at"], "now")

    def test_merge_section_defaults(self) -> None:
        merge_section_defaults = self.module.merge_section_defaults
        section = {"status": "SUCCESS", "data": 1}
        payload = {"data": 2, "extra": 3}
        merged = merge_section_defaults(section, payload, "now")
        self.assertEqual(merged["data"], 2)
        self.assertEqual(merged["status"], "SUCCESS")
        self.assertEqual(merged["extra"], 3)
        self.assertEqual(merged["collected_at"], "now")

        empty_merged = merge_section_defaults(None, None)
        self.assertEqual(empty_merged["status"], "NOT_RUN")

    def test_parse_json_command_result(self) -> None:
        parse_json_command_result = self.module.parse_json_command_result
        # Clean JSON
        res = {"rc": 0, "stdout": '{"foo": "bar"}', "stderr": ""}
        parsed = parse_json_command_result(res)
        self.assertEqual(parsed["payload"], {"foo": "bar"})
        self.assertTrue(parsed["script_valid"])

        # JSON with noise
        res_noise = {"rc": 0, "stdout": "Login banner\n{\"foo\": \"baz\"}\nFooter", "stderr": ""}
        parsed_noise = parse_json_command_result(res_noise)
        self.assertEqual(parsed_noise["payload"], {"foo": "baz"})

        # Invalid JSON
        res_invalid = {"rc": 0, "stdout": "Not JSON", "stderr": "error"}
        parsed_invalid = parse_json_command_result(res_invalid)
        self.assertIsNone(parsed_invalid["payload"])
        self.assertFalse(parsed_invalid["script_valid"])

        # Non-object JSON
        res_list = {"rc": 0, "stdout": "[1, 2, 3]", "stderr": ""}
        parsed_list = parse_json_command_result(res_list, object_only=True)
        self.assertIsNone(parsed_list["payload"])

        parsed_list_ok = parse_json_command_result(res_list, object_only=False)
        self.assertEqual(parsed_list_ok["payload"], [1, 2, 3])

        # Failed RC
        res_fail = {"rc": 1, "stdout": '{"foo": "bar"}', "stderr": "some error"}
        parsed_fail = parse_json_command_result(res_fail)
        self.assertEqual(parsed_fail["payload"], {"foo": "bar"})
        self.assertFalse(parsed_fail["script_valid"])

    def test_parse_json_command_result_empty_and_invalid(self) -> None:
        parse_json_command_result = self.module.parse_json_command_result
        # Empty stdout
        self.assertIsNone(parse_json_command_result({"stdout": ""})["payload"])
        # Invalid JSON in brackets
        self.assertIsNone(parse_json_command_result({"stdout": "{not json}"})["payload"])


if __name__ == "__main__":
    unittest.main()
