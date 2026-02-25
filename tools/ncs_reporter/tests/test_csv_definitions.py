import unittest

from ncs_reporter.csv_definitions import CSV_DEFINITIONS, get_definitions, resolve_data_path


class GetDefinitionsTests(unittest.TestCase):

    def test_returns_windows_definitions(self):
        defs = get_definitions("windows")
        self.assertTrue(len(defs) > 0)
        self.assertTrue(all(d["platform"] == "windows" for d in defs))

    def test_unknown_platform_returns_empty(self):
        defs = get_definitions("solaris")
        self.assertEqual(defs, [])

    def test_definitions_have_required_keys(self):
        for d in CSV_DEFINITIONS:
            self.assertIn("report_name", d)
            self.assertIn("headers", d)
            self.assertIn("data_path", d)
            self.assertIn("platform", d)


class ResolveDataPathTests(unittest.TestCase):

    def test_resolves_nested_path(self):
        bundle = {"a": {"b": {"c": [1, 2, 3]}}}
        result = resolve_data_path(bundle, "a.b.c")
        self.assertEqual(result, [1, 2, 3])

    def test_missing_key_returns_empty_list(self):
        bundle = {"a": {"b": 1}}
        result = resolve_data_path(bundle, "a.c.d")
        self.assertEqual(result, [])

    def test_non_list_leaf_returns_empty_list(self):
        bundle = {"a": {"b": "string"}}
        result = resolve_data_path(bundle, "a.b")
        self.assertEqual(result, [])

    def test_non_dict_intermediate_returns_empty_list(self):
        bundle = {"a": "flat"}
        result = resolve_data_path(bundle, "a.b.c")
        self.assertEqual(result, [])

    def test_empty_bundle(self):
        result = resolve_data_path({}, "a.b")
        self.assertEqual(result, [])


if __name__ == "__main__":
    unittest.main()
