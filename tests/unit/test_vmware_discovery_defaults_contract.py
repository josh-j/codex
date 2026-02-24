import pathlib
import unittest


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
    def test_vmware_ctx_defaults_still_define_expected_sections(self):
        text = DEFAULTS_PATH.read_text(encoding="utf-8")

        required_snippets = [
            "vmware_validate_ctx_schema: true",
            "vmware_ctx:",
            "  audit_type: \"vcenter_health\"",
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
            self.assertIn(snippet, text, msg=f"Missing defaults contract snippet: {snippet}")


if __name__ == "__main__":
    unittest.main()
