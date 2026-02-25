# collections/ansible_collections/internal/core/plugins/callback/stig_xml.py

import json
import os
import platform
import re
import sys
import xml.etree.ElementTree as ET
from time import gmtime, strftime

from ansible.plugins.callback import CallbackBase

XCCDF_NS = "http://checklists.nist.gov/xccdf/1.1"


def _find_repo_root(start_dir: str, max_up: int = 8) -> str:
    """
    Walk upwards looking for a repo root containing collections/ansible_collections.
    Falls back to start_dir if not found.
    """
    cur = os.path.realpath(start_dir)
    for _ in range(max_up + 1):
        marker = os.path.join(cur, "collections", "ansible_collections")
        if os.path.isdir(marker):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            break
        cur = parent
    return os.path.realpath(start_dir)


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0

    # Use a standard callback type so ansible-core reliably loads it
    CALLBACK_TYPE = "aggregate"

    CALLBACK_NAME = "stig_xml"

    # Modern + legacy enablement gates
    CALLBACK_NEEDS_ENABLED = True
    CALLBACK_NEEDS_WHITELIST = True

    def __init__(self):
        super().__init__()

        # host -> {rule_num: 'pass'|'failed'|'na'|'fixed'}
        self.rules: dict[str, dict[str, str]] = {}

        # rule_num -> details dict
        self.rule_details: dict[str, dict] = {}

        # Try to locate STIG XML (optional; plugin still runs without it)
        self.stig_path = os.environ.get("STIG_PATH") or self._find_stig_xml()
        self.disabled = False

        if self.stig_path:
            self._parse_stig_xml()
        else:
            # Allow operation without STIG XML. We’ll populate minimal rule_details from task names.
            sys.stderr.write(
                "[stig_xml] STIG XML not found; continuing with minimal rule metadata.\n"
            )

        # Stable default artifact dir: repo-root/.artifacts
        repo_root = _find_repo_root(os.getcwd())
        artifact_dir = os.environ.get("ARTIFACT_DIR") or os.path.join(
            repo_root, ".artifacts"
        )
        os.makedirs(artifact_dir, exist_ok=True)
        self.artifact_dir = artifact_dir

        # Track which hosts we emitted XML for
        self._xml_written: set[str] = set()

    # -------------------------------------------------------------------------
    # STIG XML discovery/parsing
    # -------------------------------------------------------------------------

    def _find_stig_xml(self):
        """
        Walk cwd looking for an XCCDF XML file, skipping deep irrelevant paths.
        XML is optional; we can still emit JSON based on task names.
        """
        cwd = os.getcwd()
        exclude_dirs = {".venv", ".git", "__pycache__", ".artifacts", "logs", "tests"}

        for root, dirs, files in os.walk(cwd):
            dirs[:] = [d for d in dirs if d not in exclude_dirs]

            depth = root[len(cwd) :].count(os.path.sep)
            if depth > 8:
                dirs[:] = []
                continue

            for f in files:
                if (
                    f.endswith(".xml")
                    and "xccdf" in f.lower()
                    and "results" not in f.lower()
                ):
                    return os.path.join(root, f)
        return None

    def _parse_stig_xml(self):
        try:
            root = ET.parse(self.stig_path).getroot()
        except (ET.ParseError, FileNotFoundError) as e:
            sys.stderr.write(f"[stig_xml] XML parse error: {e}\n")
            return

        for elem in root.iter():
            if not (elem.tag.endswith("Group") or elem.tag.endswith("Rule")):
                continue

            rule_num = self._extract_rule_number(elem.get("id"))
            if not rule_num or (
                rule_num in self.rule_details and elem.tag.endswith("Group")
            ):
                continue

            target = elem
            if elem.tag.endswith("Group"):
                for child in elem:
                    if child.tag.endswith("Rule"):
                        target = child
                        break

            checktext = "Check details not found"
            for child in target.iter():
                if child.tag.endswith("check-content"):
                    checktext = child.text or checktext
                    break

            self.rule_details[rule_num] = {
                "full_id": elem.get("id"),
                "title": self._child_text(target, "title") or "No Title",
                "severity": target.get("severity") or "medium",
                "fixtext": self._child_text(target, "fixtext") or "",
                "checktext": checktext,
            }

    @staticmethod
    def _child_text(parent, tag_suffix):
        for child in parent:
            if child.tag.endswith(tag_suffix):
                return child.text
        return None

    @staticmethod
    def _extract_rule_number(text):
        if not text:
            return None
        m = re.search(r"(?:V-|SV-|stigrule_|R-)?(\d{4,})", text, re.IGNORECASE)
        return m.group(1) if m else None

    # -------------------------------------------------------------------------
    # Per-host output helpers
    # -------------------------------------------------------------------------

    def _host_name(self, result):
        # Prefer inventory_hostname via host object
        try:
            return result._host.get_name()
        except Exception:
            return os.environ.get("ANSIBLE_HOSTNAME") or platform.node()

    def _paths_for_host(self, host: str):
        xml_path = os.path.join(self.artifact_dir, f"xccdf-results_{host}.xml")
        json_full_path = os.path.join(self.artifact_dir, f"xccdf-results_{host}.json")
        json_fail_path = os.path.join(
            self.artifact_dir, f"xccdf-results_{host}_failures.json"
        )
        return xml_path, json_full_path, json_fail_path

    def _ensure_rule_details(self, rule_num: str, task_name: str):
        if rule_num in self.rule_details:
            return
        # Minimal metadata when STIG XML isn't available
        self.rule_details[rule_num] = {
            "full_id": f"V-{rule_num}",
            "title": task_name or f"Rule {rule_num}",
            "severity": "medium",
            "fixtext": "",
            "checktext": "",
        }

    def _dump_json(self, host: str):
        """
        Write BOTH:
          - full list (pass/failed/na/fixed) to xccdf-results_<host>.json
          - failures-only list (failed only) to xccdf-results_<host>_failures.json
        """
        _, json_full_path, json_fail_path = self._paths_for_host(host)

        host_rules = self.rules.get(host, {})
        full_report = []
        fail_report = []

        for rule_num, status in host_rules.items():
            d = self.rule_details.get(rule_num, {})
            row = {
                "id": d.get("full_id", f"V-{rule_num}"),
                "rule_id": d.get("full_id", f"V-{rule_num}"),
                "status": status,
                "title": d.get("title", f"Rule {rule_num}"),
                "severity": d.get("severity", "medium"),
                "fixtext": d.get("fixtext", ""),
                "checktext": d.get("checktext", ""),
            }
            full_report.append(row)
            if status == "failed":
                fail_report.append(row)

        try:
            with open(json_full_path, "w", encoding="utf-8") as f:
                json.dump(full_report, f, indent=2)
            with open(json_fail_path, "w", encoding="utf-8") as f:
                json.dump(fail_report, f, indent=2)
        except OSError as e:
            sys.stderr.write(f"[stig_xml] Failed to write JSON for host {host}: {e}\n")

    def _dump_xml(self, host: str):
        """
        Writes XCCDF TestResult XML per host. Optional; kept for compatibility.
        """
        if host in self._xml_written:
            return

        xml_path, _, _ = self._paths_for_host(host)

        stig_name = (
            os.path.basename(self.stig_path) if self.stig_path else "unknown_stig.xml"
        )
        result_id = f"xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{stig_name}"

        ET.register_namespace("", XCCDF_NS)
        tr = ET.Element(f"{{{XCCDF_NS}}}TestResult")
        tr.set("id", result_id)
        tr.set("end-time", strftime("%Y-%m-%dT%H:%M:%S", gmtime()))

        bm = ET.SubElement(tr, f"{{{XCCDF_NS}}}benchmark")
        bm.set("href", result_id)

        tg = ET.SubElement(tr, f"{{{XCCDF_NS}}}target")
        tg.text = host

        for rule_num, status in self.rules.get(host, {}).items():
            d = self.rule_details.get(rule_num, {})
            full_id = d.get("full_id", f"V-{rule_num}")

            rr = ET.SubElement(tr, f"{{{XCCDF_NS}}}rule-result")
            rr.set("idref", full_id)
            rs = ET.SubElement(rr, f"{{{XCCDF_NS}}}result")

            if status == "failed":
                rs.text = "fail"
            elif status == "na":
                rs.text = "notapplicable"
            else:
                rs.text = "pass"

        try:
            with open(xml_path, "wb") as f:
                f.write(ET.tostring(tr))
        except OSError as e:
            sys.stderr.write(f"[stig_xml] Failed to write XML for host {host}: {e}\n")
        finally:
            self._xml_written.add(host)

    # -------------------------------------------------------------------------
    # Callback hooks
    # -------------------------------------------------------------------------

    def v2_runner_on_ok(self, result):
        if getattr(self, "disabled", False):
            return

        host = self._host_name(result)
        task_name = result._task.get_name()
        rule_num = self._extract_rule_number(task_name)
        if not rule_num:
            return

        self.rules.setdefault(host, {})
        self._ensure_rule_details(rule_num, task_name)

        r = getattr(result, "_result", {}) or {}
        is_check = bool(r.get("check_mode")) or bool(
            getattr(result._task, "check_mode", False)
        )

        if r.get("skipped", False):
            status = "na"
        elif result.is_changed():
            # In CHECK MODE, "changed" means non-compliant; in APPLY mode, it means fixed.
            status = "failed" if is_check else "fixed"
        else:
            status = "pass"

        # Do not downgrade a previous failure.
        if self.rules[host].get(rule_num) == "failed":
            return

        self.rules[host][rule_num] = status
        self._dump_json(host)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if getattr(self, "disabled", False):
            return

        host = self._host_name(result)
        task_name = result._task.get_name()
        rule_num = self._extract_rule_number(task_name)
        if not rule_num:
            return

        self.rules.setdefault(host, {})
        self._ensure_rule_details(rule_num, task_name)

        self.rules[host][rule_num] = "failed"
        self._dump_json(host)

    def v2_playbook_on_stats(self, stats):
        if getattr(self, "disabled", False):
            return

        for host in list(self.rules.keys()):
            self._dump_json(host)
            self._dump_xml(host)
