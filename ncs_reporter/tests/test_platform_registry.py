"""Tests for the PlatformRegistry data-driven lookups."""

from ncs_reporter.models.platforms_config import PlatformEntry, PlatformsConfig
from ncs_reporter.platform_registry import PlatformRegistry, default_registry


def _make_entry(**overrides) -> PlatformEntry:
    defaults = {
        "input_dir": "test",
        "report_dir": "test",
        "platform": "test",
        "state_file": "test_fleet_state.yaml",
        "render": True,
        "target_types": ["test"],
        "paths": {
            "raw_stig_artifact": "platform/{report_dir}/{hostname}/raw_stig_{target_type}.yaml",
            "report_fleet": "platform/{report_dir}/{schema_name}_fleet_report.html",
            "report_node_latest": "platform/{report_dir}/{hostname}/health_report.html",
            "report_node_historical": "platform/{report_dir}/{hostname}/health_report_{report_stamp}.html",
            "report_stig_host": "platform/{report_dir}/{hostname}/{hostname}_stig_{target_type}.html",
            "report_search_entry": "platform/{report_dir}/{hostname}/health_report.html",
            "report_site": "site_health_report.html",
            "report_stig_fleet": "stig_fleet_report.html",
        },
    }
    defaults.update(overrides)
    return PlatformEntry.model_validate(defaults)


class TestPlatformRegistry:
    def test_all_platform_names_preserves_order(self):
        entries = [
            _make_entry(platform="linux", input_dir="linux/ubuntu", report_dir="linux/ubuntu"),
            _make_entry(platform="vmware", input_dir="vmware/vcenter", report_dir="vmware/vcenter"),
            _make_entry(platform="vmware", input_dir="vmware/esxi", report_dir="vmware/esxi"),
            _make_entry(platform="windows", input_dir="windows", report_dir="windows"),
        ]
        reg = PlatformRegistry(entries)
        assert reg.all_platform_names() == ["linux", "vmware", "windows"]

    def test_all_target_types(self):
        entries = [
            _make_entry(platform="linux", target_types=["linux", "ubuntu"]),
            _make_entry(platform="vmware", target_types=["esxi", "vm"]),
        ]
        reg = PlatformRegistry(entries)
        assert reg.all_target_types() == {"linux", "ubuntu", "esxi", "vm"}

    def test_schema_names_for_platform(self):
        entries = [
            _make_entry(platform="linux", schema_names=["linux"]),
            _make_entry(platform="vmware", schema_names=["vcenter"]),
        ]
        reg = PlatformRegistry(entries)
        assert reg.schema_names_for_platform("linux") == ["linux"]
        assert reg.schema_names_for_platform("vmware") == ["vcenter"]
        assert reg.schema_names_for_platform("unknown") == ["unknown"]

    def test_host_exclude_set(self):
        entries = [
            _make_entry(platform="linux", input_dir="linux/ubuntu", report_dir="linux/ubuntu",
                        state_file="linux_fleet_state.yaml"),
        ]
        reg = PlatformRegistry(entries)
        excludes = reg.host_exclude_set()
        assert "linux" in excludes
        assert "ubuntu" in excludes
        assert "platform" in excludes
        assert "linux_fleet_state.yaml" in excludes
        assert "linux_fleet_state" in excludes

    def test_skip_keys_set(self):
        entries = [
            _make_entry(platform="linux", state_file="linux_fleet_state.yaml"),
        ]
        reg = PlatformRegistry(entries)
        skip = reg.skip_keys_set()
        assert "summary" in skip
        assert "linux" in skip
        assert "linux_fleet_state.yaml" in skip

    def test_stig_skeleton_for_target(self):
        entries = [
            _make_entry(platform="vmware", stig_skeleton_map={"esxi": "skeleton_esxi.json"}),
        ]
        reg = PlatformRegistry(entries)
        assert reg.stig_skeleton_for_target("esxi") == "skeleton_esxi.json"
        assert reg.stig_skeleton_for_target("nonexistent") is None

    def test_infer_target_type_from_rule_prefix(self):
        entries = [
            _make_entry(platform="linux", stig_rule_prefixes={"UBTU": "ubuntu", "GEN": "ubuntu"}),
            _make_entry(platform="vmware", stig_rule_prefixes={"ESXI": "esxi", "VMCH": "vm"}),
            _make_entry(platform="windows", stig_rule_prefixes={"WN": "windows", "MS": "windows"}),
        ]
        reg = PlatformRegistry(entries)
        assert reg.infer_target_type_from_rule_prefix("UBTU-20-010001") == "ubuntu"
        assert reg.infer_target_type_from_rule_prefix("ESXI-70-000001") == "esxi"
        assert reg.infer_target_type_from_rule_prefix("VMCH-70-000001") == "vm"
        assert reg.infer_target_type_from_rule_prefix("WN10-CC-000001") == "windows"
        assert reg.infer_target_type_from_rule_prefix("UNKNOWN-001") == ""

    def test_infer_platform_from_target_type(self):
        entries = [
            _make_entry(platform="linux", target_types=["linux", "ubuntu"]),
            _make_entry(platform="vmware", target_types=["esxi", "vm", "vcsa"]),
            _make_entry(platform="windows", target_types=["windows"]),
        ]
        reg = PlatformRegistry(entries)
        assert reg.infer_platform_from_target_type("esxi") == "vmware"
        assert reg.infer_platform_from_target_type("ubuntu") == "linux"
        assert reg.infer_platform_from_target_type("windows") == "windows"
        assert reg.infer_platform_from_target_type("nonexistent") == "unknown"

    def test_site_dashboard_entries(self):
        entries = [
            _make_entry(platform="linux", site_audit_key="linux"),
            _make_entry(platform="vmware", site_audit_key="vcenter"),
            _make_entry(platform="vmware", render=False),  # render=False -> no site_audit_key -> excluded
        ]
        reg = PlatformRegistry(entries)
        site = reg.site_dashboard_entries()
        assert len(site) == 2
        assert site[0].platform == "linux"
        assert site[1].platform == "vmware"

    def test_count_inventory_assets(self):
        entry = _make_entry(platform="linux", inventory_groups=["ubuntu_servers"])
        reg = PlatformRegistry([entry])
        groups = {"ubuntu_servers": ["h1", "h2", "h3"]}
        assert reg.count_inventory_assets(entry, groups) == 3
        assert reg.count_inventory_assets(entry, {}) == 0

    def test_platform_fleet_link(self):
        entries = [
            _make_entry(platform="linux", fleet_link="platform/linux/ubuntu/linux_fleet_report.html"),
        ]
        reg = PlatformRegistry(entries)
        assert reg.platform_fleet_link("linux") == "platform/linux/ubuntu/linux_fleet_report.html"
        assert reg.platform_fleet_link("unknown") is None

    def test_platform_display_name(self):
        entries = [
            _make_entry(platform="linux", display_name="Linux"),
        ]
        reg = PlatformRegistry(entries)
        assert reg.platform_display_name("linux") == "Linux"
        assert reg.platform_display_name("unknown") == "Unknown"

    def test_link_base_for_target(self):
        entries = [
            _make_entry(platform="vmware", report_dir="vmware/esxi", target_types=["esxi"]),
            _make_entry(platform="vmware", report_dir="vmware/vm", target_types=["vm"]),
            _make_entry(platform="linux", report_dir="linux/ubuntu", target_types=["ubuntu"]),
        ]
        reg = PlatformRegistry(entries)
        assert reg.link_base_for_target("esxi") == "platform/vmware/esxi"
        assert reg.link_base_for_target("vm") == "platform/vmware/vm"
        assert reg.link_base_for_target("ubuntu") == "platform/linux/ubuntu"

    def test_platform_to_report_dir(self):
        entries = [
            _make_entry(platform="vmware", report_dir="vmware/vcenter", render=True),
            _make_entry(platform="vmware", report_dir="vmware/esxi", render=False),
        ]
        reg = PlatformRegistry(entries)
        assert reg.platform_to_report_dir("vmware") == "vmware/vcenter"

    def test_all_stig_skeleton_map_merges(self):
        entries = [
            _make_entry(platform="vmware", stig_skeleton_map={"esxi": "esxi.json", "vm": "vm.json"}),
            _make_entry(platform="linux", stig_skeleton_map={"ubuntu": "ubuntu.json"}),
        ]
        reg = PlatformRegistry(entries)
        merged = reg.all_stig_skeleton_map()
        assert merged["esxi"] == "esxi.json"
        assert merged["vm"] == "vm.json"
        assert merged["ubuntu"] == "ubuntu.json"


class TestDefaultRegistry:
    def test_default_registry_loads(self):
        reg = default_registry()
        assert "linux" in reg.all_platform_names()
        assert "vmware" in reg.all_platform_names()
        assert "windows" in reg.all_platform_names()

    def test_default_registry_skeleton_map(self):
        reg = default_registry()
        assert reg.stig_skeleton_for_target("esxi") == "cklb_skeleton_vsphere7_esxi_V1R4.json"
        assert reg.stig_skeleton_for_target("vm") == "cklb_skeleton_vsphere7_vms_V1R4.json"

    def test_default_registry_rule_prefixes(self):
        reg = default_registry()
        assert reg.infer_target_type_from_rule_prefix("UBTU-20-010001") == "ubuntu"
        assert reg.infer_target_type_from_rule_prefix("ESXI-70-000001") == "esxi"
        assert reg.infer_target_type_from_rule_prefix("WN10-CC-000001") == "windows"

    def test_default_registry_site_entries(self):
        reg = default_registry()
        site = reg.site_dashboard_entries()
        platforms = [e.platform for e in site]
        assert "linux" in platforms
        assert "vmware" in platforms
        assert "windows" in platforms


class TestFakePlatformIntegration:
    """Verify a new platform can be added via platforms.yaml with zero Python changes."""

    def test_fake_platform_in_registry(self):
        entries = list(default_registry().entries) + [
            _make_entry(
                platform="network",
                input_dir="network",
                report_dir="network",
                target_types=["switch", "router"],
                display_name="Network",
                asset_label="Devices",
                inventory_groups=["network_devices"],
                schema_names=["network"],
                stig_skeleton_map={"switch": "switch_skeleton.json"},
                stig_rule_prefixes={"NET": "switch"},
                site_audit_key="network",
                site_category="Network",
                fleet_link="platform/network/network_fleet_report.html",
            ),
        ]
        reg = PlatformRegistry(entries)

        assert "network" in reg.all_platform_names()
        assert "switch" in reg.all_target_types()
        assert "router" in reg.all_target_types()
        assert reg.schema_names_for_platform("network") == ["network"]
        assert reg.stig_skeleton_for_target("switch") == "switch_skeleton.json"
        assert reg.infer_target_type_from_rule_prefix("NET-01-000001") == "switch"
        assert reg.infer_platform_from_target_type("switch") == "network"
        assert reg.platform_display_name("network") == "Network"
        assert reg.link_base_for_target("switch") == "platform/network"

        site = reg.site_dashboard_entries()
        network_entries = [e for e in site if e.platform == "network"]
        assert len(network_entries) == 1

        groups = {"network_devices": ["sw-01", "sw-02"]}
        assert reg.count_inventory_assets(network_entries[0], groups) == 2


class TestMinimalEntry:
    """Verify that minimal entries (no paths, no state_file, etc.) get correct defaults."""

    def test_minimal_entry_gets_defaults(self):
        entry = PlatformEntry.model_validate({
            "input_dir": "network/switches",
            "report_dir": "network/switches",
            "platform": "network",
            "target_types": ["switch", "router"],
        })
        assert entry.state_file == "network_fleet_state.yaml"
        assert entry.display_name == "Network"
        assert entry.schema_names == ["network"]
        assert entry.site_audit_key == "network"
        assert entry.site_category == "Network"
        assert entry.fleet_link == "platform/network/switches/network_fleet_report.html"
        assert entry.paths.raw_stig_artifact == "platform/{report_dir}/{hostname}/raw_stig_{target_type}.yaml"
        assert entry.paths.report_fleet == "platform/{report_dir}/{schema_name}_fleet_report.html"

    def test_explicit_paths_override_defaults(self):
        custom_fleet = "custom/{report_dir}/{schema_name}_fleet.html"
        entry = PlatformEntry.model_validate({
            "input_dir": "test",
            "report_dir": "test",
            "platform": "test",
            "target_types": ["test"],
            "paths": {"report_fleet": custom_fleet},
        })
        assert entry.paths.report_fleet == custom_fleet
        # Other paths should still be defaults
        assert entry.paths.report_site == "site_health_report.html"

    def test_partial_paths_filled(self):
        entry = PlatformEntry.model_validate({
            "input_dir": "test",
            "report_dir": "test",
            "platform": "test",
            "target_types": ["test"],
            "paths": {"report_site": "custom_site.html"},
        })
        assert entry.paths.report_site == "custom_site.html"
        assert entry.paths.report_fleet == "platform/{report_dir}/{schema_name}_fleet_report.html"

    def test_explicit_state_file_wins(self):
        entry = PlatformEntry.model_validate({
            "input_dir": "test",
            "report_dir": "test",
            "platform": "test",
            "target_types": ["test"],
            "state_file": "custom_state.yaml",
        })
        assert entry.state_file == "custom_state.yaml"

    def test_explicit_display_name_wins(self):
        entry = PlatformEntry.model_validate({
            "input_dir": "test",
            "report_dir": "test",
            "platform": "vmware",
            "target_types": ["vcenter"],
            "display_name": "VMware vCenter",
        })
        assert entry.display_name == "VMware vCenter"

    def test_render_false_no_site_audit_key(self):
        entry = PlatformEntry.model_validate({
            "input_dir": "test",
            "report_dir": "test",
            "platform": "test",
            "target_types": ["test"],
            "render": False,
        })
        assert entry.site_audit_key is None
        assert entry.fleet_link is None


class TestSchemaEmbeddedParity:
    """Ensure schema-embedded platform metadata produces a valid registry
    and the path contract validator still works with the generated entries."""

    def test_default_registry_from_schemas(self):
        reg = default_registry()
        entries = reg.entries
        assert len(entries) > 0
        # All original target types must be present
        all_tt = reg.all_target_types()
        for expected in ("linux", "ubuntu", "photon", "esxi", "vm", "vcsa", "windows"):
            assert expected in all_tt, f"Missing target type: {expected}"

    def test_schema_derived_entries_pass_path_contract(self):
        from ncs_path_contract import validate_platforms_config_dict

        entries = [e.model_dump() for e in default_registry().entries]
        validated = validate_platforms_config_dict({"platforms": entries})
        assert len(validated) > 0

    def test_schema_derived_target_types_match_contract(self):
        from ncs_path_contract import build_target_type_index

        entries = [e.model_dump() for e in default_registry().entries]
        pydantic_targets = {t for e in entries for t in e.get("target_types", [])}
        contract_index = build_target_type_index(entries)
        contract_targets = set(contract_index.keys())
        assert pydantic_targets == contract_targets

    def test_minimal_config_passes_both_validators(self):
        from ncs_path_contract import validate_platforms_config_dict

        minimal = {
            "platforms": [
                {
                    "input_dir": "network/switches",
                    "report_dir": "network/switches",
                    "platform": "network",
                    "target_types": ["switch", "router"],
                }
            ]
        }
        # Pydantic
        config = PlatformsConfig.model_validate(minimal)
        assert len(config.platforms) == 1
        assert config.platforms[0].state_file == "network_fleet_state.yaml"
        assert config.platforms[0].paths.report_site == "site_health_report.html"
        # Path contract
        entries = validate_platforms_config_dict(minimal)
        assert len(entries) == 1
        assert entries[0]["state_file"] == "network_fleet_state.yaml"
        assert "report_site" in entries[0]["paths"]
