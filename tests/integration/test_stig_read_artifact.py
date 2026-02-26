"""Integration tests for STIG read_callback_artifact role."""
from __future__ import annotations

import shutil

import pytest

pytestmark = pytest.mark.integration

FIXTURES_DIR = __import__("pathlib").Path(__file__).resolve().parent / "fixtures"


class TestStigReadArtifact:
    """Test reading a STIG callback JSON artifact."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, tmp_path):
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        shutil.copy2(
            FIXTURES_DIR / "stig_callback_esxi.json",
            artifacts_dir / "xccdf-results_esxi-01.lab.local.json",
        )
        self.result = run_playbook(
            "stig_read_artifact.yaml",
            extravars={
                "stig_artifacts_dir": str(artifacts_dir),
                "stig_host_hint": "esxi-01",
                "stig_require_artifact": False,
            },
        )

    def test_reads_artifact(self):
        assert len(self.result["audit_full_list"]) == 3

    def test_fixed_remapped_to_failed(self):
        # Default is_hardening=false, so "fixed" → "failed"
        statuses = {r["id"]: r["status"] for r in self.result["audit_full_list"]}
        assert statuses["V-258704"] == "failed"

    def test_artifact_path_populated(self):
        assert self.result["artifact_path"] != ""
        assert "xccdf-results" in self.result["artifact_path"]


class TestStigReadArtifactEmpty:
    """Empty artifacts directory produces empty list."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, tmp_path):
        artifacts_dir = tmp_path / "empty_artifacts"
        artifacts_dir.mkdir()
        self.result = run_playbook(
            "stig_read_artifact.yaml",
            extravars={
                "stig_artifacts_dir": str(artifacts_dir),
                "stig_host_hint": "",
                "stig_require_artifact": False,
            },
        )

    def test_empty_dir_empty_list(self):
        assert self.result["audit_full_list"] == []

    def test_artifact_path_empty(self):
        assert self.result["artifact_path"].strip() == ""


class TestStigReadArtifactHardening:
    """In hardening mode, 'fixed' should NOT be remapped to 'failed'."""

    @pytest.fixture(autouse=True)
    def _run(self, run_playbook, tmp_path):
        artifacts_dir = tmp_path / "artifacts"
        artifacts_dir.mkdir()
        shutil.copy2(
            FIXTURES_DIR / "stig_callback_esxi.json",
            artifacts_dir / "xccdf-results_esxi-01.lab.local.json",
        )
        self.result = run_playbook(
            "stig_read_artifact.yaml",
            extravars={
                "stig_artifacts_dir": str(artifacts_dir),
                "stig_host_hint": "esxi-01",
                "stig_is_hardening": True,
                "stig_require_artifact": False,
            },
        )

    def test_fixed_preserved_in_hardening(self):
        statuses = {r["id"]: r["status"] for r in self.result["audit_full_list"]}
        assert statuses["V-258704"] == "fixed"
