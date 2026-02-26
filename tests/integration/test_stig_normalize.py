"""Integration tests for STIG normalization pipeline."""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


class TestStigNormalize:
    """Test the STIG normalization filter chain through Ansible."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, load_fixture):
        fixture = load_fixture("stig_callback_esxi.json")
        self.result = run_playbook(
            "stig_normalize.yaml",
            extravars={
                "audit_full_list": fixture,
                "stig_target_type": "esxi",
            },
        )

    def test_full_audit_preserves_all_rows(self):
        assert len(self.result["full_audit"]) == 3

    def test_violations_are_open_only(self):
        for v in self.result["violations"]:
            assert v["status"] == "open"

    def test_fixed_becomes_pass(self):
        # The "fixed" item (V-258704) should be normalized to "pass"
        statuses = {r["rule_id"]: r["status"] for r in self.result["full_audit"]}
        assert statuses["V-258704"] == "pass"

    def test_failed_becomes_open(self):
        statuses = {r["rule_id"]: r["status"] for r in self.result["full_audit"]}
        assert statuses["V-258703"] == "open"

    def test_summary_counts(self):
        summary = self.result["normalized"]["summary"]
        assert summary["total"] == 3
        assert summary["violations"] == 1
        assert summary["passed"] == 2


class TestStigNormalizeEmpty:
    """Empty input should produce empty output."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook):
        self.result = run_playbook(
            "stig_normalize.yaml",
            extravars={
                "audit_full_list": [],
                "stig_target_type": "esxi",
            },
        )

    def test_empty_produces_empty(self):
        assert self.result["full_audit"] == []
        assert self.result["violations"] == []
        assert self.result["alerts"] == []
