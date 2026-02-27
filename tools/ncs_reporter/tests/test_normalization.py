"""Unit tests for the ncs_reporter normalization layer."""

from ncs_reporter.normalization.vmware import normalize_vmware
from ncs_reporter.normalization.linux import normalize_linux
from ncs_reporter.normalization.windows import normalize_windows


def test_normalize_vmware_basic():
    raw_bundle = {
        "metadata": {"timestamp": "2026-02-26T12:00:00Z"},
        "data": {
            "datacenters_info": {"value": [{"name": "DC1", "datacenter": "datacenter-1"}]},
            "clusters_info": {"results": []},
            "datastores_info": {"datastores": []},
            "vms_info": {"virtual_machines": []},
            "appliance_health_info": {"appliance": {"summary": {"health": {"overall": "green"}}}},
            "appliance_backup_info": {"schedules": [{"enabled": True, "location": "smb://test"}]},
            "alarms_info": {"alarms": [], "success": True},
        }
    }
    normalized = normalize_vmware(raw_bundle)
    assert normalized.health == "HEALTHY"
    assert normalized.metadata.audit_type == "vmware_vcenter"
    assert normalized.discovery is not None


def test_normalize_linux_basic():
    raw_bundle = {
        "metadata": {"timestamp": "2026-02-26T12:00:00Z"},
        "data": {
            "ansible_facts": {
                "hostname": "test-linux",
                "memtotal_mb": 1024,
                "memfree_mb": 512,
                "mounts": []
            },
            "failed_services": {"stdout_lines": []},
            "apt_simulate": {"stdout_lines": []},
            "reboot_stat": {"stat": {"exists": False}},
        }
    }
    normalized = normalize_linux(raw_bundle)
    assert normalized.health == "HEALTHY"
    assert normalized.ubuntu_ctx.system.hostname == "test-linux"


def test_normalize_windows_basic():
    raw_bundle = {
        "metadata": {"timestamp": "2026-02-26T12:00:00Z"},
        "data": {
            "ccm_service": {"state": "running"},
            "configmgr_apps": [],
            "installed_apps": [],
            "update_results": [],
        }
    }
    normalized = normalize_windows(raw_bundle)
    assert normalized.health == "HEALTHY"
    # services info is in the wrapped windows_audit dict, not SummaryModel
    assert normalized.windows_audit["summary"]["services"]["ccmexec_running"] is True
