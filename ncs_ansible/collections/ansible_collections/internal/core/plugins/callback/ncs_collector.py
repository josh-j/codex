# collections/ansible_collections/internal/core/plugins/callback/ncs_collector.py

import os
import re
import tempfile
import hashlib
import importlib.util
import stat
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

DEFAULT_REPORT_DIRECTORY = "/srv/samba/reports"
FILE_MODE_INHERIT_MASK = 0o666


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


def _import_path_contract_module():
    try:
        from ansible_collections.internal.core.plugins.module_utils import path_contract as module
        return module
    except Exception:
        # Local unit tests load callback by file path (no collection package context).
        mod_path = os.path.join(os.path.dirname(__file__), "..", "module_utils", "path_contract.py")
        spec = importlib.util.spec_from_file_location("ncs_path_contract_module_utils", mod_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"Could not load path contract module from {mod_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _load_platforms_contract(repo_root: str) -> tuple[list[dict], dict[str, dict], object]:
    path_contract = _import_path_contract_module()

    explicit_cfg = os.environ.get("NCS_PLATFORMS_CONFIG", "").strip()
    if explicit_cfg:
        cfg_path = explicit_cfg
    else:
        cfg_path = os.path.join(repo_root, "files", "ncs_reporter_configs", "platforms.yaml")
    platforms = path_contract.load_platforms_config_file(cfg_path)
    target_index = path_contract.build_target_type_index(platforms)
    return platforms, target_index, path_contract.resolve_platform_for_target_type

class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = 'aggregate'
    CALLBACK_NAME = 'ncs_collector'
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.repo_root = _find_repo_root(os.path.dirname(__file__))
        self._stig_rules = {}
        self._stig_meta = {}
        self._host_report_dirs = {}
        self._platforms_config, self._target_type_index, self._resolve_platform_for_target = _load_platforms_contract(
            self.repo_root
        )

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
        report_dir = collect_data.get('report_directory') or DEFAULT_REPORT_DIRECTORY
        target_type = ""
        if isinstance(name, str) and name.startswith("stig_"):
            target_type = name.replace("stig_", "", 1).strip().lower()
            platform_cfg = self._resolve_platform_for_target(self._platforms_config, target_type)
            paths = platform_cfg.get("paths", {}) if isinstance(platform_cfg, dict) else {}
            raw_template = str(paths.get("raw_stig_artifact", "")).strip()
            if not raw_template:
                raise RuntimeError(f"Missing paths.raw_stig_artifact for target_type '{target_type}'")
            raw_path = os.path.join(
                report_dir,
                raw_template.format(
                    report_dir=str(platform_cfg.get("report_dir", "")),
                    hostname=host,
                    schema_name=str(platform_cfg.get("schema_name") or platform_cfg.get("platform") or ""),
                    target_type=target_type,
                    report_stamp="",
                ),
            )
            host_dir = os.path.dirname(raw_path)
        else:
            host_dir = os.path.join(report_dir, 'platform', platform, host)
        
        try:
            self._ensure_dir_inherits_parent(host_dir)
        except OSError as e:
            self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
            return

        # 1. Save Raw Payload
        if payload is not None:
            raw_path = raw_path if (isinstance(name, str) and name.startswith("stig_")) else os.path.join(
                host_dir, f"raw_{name}.yaml"
            )
            envelope = {
                'metadata': {
                    'host': host,
                    'raw_type': name,
                    'timestamp': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
                    'engine': 'ncs_collector_callback'
                },
                'data': payload
            }
            if isinstance(name, str) and name.startswith("stig_"):
                envelope['metadata']['audit_type'] = name
                envelope['target_type'] = target_type
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
        # Pattern 1: stigrule_123456
        m = re.search(r"stigrule_(\d{4,})", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        # Pattern 2: V-123456
        m = re.search(r"\bV-(\d{4,})\b", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        # Pattern 3: PREFIX-YY-123456 (VCPG-70-000002, PHTN-50-000016)
        m = re.search(r"\b[A-Z]+-\d+-(\d{4,})\b", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    def _record_stig_result(self, result, failed=False, skipped=False):
        task = getattr(result, "_task", None)
        if task is None:
            return
        task_name = getattr(task, "name", "") or ""
        task_vars = getattr(task, "vars", {}) or {}
        target_type = str(task_vars.get("stig_target_type", "") or "").lower() or "esxi"
        rule_num = self._extract_rule_number(task_name)
        if not rule_num and target_type in {"vcsa", "vcenter"} and task_name:
            # VCSA role tasks do not always carry STIG IDs in task names.
            # Generate a stable synthetic rule id per task name to preserve findings.
            digest = hashlib.sha1(task_name.encode("utf-8")).hexdigest()
            rule_num = f"9{(int(digest[:8], 16) % 99999):05d}"
        if not rule_num:
            return

        host = task_vars.get("stig_target_host")
        if not host:
            try:
                host = result._host.get_name()
            except Exception:
                host = "unknown"

        try:
            platform_cfg = self._resolve_platform_for_target(self._platforms_config, target_type)
        except Exception as exc:
            raise RuntimeError(f"Unknown STIG target_type '{target_type}' in ncs_collector callback: {exc}") from exc
        platform = str(platform_cfg.get("report_dir", "")).strip()
        if not platform:
            raise RuntimeError(f"Missing report_dir for target_type '{target_type}' in platforms config")

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
                or DEFAULT_REPORT_DIRECTORY
            )
            try:
                platform_cfg = self._resolve_platform_for_target(self._platforms_config, str(target_type))
            except Exception as exc:
                raise RuntimeError(f"Unknown STIG target_type '{target_type}' while persisting STIG data: {exc}") from exc
            paths = platform_cfg.get("paths", {}) if isinstance(platform_cfg, dict) else {}
            raw_template = str(paths.get("raw_stig_artifact", "")).strip()
            if not raw_template:
                raise RuntimeError(f"Missing paths.raw_stig_artifact for target_type '{target_type}'")
            raw_rel = raw_template.format(
                report_dir=str(platform_cfg.get("report_dir", "")),
                hostname=host,
                schema_name=str(platform_cfg.get("schema_name") or platform_cfg.get("platform") or ""),
                target_type=str(target_type),
                report_stamp="",
            )
            raw_path = os.path.join(report_dir, raw_rel)
            host_dir = os.path.dirname(raw_path)
            try:
                self._ensure_dir_inherits_parent(host_dir)
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
            self._write_yaml(raw_path, envelope)

    def _write_yaml(self, path, data):
        try:
            clean_data = self._to_builtin(data)
            dir_ = os.path.dirname(path) or "."
            with tempfile.NamedTemporaryFile('w', dir=dir_, suffix='.tmp', delete=False, encoding='utf-8') as tmp:
                yaml.dump(clean_data, tmp, Dumper=_IndentedDumper, default_flow_style=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
            self._apply_file_mode_from_parent(path)
            self._display.display(f"[ncs_collector] Persisted data to {path}", color='green')
        except Exception as e:
            self._display.warning(f"[ncs_collector] Failed to write {path}: {e}")

    def _mode_from_parent(self, parent_dir: str, *, is_dir: bool) -> int:
        parent_mode = stat.S_IMODE(os.stat(parent_dir).st_mode)
        if is_dir:
            return parent_mode
        return parent_mode & FILE_MODE_INHERIT_MASK

    def _ensure_dir_inherits_parent(self, path: str) -> None:
        path = os.path.realpath(path)
        if os.path.isdir(path):
            return
        parent = os.path.dirname(path) or "."
        if parent != path and not os.path.isdir(parent):
            self._ensure_dir_inherits_parent(parent)
        try:
            os.mkdir(path)
        except FileExistsError:
            return
        os.chmod(path, self._mode_from_parent(parent, is_dir=True))

    def _apply_file_mode_from_parent(self, path: str) -> None:
        parent = os.path.dirname(path) or "."
        os.chmod(path, self._mode_from_parent(parent, is_dir=False))

    def _to_builtin(self, value):
        """Recursively coerce Ansible-tagged values to plain Python builtins."""
        if isinstance(value, dict):
            return {str(k): self._to_builtin(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_builtin(v) for v in value]
        if isinstance(value, str):
            return str(value)
        if isinstance(value, (int, float, bool)) or value is None:
            return value
        return str(value)
