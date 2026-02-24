from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import platform
import re
import sys
import xml.etree.ElementTree as ET
from time import gmtime, strftime

from ansible.plugins.callback import CallbackBase

XCCDF_NS = "http://checklists.nist.gov/xccdf/1.1"


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "xml"
    CALLBACK_NAME = "stig_xml"
    CALLBACK_NEEDS_WHITELIST = True

    # -------------------------------------------------------------------------
    # Init
    # -------------------------------------------------------------------------

    def __init__(self):
        super().__init__()
        self.rules = {}  # {rule_num: 'pass' | 'fixed' | 'failed'}
        self.rule_details = {}  # {rule_num: {title, severity, fixtext, checktext, full_id}}

        self.stig_path = os.environ.get("STIG_PATH") or self._find_stig_xml()
        if self.stig_path is None:
            self.disabled = True
            return

        self.disabled = False
        self._parse_stig_xml()

        artifact_dir = os.environ.get(
            "ARTIFACT_DIR", os.path.join(os.getcwd(), ".artifacts")
        )
        os.makedirs(artifact_dir, exist_ok=True)

        self.xml_path = os.environ.get(
            "XML_PATH", os.path.join(artifact_dir, "xccdf-results.xml")
        )
        self.json_path = self.xml_path.replace(".xml", "_failures.json")

        self._init_xml()
        self._dump_json()

    def _find_stig_xml(self):
        """Walk cwd looking for an XCCDF XML file under a files/ directory."""
        for dirpath, _, files in os.walk(os.path.abspath(".")):
            if os.path.sep + "files" not in dirpath:
                continue
            for f in files:
                if (
                    f.endswith(".xml")
                    and "xccdf" in f.lower()
                    and "results" not in f.lower()
                ):
                    return os.path.join(dirpath, f)
        return None

    def _init_xml(self):
        stig_name = os.path.basename(self.stig_path)
        result_id = f"xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{stig_name}"

        ET.register_namespace("", XCCDF_NS)
        self.tr = ET.Element(f"{{{XCCDF_NS}}}TestResult")
        self.tr.set("id", result_id)
        self.tr.set("end-time", strftime("%Y-%m-%dT%H:%M:%S", gmtime()))

        bm = ET.SubElement(self.tr, f"{{{XCCDF_NS}}}benchmark")
        bm.set("href", result_id)

        tg = ET.SubElement(self.tr, f"{{{XCCDF_NS}}}target")
        tg.text = platform.node()

    # -------------------------------------------------------------------------
    # STIG XML parsing
    # -------------------------------------------------------------------------

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

            # For Group elements, use the child Rule for details
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
                "fixtext": self._child_text(target, "fixtext") or "No Fix Text",
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
        m = re.search(r"(?:V-|SV-|stigrule_)?(\d+)", text)
        return m.group(1) if m else None

    # -------------------------------------------------------------------------
    # Output
    # -------------------------------------------------------------------------

    def _dump_json(self):
        """Writes failed and fixed rules to JSON artifact."""
        report = []
        for rule_num, status in self.rules.items():
            if status not in ("fixed", "failed"):
                continue
            d = self.rule_details.get(rule_num, {})
            report.append(
                {
                    "id": d.get("full_id", f"SV-{rule_num}"),
                    "status": status,
                    "title": d.get("title", "Unknown Rule"),
                    "severity": d.get("severity", "medium"),
                    "fixtext": d.get("fixtext", ""),
                    "checktext": d.get("checktext", ""),
                }
            )
        try:
            with open(self.json_path, "w") as f:
                json.dump(report, f, indent=2)
        except OSError as e:
            sys.stderr.write(f"[stig_xml] Failed to write JSON: {e}\n")

    def _dump_xml(self):
        """Writes XCCDF TestResult XML. Safe to call once only."""
        for rule_num, status in self.rules.items():
            d = self.rule_details.get(rule_num, {})
            full_id = d.get("full_id", f"SV-{rule_num}")

            rr = ET.SubElement(self.tr, f"{{{XCCDF_NS}}}rule-result")
            rr.set("idref", full_id)
            rs = ET.SubElement(rr, f"{{{XCCDF_NS}}}result")
            rs.text = "fail" if status == "failed" else "pass"

        try:
            with open(self.xml_path, "wb") as f:
                f.write(ET.tostring(self.tr))
        except OSError as e:
            sys.stderr.write(f"[stig_xml] Failed to write XML: {e}\n")
        finally:
            self._xml_written = True

    # -------------------------------------------------------------------------
    # Ansible callback hooks
    # -------------------------------------------------------------------------

    def v2_runner_on_ok(self, result):
        if getattr(self, "disabled", True):
            return
        rule_num = self._extract_rule_number(result._task.get_name())
        if not rule_num:
            return
        # Don't downgrade a previous failure
        if self.rules.get(rule_num) == "failed":
            return
        status = "fixed" if result.is_changed() else "pass"
        self.rules[rule_num] = status
        if status == "fixed":
            self._dump_json()

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if getattr(self, "disabled", True):
            return
        rule_num = self._extract_rule_number(result._task.get_name())
        if not rule_num:
            return
        self.rules[rule_num] = "failed"
        self._dump_json()

    def v2_playbook_on_stats(self, stats):
        if getattr(self, "disabled", True):
            return
        self._dump_json()
        if not getattr(self, "_xml_written", False):
            self._dump_xml()
