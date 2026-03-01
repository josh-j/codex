# collections/ansible_collections/internal/core/plugins/callback/ncs_collector.py

import os
import re
import tempfile
from datetime import datetime, timezone

import yaml
from ansible.plugins.callback import CallbackBase


class _IndentedDumper(yaml.Dumper):
    """PyYAML Dumper that indents block sequences under their parent key."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)

DOCUMENTATION = '''
    callback: ncs_collector
    type: aggregate
    short_description: Persists NCS raw collection data to disk from host stats
    description:
      - Intercepts 'ncs_collect' data from set_stats and writes it to the reporting directory.
      - Ensures that data collection remains persistent even after the playbook finishes.
'''

def _find_repo_root(start_dir: str, max_up: int = 8) -> str:
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
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'ncs_collector'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.repo_root = _find_repo_root(os.getcwd())
        self._stig_rules = {}
        self._stig_meta = {}
        self._host_report_dirs = {}

    def v2_playbook_on_stats(self, stats):
        """
        Triggered at the end of the playbook. Iterates through all hosts and
        persists any 'ncs_collect' data found in their stats.
        """
        all_custom = getattr(stats, "custom", {}) or {}

        for host in stats.processed.keys():
            custom_stats = all_custom.get(host, {})

            if not custom_stats or 'ncs_collect' not in custom_stats:
                continue

            collect_data = custom_stats['ncs_collect']
            if not isinstance(collect_data, dict):
                continue

            report_dir = collect_data.get('report_directory')
            if isinstance(report_dir, str) and report_dir.strip():
                self._host_report_dirs[host] = report_dir.strip()

            self._persist_host_data(host, collect_data)

        # Persist STIG task telemetry gathered from runner events.
        self._persist_stig_task_data()

    def v2_runner_on_ok(self, result):
        self._record_stig_result(result, failed=False, skipped=False)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record_stig_result(result, failed=True, skipped=False)

    def v2_runner_on_skipped(self, result):
        self._record_stig_result(result, failed=False, skipped=True)

    def _persist_host_data(self, host, collect_data):
        """
        Writes the collection payload and config to the appropriate disk paths.
        """
        platform = collect_data.get('platform', 'unknown')
        name = collect_data.get('name', 'raw')
        payload = collect_data.get('payload')
        config = collect_data.get('config')
        
        # Determine output directory
        report_dir = collect_data.get('report_directory') or '/srv/samba/reports'
        host_dir = os.path.join(report_dir, 'platform', platform, host)
        
        try:
            os.makedirs(host_dir, exist_ok=True)
        except OSError as e:
            self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
            return

        # 1. Save Raw Payload
        if payload is not None:
            raw_path = os.path.join(host_dir, f"raw_{name}.yaml")
            envelope = {
                'metadata': {
                    'host': host,
                    'raw_type': name,
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'engine': 'ncs_collector_callback'
                },
                'data': payload
            }
            self._write_yaml(raw_path, envelope)

        # 2. Save Config if provided
        if config:
            config_path = os.path.join(host_dir, "config.yaml")
            config_envelope = {
                'metadata': {
                    'host': host,
                    'type': 'config',
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
                },
                'config': config
            }
            self._write_yaml(config_path, config_envelope)

    def _extract_rule_number(self, task_name):
        if not task_name:
            return None
        m = re.search(r"stigrule_(\d{4,})", str(task_name), re.IGNORECASE)
        return m.group(1) if m else None

    def _record_stig_result(self, result, failed=False, skipped=False):
        task = getattr(result, "_task", None)
        if task is None:
            return
        task_name = getattr(task, "name", "") or ""
        rule_num = self._extract_rule_number(task_name)
        if not rule_num:
            return

        task_vars = getattr(task, "vars", {}) or {}
        host = task_vars.get("stig_target_host")
        if not host:
            try:
                host = result._host.get_name()
            except Exception:
                host = "unknown"

        target_type = str(task_vars.get("stig_target_type", "") or "").lower() or "esxi"
        platform = str(task_vars.get("stig_platform", "") or "").strip()
        if not platform:
            if target_type in {"ubuntu", "linux"}:
                platform = "linux/ubuntu"
            elif target_type == "windows":
                platform = "windows"
            else:
                platform = "vmware"

        result_data = getattr(result, "_result", {}) or {}
        check_mode = bool(getattr(task, "check_mode", False))
        changed = bool(result_data.get("changed", False))

        if failed:
            status = "failed"
        elif skipped:
            status = "na"
        elif check_mode:
            status = "failed" if changed else "pass"
        else:
            status = "fixed" if changed else "pass"

        host_rules = self._stig_rules.setdefault(host, {})
        host_rules[rule_num] = status

        self._stig_meta[host] = {
            "platform": platform,
            "target_type": target_type,
        }

    def _persist_stig_task_data(self):
        if not self._stig_rules:
            return

        for host, rules in self._stig_rules.items():
            meta = self._stig_meta.get(host, {})
            platform = meta.get("platform", "vmware")
            target_type = meta.get("target_type", "esxi")

            report_dir = (
                self._host_report_dirs.get(host)
                or os.environ.get("NCS_REPORT_DIRECTORY")
                or "/srv/samba/reports"
            )
            host_dir = os.path.join(report_dir, "platform", platform, host)
            try:
                os.makedirs(host_dir, exist_ok=True)
            except OSError as e:
                self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
                continue

            rows = []
            for rule_num, status in rules.items():
                rows.append(
                    {
                        "id": f"V-{rule_num}",
                        "rule_id": f"V-{rule_num}",
                        "name": host,
                        "status": status,
                        "title": f"stigrule_{rule_num}",
                        "severity": "medium",
                        "fixtext": "",
                        "checktext": "",
                    }
                )

            envelope = {
                "metadata": {
                    "host": host,
                    "audit_type": f"stig_{target_type}",
                    "raw_type": f"stig_{target_type}",
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "engine": "ncs_collector_callback",
                },
                "data": rows,
                "target_type": target_type,
            }
            raw_path = os.path.join(host_dir, f"raw_stig_{target_type}.yaml")
            self._write_yaml(raw_path, envelope)

    def _write_yaml(self, path, data):
        try:
            dir_ = os.path.dirname(path) or "."
            with tempfile.NamedTemporaryFile('w', dir=dir_, suffix='.tmp', delete=False, encoding='utf-8') as tmp:
                yaml.dump(data, tmp, Dumper=_IndentedDumper, default_flow_style=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
            self._display.display(f"[ncs_collector] Persisted data to {path}", color='green')
        except Exception as e:
            self._display.warning(f"[ncs_collector] Failed to write {path}: {e}")
