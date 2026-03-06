# collections/ansible_collections/internal/core/plugins/callback/ncs_collector.py

import hashlib
import importlib.util
import os
import re
import stat
import tempfile
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

import yaml
from ansible.plugins.callback import CallbackBase


class _IndentedDumper(yaml.Dumper):
    """PyYAML Dumper that indents block sequences under their parent key."""

    def increase_indent(self, flow=False, indentless=False):
        return super().increase_indent(flow=flow, indentless=False)


DOCUMENTATION = """
    callback: ncs_collector
    type: aggregate
    short_description: Persists NCS raw collection data to disk from host stats
    description:
      - Intercepts 'ncs_collect' data from set_stats and writes it to the reporting directory.
      - Captures STIG task outcomes from runner events and persists them as raw artifacts.
      - Ensures that data collection remains persistent even after the playbook finishes.
"""

DEFAULT_REPORT_DIRECTORY = "/srv/samba/reports"
FILE_MODE_INHERIT_MASK = 0o666

# Status priority: lower number = worse result.  When the same rule fires
# multiple times (query, assert, remediate, declarative) we keep the worst.
_STATUS_PRIORITY: dict[str, int] = {"failed": 0, "fixed": 1, "pass": 2, "na": 3}


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
    except ModuleNotFoundError as exc:
        mod_path = os.path.join(os.path.dirname(__file__), "..", "module_utils", "path_contract.py")
        spec = importlib.util.spec_from_file_location("ncs_path_contract_module_utils", mod_path)
        if not spec or not spec.loader:
            raise RuntimeError(f"Could not load path contract module from {mod_path}") from exc
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module


def _load_platforms_contract(
    repo_root: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], Callable[[list[dict[str, Any]], str], dict[str, Any]]]:
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
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "ncs_collector"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.repo_root = _find_repo_root(os.path.dirname(__file__))

        # STIG rules keyed by (host, target_type) tuple so each STIG component
        # (esxi, eam, sts, etc.) on the same inventory host gets its own bucket
        # and its own raw artifact file.
        self._stig_rules: dict[tuple[str, str], dict[str, str]] = {}
        self._stig_meta: dict[tuple[str, str], dict[str, str]] = {}

        self._host_report_dirs: dict[str, str] = {}

        # Maps inventory hostname (e.g. vCenter) → real STIG target (e.g. ESXi host).
        # Populated from set_fact tasks that set _ncs_stig_target_host.
        self._target_host_map: dict[str, str] = {}

        # Maps inventory hostname → STIG target type (e.g. "esxi", "eam", "sts").
        # Populated from set_fact tasks that set _ncs_stig_target_type.
        self._target_type_map: dict[str, str] = {}

        self._platforms_config, self._target_type_index, resolve_fn = _load_platforms_contract(self.repo_root)
        self._resolve_platform_for_target: Callable[[list[dict[str, Any]], str], dict[str, Any]] = resolve_fn

    # ------------------------------------------------------------------
    # Ansible callback hooks
    # ------------------------------------------------------------------

    def v2_playbook_on_stats(self, stats):
        """End of playbook — persist ncs_collect payloads and STIG telemetry."""
        all_custom = getattr(stats, "custom", {}) or {}

        for host in stats.processed.keys():
            custom_stats = all_custom.get(host, {})
            if not custom_stats or "ncs_collect" not in custom_stats:
                continue

            collect_data = custom_stats["ncs_collect"]
            if not isinstance(collect_data, dict):
                continue

            report_dir = collect_data.get("report_directory")
            if isinstance(report_dir, str) and report_dir.strip():
                self._host_report_dirs[host] = report_dir.strip()

            self._persist_host_data(host, collect_data)

        self._persist_stig_task_data()

    def v2_runner_on_ok(self, result):
        self._track_target_context(result)
        self._record_stig_result(result, failed=False, skipped=False)

    def v2_runner_on_failed(self, result, ignore_errors=False):
        self._record_stig_result(result, failed=True, skipped=False)

    def v2_runner_on_skipped(self, result):
        self._record_stig_result(result, failed=False, skipped=True)

    # ------------------------------------------------------------------
    # Target host and type tracking
    # ------------------------------------------------------------------

    def _track_target_context(self, result):
        """Watch for set_fact tasks that register target host and/or type.

        In ESXi/VM STIG runs the inventory host is the vCenter, but the
        actual targets are ESXi hosts or VM names.  The task files set:

            _ncs_stig_target_host: "{{ _current_esxi_host }}"
            _ncs_stig_target_type: "esxi"

        We capture those facts here so _record_stig_result can file rules
        under the correct hostname and platform.
        """
        result_data = getattr(result, "_result", {}) or {}
        ansible_facts = result_data.get("ansible_facts", {})
        if not ansible_facts:
            return

        try:
            inv_host = result._host.get_name()
        except Exception:
            return

        target = ansible_facts.get("_ncs_stig_target_host")
        if target:
            self._target_host_map[inv_host] = str(target)

        target_type = ansible_facts.get("_ncs_stig_target_type")
        if target_type:
            self._target_type_map[inv_host] = str(target_type).lower()

    # ------------------------------------------------------------------
    # STIG result recording (from runner events)
    # ------------------------------------------------------------------

    def _record_stig_result(self, result, failed: bool = False, skipped: bool = False):
        task = getattr(result, "_task", None)
        if task is None:
            return
        task_name = getattr(task, "name", "") or ""
        result_data = getattr(result, "_result", {}) or {}

        # Detect assert tasks using ignore_errors that actually failed.
        # The assert module sets evaluated_to: false when the assertion fails.
        if not failed and not skipped and "_assert" in task_name:
            if result_data.get("evaluated_to") is False:
                failed = True

        # Resolve target type.
        # Priority: task vars (stig_target_type) → target_type_map → "esxi" fallback.
        task_vars = getattr(task, "vars", {}) or {}
        target_type = str(task_vars.get("stig_target_type", "") or "").lower()
        if not target_type:
            try:
                inv_host = result._host.get_name()
            except Exception:
                inv_host = "unknown"
            target_type = self._target_type_map.get(inv_host, "esxi")

        rule_num = self._extract_rule_number(task_name)
        if not rule_num and target_type in {"vcsa", "vcenter"} and task_name:
            # VCSA role tasks do not always carry STIG IDs in task names.
            # Generate a stable synthetic rule id per task name to preserve findings.
            digest = hashlib.sha1(task_name.encode("utf-8")).hexdigest()
            rule_num = f"9{(int(digest[:8], 16) % 99999):05d}"
        if not rule_num:
            return

        # Determine task phase from suffix
        phase = "declarative"
        for suffix in ("query", "assert", "remediate", "reset", "alias", "eval_remediate"):
            if task_name.endswith(f"_{suffix}") or f"_{suffix}_" in task_name:
                phase = suffix
                break

        # Skip non-recording phases
        if phase in ("alias", "reset", "eval_remediate", "query"):
            return

        # Resolve target host.
        # Priority: task vars (stig_target_host) → target_host_map → inventory host.
        host = task_vars.get("stig_target_host")
        if not host:
            try:
                inv_host = result._host.get_name()
            except Exception:
                inv_host = "unknown"
            host = self._target_host_map.get(inv_host, inv_host)

        # Resolve platform metadata
        try:
            platform_cfg = self._resolve_platform_for_target(self._platforms_config, target_type)
        except Exception as exc:
            self._display.warning(
                f"[ncs_collector] Unknown STIG target_type '{target_type}' for task '{task_name}': {exc}"
            )
            return
        platform_report_dir = str(platform_cfg.get("report_dir", "")).strip()
        if not platform_report_dir:
            self._display.warning(
                f"[ncs_collector] Missing report_dir for target_type '{target_type}' in platforms config"
            )
            return

        # Determine status based on phase and result
        check_mode = bool(getattr(task, "check_mode", False))
        changed = bool(result_data.get("changed", False))

        if skipped:
            status = "na"
        elif failed:
            status = "failed"
        elif phase == "assert":
            # If we got here without failed=True, the assertion passed
            status = "pass"
        elif phase == "remediate":
            status = "fixed" if changed else "pass"
        else:
            # Declarative tasks (community.vmware modules, service_manager, etc.)
            if check_mode:
                status = "failed" if changed else "pass"
            else:
                status = "fixed" if changed else "pass"

        # Composite key: (host, target_type) ensures each STIG component
        # gets its own bucket and its own raw artifact file.
        bucket_key = (host, target_type)
        host_rules = self._stig_rules.setdefault(bucket_key, {})

        # Keep the worst status seen for this rule
        existing = host_rules.get(rule_num)
        if existing is None or _STATUS_PRIORITY.get(status, 99) < _STATUS_PRIORITY.get(existing, 99):
            host_rules[rule_num] = status

        self._stig_meta[bucket_key] = {
            "platform": platform_report_dir,
            "target_type": target_type,
        }

    # ------------------------------------------------------------------
    # Rule number extraction
    # ------------------------------------------------------------------

    def _extract_rule_number(self, task_name: str) -> str | None:
        if not task_name:
            return None
        # Pattern 1: stigrule_123456 -> 123456
        m = re.search(r"stigrule_(\d{4,})", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        # Pattern 2: V-123456 -> 123456
        m = re.search(r"\bV-(\d{4,})\b", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        # Pattern 3: PREFIX-YY-123456 (VCPG-70-000002, PHTN-50-000016, VCEM-70-000001)
        m = re.search(r"\b([A-Z]+-\d+-\d{4,})\b", str(task_name), re.IGNORECASE)
        if m:
            return m.group(1)
        return None

    # ------------------------------------------------------------------
    # ncs_collect payload persistence
    # ------------------------------------------------------------------

    def _persist_host_data(self, host: str, collect_data: dict[str, Any]):
        """Write collection payload and config to the appropriate disk paths."""
        platform = collect_data.get("platform", "unknown")
        name = collect_data.get("name", "raw")
        payload = collect_data.get("payload")
        config = collect_data.get("config")

        report_dir = collect_data.get("report_directory") or DEFAULT_REPORT_DIRECTORY
        target_type = ""
        raw_path = ""
        try:
            if isinstance(name, str) and name.startswith("stig_"):
                target_type = name.replace("stig_", "", 1).strip().lower()
                platform_cfg = self._resolve_platform_for_target(self._platforms_config, target_type)
                paths = platform_cfg.get("paths", {}) if isinstance(platform_cfg, dict) else {}
                raw_template = str(paths.get("raw_stig_artifact", "")).strip()
                if not raw_template:
                    raise RuntimeError(f"Missing paths.raw_stig_artifact for target_type '{target_type}'")
                raw_rel = raw_template.format(
                    report_dir=str(platform_cfg.get("report_dir", "")),
                    hostname=host,
                    schema_name=str(platform_cfg.get("schema_name") or platform_cfg.get("platform") or ""),
                    target_type=target_type,
                    report_stamp="",
                )
                raw_path = self._resolve_under_report_root(report_dir, raw_rel)
                host_dir = os.path.dirname(raw_path)
            else:
                host_rel = os.path.join("platform", str(platform), str(host))
                host_dir = self._resolve_under_report_root(report_dir, host_rel)
        except Exception as e:
            self._display.warning(f"[ncs_collector] Invalid output path for host '{host}' name '{name}': {e}")
            return

        try:
            self._ensure_dir_inherits_parent(host_dir)
        except OSError as e:
            self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
            return

        if payload is not None:
            if not raw_path:
                raw_path = self._resolve_under_report_root(
                    report_dir, os.path.join("platform", str(platform), str(host), f"raw_{name}.yaml")
                )
            envelope: dict[str, Any] = {
                "metadata": {
                    "host": host,
                    "raw_type": name,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "engine": "ncs_collector_callback",
                },
                "data": payload,
            }
            if isinstance(name, str) and name.startswith("stig_"):
                envelope["metadata"]["audit_type"] = name
                envelope["target_type"] = target_type
            self._write_yaml(raw_path, envelope)

        if config:
            config_path = os.path.join(host_dir, "config.yaml")
            config_envelope = {
                "metadata": {
                    "host": host,
                    "type": "config",
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "config": config,
            }
            self._write_yaml(config_path, config_envelope)

    # ------------------------------------------------------------------
    # STIG task telemetry persistence
    # ------------------------------------------------------------------

    def _persist_stig_task_data(self):
        if not self._stig_rules:
            return

        for bucket_key, rules in self._stig_rules.items():
            host, target_type_from_key = bucket_key
            meta = self._stig_meta.get(bucket_key, {})
            platform = meta.get("platform", "vmware")
            target_type = meta.get("target_type", target_type_from_key)

            # For report_dir lookup, check the host directly, then check
            # inventory hosts that map to it (vCenter → ESXi), then env/default.
            report_dir = self._host_report_dirs.get(host)
            if not report_dir:
                for inv_host, target in self._target_host_map.items():
                    if target == host:
                        report_dir = self._host_report_dirs.get(inv_host)
                        if report_dir:
                            break
            if not report_dir:
                report_dir = os.environ.get("NCS_REPORT_DIRECTORY") or DEFAULT_REPORT_DIRECTORY

            try:
                platform_cfg = self._resolve_platform_for_target(self._platforms_config, str(target_type))
            except Exception as exc:
                self._display.warning(
                    f"[ncs_collector] Unknown STIG target_type '{target_type}' while persisting for host '{host}': {exc}"
                )
                continue
            paths = platform_cfg.get("paths", {}) if isinstance(platform_cfg, dict) else {}
            raw_template = str(paths.get("raw_stig_artifact", "")).strip()
            if not raw_template:
                self._display.warning(
                    f"[ncs_collector] Missing paths.raw_stig_artifact for target_type '{target_type}'"
                )
                continue
            raw_rel = raw_template.format(
                report_dir=str(platform_cfg.get("report_dir", "")),
                hostname=host,
                schema_name=str(platform_cfg.get("schema_name") or platform_cfg.get("platform") or ""),
                target_type=str(target_type),
                report_stamp="",
            )
            raw_path = self._resolve_under_report_root(report_dir, raw_rel)
            host_dir = os.path.dirname(raw_path)
            try:
                self._ensure_dir_inherits_parent(host_dir)
            except OSError as e:
                self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
                continue

            rows = []
            for rule_num, status in rules.items():
                rule_id = str(rule_num)
                if "-" not in rule_id:
                    rule_id = f"V-{rule_id}"

                rows.append(
                    {
                        "id": rule_id,
                        "rule_id": rule_id,
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

    # ------------------------------------------------------------------
    # File I/O helpers
    # ------------------------------------------------------------------

    def _write_yaml(self, path: str, data: dict[str, Any]):
        try:
            clean_data = self._to_builtin(data)
            dir_ = os.path.dirname(path) or "."
            with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp", delete=False, encoding="utf-8") as tmp:
                yaml.dump(clean_data, tmp, Dumper=_IndentedDumper, default_flow_style=False, indent=2)
                tmp_path = tmp.name
            os.replace(tmp_path, path)
            self._apply_file_mode_from_parent(path)
            self._display.display(f"[ncs_collector] Persisted data to {path}", color="green")
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

    def _resolve_under_report_root(self, report_root: str, rel_or_abs: str) -> str:
        root_real = os.path.realpath(report_root)
        candidate = rel_or_abs if os.path.isabs(rel_or_abs) else os.path.join(root_real, rel_or_abs)
        cand_real = os.path.realpath(candidate)
        try:
            within = os.path.commonpath([cand_real, root_real]) == root_real
        except ValueError:
            within = False
        if not within:
            raise RuntimeError(f"resolved path escapes report root: {rel_or_abs}")
        return cand_real

    def _to_builtin(self, value: Any) -> Any:
        """Recursively coerce Ansible-tagged values to plain Python builtins."""
        if isinstance(value, dict):
            return {str(k): self._to_builtin(v) for k, v in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [self._to_builtin(v) for v in value]
        if isinstance(value, bool):
            return bool(value)
        if isinstance(value, int):
            return int(value)
        if isinstance(value, float):
            return float(value)
        if isinstance(value, str):
            return str(value)
        if value is None:
            return value
        return str(value)
