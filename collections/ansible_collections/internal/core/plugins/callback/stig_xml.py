from __future__ import absolute_import, division, print_function

__metaclass__ = type

import json
import os
import platform
import re
import sys

try:
    import xml.dom.minidom
    import xml.etree.ElementTree as ET
    from time import gmtime, strftime

    from ansible.plugins.callback import CallbackBase
except ImportError as e:
    sys.stderr.write("[DEBUG] STIG_XML Import Error: {}\n".format(str(e)))
    raise


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "xml"
    CALLBACK_NAME = "stig_xml"
    CALLBACK_NEEDS_WHITELIST = True

    def _get_STIG_path(self):
        cwd = os.path.abspath(".")
        for dirpath, dirs, files in os.walk(cwd):
            if os.path.sep + "files" in dirpath and len(files) > 0:
                for f in files:
                    if (
                        f.endswith(".xml")
                        and "xccdf" in f.lower()
                        and "results" not in f.lower()
                    ):
                        return os.path.join(dirpath, f)
        return None

    def __init__(self):
        try:
            super(CallbackModule, self).__init__()
            # Stores status by Number: {'270645': 'pass' | 'fixed' | 'failed'}
            self.rules = {}
            self.rule_details = {}

            self.stig_path = os.environ.get("STIG_PATH") or self._get_STIG_path()

            if self.stig_path is None:
                self.disabled = True
                return

            self.disabled = False
            self._parse_stig_xml()

            # --- ARTIFACTS PATH ---
            base_dir = os.environ.get(
                "ARTIFACT_DIR", os.path.join(os.getcwd(), ".artifacts")
            )

            if not os.path.exists(base_dir):
                try:
                    os.makedirs(base_dir)
                except OSError:
                    base_dir = os.getcwd()

            self.XML_path = os.environ.get("XML_PATH") or os.path.join(
                base_dir, "xccdf-results.xml"
            )
            self.JSON_path = self.XML_path.replace(".xml", "_failures.json")

            # Init XML
            STIG_name = os.path.basename(self.stig_path)
            ET.register_namespace("", "http://checklists.nist.gov/xccdf/1.1")

            self.tr = ET.Element("{http://checklists.nist.gov/xccdf/1.1}TestResult")
            self.tr.set(
                "id",
                "xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{}".format(
                    STIG_name
                ),
            )
            self.tr.set("end-time", strftime("%Y-%m-%dT%H:%M:%S", gmtime()))

            bm = ET.SubElement(
                self.tr, "{http://checklists.nist.gov/xccdf/1.1}benchmark"
            )
            bm.set(
                "href",
                "xccdf_mil.disa.stig_testresult_scap_mil.disa_comp_{}".format(
                    STIG_name
                ),
            )

            tg = ET.SubElement(self.tr, "{http://checklists.nist.gov/xccdf/1.1}target")
            tg.text = platform.node()

            self._dump_json()

        except Exception as e:
            sys.stderr.write(
                "[CRITICAL ERROR] Plugin Init Crashed: {}\n".format(str(e))
            )
            self.disabled = True

    def _extract_number(self, text):
        if not text:
            return None
        m = re.search(r"(?:V-|SV-|stigrule_)?(\d+)", text)
        return m.group(1) if m else None

    def _parse_stig_xml(self):
        try:
            tree = ET.parse(self.stig_path)
            root = tree.getroot()

            def find_child_text(parent, tag_suffix):
                for child in parent:
                    if child.tag.endswith(tag_suffix):
                        return child.text
                return None

            for elem in root.iter():
                if elem.tag.endswith("Group") or elem.tag.endswith("Rule"):
                    raw_id = elem.get("id")
                    rule_num = self._extract_number(raw_id)

                    if not rule_num:
                        continue
                    if rule_num in self.rule_details and elem.tag.endswith("Group"):
                        continue

                    target_elem = elem
                    if elem.tag.endswith("Group"):
                        for child in elem:
                            if child.tag.endswith("Rule"):
                                target_elem = child
                                break

                    title = find_child_text(target_elem, "title") or "No Title"
                    severity = target_elem.get("severity") or "medium"
                    fixtext = find_child_text(target_elem, "fixtext") or "No Fix Text"

                    checktext = "Check details not found"
                    for child in target_elem.iter():
                        if child.tag.endswith("check-content"):
                            checktext = child.text
                            break

                    self.rule_details[rule_num] = {
                        "title": title,
                        "severity": severity,
                        "fixtext": fixtext,
                        "checktext": checktext,
                        "full_id": raw_id,
                    }

        except Exception as e:
            sys.stderr.write("[DEBUG] XML Parse Error: {}\n".format(str(e)))

    def _dump_json(self):
        """Dumps 'fixed' and 'failed' items to JSON."""
        try:
            report_list = []

            for rule_num, status in self.rules.items():
                # We want to report on FIXED and FAILED items (skip PASS)
                if status in ["fixed", "failed"]:
                    details = self.rule_details.get(
                        rule_num,
                        {
                            "title": "Unknown Rule ID",
                            "severity": "medium",
                            "fixtext": "Details not found.",
                            "checktext": "",
                            "full_id": "SV-{}".format(rule_num),
                        },
                    )

                    report_list.append(
                        {
                            "id": details.get("full_id", "SV-{}".format(rule_num)),
                            "status": status,  # <--- NEW FIELD: 'fixed' or 'failed'
                            "title": details["title"],
                            "severity": details["severity"],
                            "fixtext": details["fixtext"],
                            "checktext": details["checktext"],
                        }
                    )

            with open(self.JSON_path, "w") as jf:
                json.dump(report_list, jf, indent=2)

        except Exception:
            pass

    def v2_runner_on_ok(self, result):
        if getattr(self, "disabled", True):
            return

        name = result._task.get_name()
        rule_num = self._extract_number(name)

        if rule_num:
            # If Changed=True, it was FIXED (Remediated)
            # If Changed=False, it was PASS (Already compliant)
            status = "fixed" if result.is_changed() else "pass"

            # Priority: If it failed before, keep it failed. Else update.
            current = self.rules.get(rule_num, "pass")
            if current != "failed":
                self.rules[rule_num] = status
                if status == "fixed":
                    self._dump_json()

    def v2_runner_on_failed(self, result, ignore_errors=False):
        if getattr(self, "disabled", True):
            return

        name = result._task.get_name()
        rule_num = self._extract_number(name)

        if rule_num:
            self.rules[rule_num] = "failed"
            self._dump_json()

    def v2_playbook_on_stats(self, stats):
        if getattr(self, "disabled", True):
            return
        self._dump_json()

        # XML Generation (Simplified)
        try:
            for rule_num, status in self.rules.items():
                # Map internal status to XCCDF result string
                # fixed -> pass (because it is now compliant)
                # failed -> fail
                xccdf_res = "fail" if status == "failed" else "pass"

                details = self.rule_details.get(rule_num, {})
                full_id = details.get("full_id", "SV-{}".format(rule_num))

                rr = ET.SubElement(
                    self.tr, "{http://checklists.nist.gov/xccdf/1.1}rule-result"
                )
                rr.set("idref", full_id)
                rs = ET.SubElement(rr, "{http://checklists.nist.gov/xccdf/1.1}result")
                rs.text = xccdf_res

            with open(self.XML_path, "wb") as f:
                out = ET.tostring(self.tr)
                xml.dom.minidom.parseString(out).toprettyxml()
                f.write(out)

        except Exception:
            pass
