import pathlib
import unittest

# The vmware_ctx schema moved from discovery/defaults/main.yaml to a dedicated schema file.
SCHEMA_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "schemas"
    / "vmware_ctx.yaml"
)

DEFAULTS_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "collections"
    / "ansible_collections"
    / "internal"
    / "vmware"
    / "roles"
    / "discovery"
    / "defaults"
    / "main.yaml"
)


class VmwareDiscoveryDefaultsContractTests(unittest.TestCase):
    def test_discovery_defaults_exist(self):
        self.assertTrue(DEFAULTS_PATH.exists(), f"Discovery defaults not found at {DEFAULTS_PATH}")
        text = DEFAULTS_PATH.read_text(encoding="utf-8")
        self.assertIn("vmware_validate_ctx_schema: true", text)

    def test_vmware_ctx_schema_defines_expected_sections(self):
        text = SCHEMA_PATH.read_text(encoding="utf-8")

        required_snippets = [
            "vmware_ctx:",
            '  audit_type: "vmware_vcenter"',
            "  checks_failed: false",
            "  system:",
            "  health:",
            "    appliance:",
            "    alarms:",
            "  inventory:",
            "    datacenters:",
            "    clusters:",
            "    hosts:",
            "    datastores:",
            "    vms:",
            "    snapshots:",
            "  alerts: []",
        ]

        for snippet in required_snippets:
            self.assertIn(snippet, text, msg=f"Missing schema contract snippet: {snippet}")


if __name__ == "__main__":
    unittest.main()
