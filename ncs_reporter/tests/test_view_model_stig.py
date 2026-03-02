"""Tests for STIG view-model builders."""

from ncs_reporter.view_models.stig import (
    _canonical_stig_status,
    _infer_stig_platform,
    _infer_stig_target_type,
    _normalize_stig_finding,
    _summarize_stig_findings,
    build_stig_fleet_view,
    build_stig_host_view,
)


def _stig_payload(findings=None, health="WARNING"):
    return {
        "health": health,
        "target_type": "esxi",
        "full_audit": findings or [],
        "alerts": [],
    }


class TestCanonicalStigStatus:
    def test_open_variants(self):
        for val in ("failed", "fail", "open", "non-compliant"):
            assert _canonical_stig_status(val) == "open"

    def test_pass_variants(self):
        for val in ("pass", "passed", "compliant", "success"):
            assert _canonical_stig_status(val) == "pass"

    def test_na_variants(self):
        for val in ("na", "n/a", "not_applicable"):
            assert _canonical_stig_status(val) == "na"


class TestInferStigPlatform:
    def test_vmware_from_audit_type(self):
        assert _infer_stig_platform("stig_esxi", None) == "vmware"
        assert _infer_stig_platform("stig_vm", None) == "vmware"

    def test_linux_from_audit_type(self):
        assert _infer_stig_platform("stig_ubuntu", None) == "linux"
        assert _infer_stig_platform("stig_linux", None) == "linux"

    def test_windows_from_audit_type(self):
        assert _infer_stig_platform("stig_windows", None) == "windows"

    def test_vmware_from_vcsa_audit_type(self):
        assert _infer_stig_platform("stig_vcsa", None) == "vmware"
        assert _infer_stig_platform("stig_vcenter", None) == "vmware"

    def test_linux_from_photon_audit_type(self):
        assert _infer_stig_platform("stig_photon", None) == "linux"

    def test_from_payload_target_type(self):
        assert _infer_stig_platform("stig_unknown", {"target_type": "esxi"}) == "vmware"
        assert _infer_stig_platform("stig_unknown", {"target_type": "vcsa"}) == "vmware"
        assert _infer_stig_platform("stig_unknown", {"target_type": "photon"}) == "linux"

    def test_unknown_default(self):
        assert _infer_stig_platform("stig_misc", {}) == "unknown"


class TestInferStigTargetType:
    def test_from_audit_type_prefix(self):
        assert _infer_stig_target_type("stig_esxi", None) == "esxi"
        assert _infer_stig_target_type("stig_vm", None) == "vm"

    def test_from_payload(self):
        assert _infer_stig_target_type("other", {"target_type": "esxi"}) == "esxi"


class TestNormalizeStigFinding:
    def test_basic_finding(self):
        finding = {
            "status": "open",
            "severity": "CAT_I",
            "id": "V-001",
            "title": "Test Rule",
            "description": "Test desc",
        }
        result = _normalize_stig_finding(finding, "stig_esxi", "vmware")
        assert result["status"] == "open"
        assert result["severity"] == "CRITICAL"
        assert result["rule_id"] == "V-001"
        assert result["platform"] == "vmware"

    def test_non_dict_input(self):
        result = _normalize_stig_finding("just a string", "stig_test", "linux")
        assert result["message"] == "just a string"


class TestSummarizeStigFindings:
    def test_basic_summary(self):
        findings = [
            {"severity": "CRITICAL", "status": "open"},
            {"severity": "WARNING", "status": "open"},
            {"severity": "INFO", "status": "pass"},
            {"severity": "INFO", "status": "na"},
        ]
        summary = _summarize_stig_findings(findings)
        assert summary["findings"]["total"] == 4
        assert summary["findings"]["critical"] == 1
        assert summary["findings"]["warning"] == 1
        assert summary["by_status"]["open"] == 2
        assert summary["by_status"]["pass"] == 1
        assert summary["by_status"]["na"] == 1

    def test_empty_findings(self):
        summary = _summarize_stig_findings([])
        assert summary["findings"]["total"] == 0


class TestBuildStigHostView:
    def test_basic_host_view(self):
        findings = [
            {"id": "V-001", "status": "open", "severity": "CAT_I", "title": "Rule 1"},
            {"id": "V-002", "status": "pass", "severity": "CAT_II", "title": "Rule 2"},
        ]
        view = build_stig_host_view("host1", "stig_esxi", _stig_payload(findings), report_stamp="20260226")
        assert view["target"]["host"] == "host1"
        assert view["target"]["platform"] == "vmware"
        assert view["target"]["target_type"] == "esxi"
        assert view["summary"]["findings"]["total"] == 2
        assert len(view["findings"]) == 2
        assert view["meta"]["report_stamp"] == "20260226"

    def test_empty_payload(self):
        view = build_stig_host_view("host1", "stig_test", {})
        assert view["summary"]["findings"]["total"] == 0
        assert len(view["findings"]) == 0

    def test_enriches_finding_detail_from_cklb_lookup(self):
        findings = [
            {"id": "V-001", "status": "open", "severity": "CAT_I", "title": "Rule 1"},
        ]
        cklb_lookup = {
            "V-001": {
                "rule_id": "V-001",
                "rule_title": "CKLB Rule 1",
                "severity": "cat_i",
                "discussion": "CKLB discussion",
                "check_content": "CKLB check",
                "fix_text": "CKLB fix",
            }
        }
        view = build_stig_host_view(
            "host1",
            "stig_esxi",
            _stig_payload(findings),
            cklb_rule_lookup=cklb_lookup,
        )
        finding = view["findings"][0]
        assert finding["title"] == "Rule 1"
        assert finding["detail"]["description"] == "CKLB discussion"
        assert finding["detail"]["checktext"] == "CKLB check"
        assert finding["detail"]["fixtext"] == "CKLB fix"

    def test_cklb_lookup_can_supply_title_when_missing(self):
        findings = [
            {"id": "V-009", "status": "open", "severity": "CAT_II"},
        ]
        cklb_lookup = {
            "V-009": {
                "rule_id": "V-009",
                "rule_title": "CKLB Title 9",
                "severity": "cat_ii",
                "discussion": "Discuss 9",
            }
        }
        view = build_stig_host_view(
            "host9",
            "stig_esxi",
            _stig_payload(findings),
            cklb_rule_lookup=cklb_lookup,
        )
        finding = view["findings"][0]
        assert finding["title"] == "CKLB Title 9"
        assert finding["message"] == "Discuss 9"

    def test_tree_fleets_filters_non_generated_platform_dirs(self):
        hosts_data = {
            "host-esxi": "vmware/esxi",
            "host-vc": "vmware/vcenter",
            "host-linux": "linux/ubuntu",
        }
        view = build_stig_host_view(
            "host-esxi",
            "stig_esxi",
            _stig_payload([{"id": "V-001", "status": "open", "severity": "CAT_I"}]),
            hosts_data=hosts_data,
            generated_fleet_dirs={"vmware/vcenter", "linux/ubuntu"},
        )
        reports = [f["report"] for f in view["nav"]["tree_fleets"]]
        assert any("platform/vmware/vcenter/vcenter_fleet_report.html" in r for r in reports)
        assert any("platform/linux/ubuntu/linux_fleet_report.html" in r for r in reports)
        assert not any("platform/vmware/esxi/esxi_fleet_report.html" in r for r in reports)


class TestBuildStigFleetView:
    def test_basic_fleet(self):
        hosts = {
            "host1": {
                "stig_esxi": _stig_payload(
                    [
                        {"id": "V-001", "status": "open", "severity": "CAT_I", "title": "Rule 1"},
                    ]
                )
            },
            "host2": {
                "stig_vm": _stig_payload(
                    [
                        {"id": "V-001", "status": "open", "severity": "CAT_I", "title": "Rule 1"},
                        {"id": "V-002", "status": "pass", "severity": "CAT_II", "title": "Rule 2"},
                    ]
                )
            },
        }
        view = build_stig_fleet_view(hosts, report_stamp="20260226")
        assert view["fleet"]["totals"]["hosts"] == 2
        assert len(view["rows"]) == 2
        # V-001 open on both hosts
        top = view["findings_index"]["top_findings"]
        assert len(top) > 0
        assert top[0]["rule_id"] == "V-001"
        assert top[0]["affected_hosts"] == 2

    def test_empty_hosts(self):
        view = build_stig_fleet_view({})
        assert view["fleet"]["totals"]["hosts"] == 0
        assert view["rows"] == []

    def test_non_stig_keys_skipped(self):
        hosts = {
            "host1": {
                "linux_system": {"health": "OK"},
                "stig_ubuntu": _stig_payload([{"id": "V-001", "status": "pass", "severity": "low"}]),
            }
        }
        view = build_stig_fleet_view(hosts)
        assert view["fleet"]["totals"]["hosts"] == 1
