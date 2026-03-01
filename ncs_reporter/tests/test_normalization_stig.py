"""Tests for STIG normalization logic."""

from ncs_reporter.normalization.stig import (
    _canonical_stig_status,
    _row_rule_id,
    _row_severity,
    _row_status,
    _row_title,
    _severity_to_alert,
    normalize_stig,
)


class TestSeverityToAlert:
    def test_cat_i_maps_to_critical(self):
        assert _severity_to_alert("CAT_I") == "CRITICAL"
        assert _severity_to_alert("HIGH") == "CRITICAL"
        assert _severity_to_alert("SEVERE") == "CRITICAL"

    def test_cat_ii_maps_to_warning(self):
        assert _severity_to_alert("CAT_II") == "WARNING"
        assert _severity_to_alert("MEDIUM") == "WARNING"
        assert _severity_to_alert("MODERATE") == "WARNING"

    def test_other_maps_to_info(self):
        assert _severity_to_alert("CAT_III") == "INFO"
        assert _severity_to_alert("LOW") == "INFO"
        assert _severity_to_alert(None) == "WARNING"  # default is "medium"


class TestCanonicalStigStatus:
    def test_failed_variants(self):
        for val in ("failed", "fail", "open", "finding", "non-compliant", "non_compliant"):
            assert _canonical_stig_status(val) == "open"

    def test_pass_variants(self):
        for val in ("pass", "passed", "compliant", "success", "closed", "notafinding", "fixed", "remediated"):
            assert _canonical_stig_status(val) == "pass"

    def test_na_variants(self):
        for val in ("na", "n/a", "not_applicable", "not applicable"):
            assert _canonical_stig_status(val) == "na"

    def test_empty_and_none(self):
        assert _canonical_stig_status("") == ""
        assert _canonical_stig_status(None) == ""


class TestRowExtractors:
    def test_row_status_fallbacks(self):
        assert _row_status({"status": "open"}) == "open"
        assert _row_status({"finding_status": "pass"}) == "pass"
        assert _row_status({"result": "fail"}) == "open"
        assert _row_status({}) == ""

    def test_row_rule_id_fallbacks(self):
        assert _row_rule_id({"id": "V-123"}) == "V-123"
        assert _row_rule_id({"rule_id": "SV-456"}) == "SV-456"
        assert _row_rule_id({"vuln_id": "V-789"}) == "V-789"
        assert _row_rule_id({}) == ""

    def test_row_title_fallbacks(self):
        assert _row_title({"title": "Test Rule"}) == "Test Rule"
        assert _row_title({"rule_title": "Alt"}) == "Alt"
        assert _row_title({}) == "Unknown Rule"

    def test_row_severity_fallbacks(self):
        assert _row_severity({"severity": "CAT_I"}) == "CAT_I"
        assert _row_severity({"cat": "high"}) == "high"
        assert _row_severity({}) == "medium"


class TestNormalizeStig:
    def test_basic_normalization(self):
        raw = {
            "data": [
                {"id": "V-001", "title": "Rule One", "status": "open", "severity": "CAT_I", "checktext": "Check it"},
                {"id": "V-002", "title": "Rule Two", "status": "pass", "severity": "CAT_II"},
                {"id": "V-003", "title": "Rule Three", "status": "na", "severity": "CAT_III"},
            ]
        }
        result = normalize_stig(raw, stig_target_type="esxi")
        assert result.target_type == "esxi"
        assert len(result.full_audit) == 3
        assert result.health == "CRITICAL"  # has CAT_I open finding
        assert result.summary.critical_count == 1
        assert result.summary.warning_count == 0

    def test_all_passing(self):
        raw = {"data": [{"id": "V-001", "status": "pass", "severity": "CAT_I"}]}
        result = normalize_stig(raw)
        assert result.health == "HEALTHY"
        assert len(result.alerts) == 0

    def test_empty_input(self):
        result = normalize_stig({})
        assert result.health == "HEALTHY"
        assert len(result.full_audit) == 0
        assert len(result.alerts) == 0

    def test_list_input(self):
        raw = [{"id": "V-001", "status": "open", "severity": "high"}]
        result = normalize_stig(raw)
        assert len(result.full_audit) == 1
        assert result.health == "CRITICAL"

    def test_malformed_rows_skipped(self):
        raw = {"data": [None, "not a dict", 42, {"id": "V-001", "status": "pass", "severity": "low"}]}
        result = normalize_stig(raw)
        assert len(result.full_audit) == 1

    def test_alert_detail_contains_rule_info(self):
        raw = {
            "data": [
                {"id": "V-001", "title": "SSH Rule", "status": "open", "severity": "CAT_I", "checktext": "Verify SSH"}
            ]
        }
        result = normalize_stig(raw, stig_target_type="vm")
        assert len(result.alerts) == 1
        alert = result.alerts[0]
        assert alert.severity == "CRITICAL"
        assert "V-001" in alert.detail.get("rule_id", "")
        assert alert.detail.get("target_type") == "vm"
