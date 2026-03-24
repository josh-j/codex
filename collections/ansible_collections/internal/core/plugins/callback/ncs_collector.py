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

    def increase_indent(self, flow: bool = False, indentless: bool = False):
        return super().increase_indent(flow=flow, indentless=False)


# ---------------------------------------------------------------------------
# Safety net: register YAML representers for Ansible wrapper types so that
# any values that survive _to_builtin() are still serialized as plain
# scalars instead of Python object tags.
# ---------------------------------------------------------------------------
def _ansible_str_representer(dumper, data):
    return dumper.represent_str(str(data))


def _ansible_dict_representer(dumper, data):
    return dumper.represent_dict(dict(data))


def _ansible_list_representer(dumper, data):
    return dumper.represent_list(list(data))


try:
    from ansible.utils.unsafe_proxy import (
        AnsibleUnsafeBytes,
        AnsibleUnsafeText,
    )

    _IndentedDumper.add_representer(AnsibleUnsafeText, _ansible_str_representer)
    _IndentedDumper.add_representer(AnsibleUnsafeBytes, _ansible_str_representer)
except ImportError:
    pass

try:
    from ansible.parsing.yaml.objects import AnsibleMapping, AnsibleSequence, AnsibleUnicode

    _IndentedDumper.add_representer(AnsibleMapping, _ansible_dict_representer)
    _IndentedDumper.add_representer(AnsibleSequence, _ansible_list_representer)
    _IndentedDumper.add_representer(AnsibleUnicode, _ansible_str_representer)
except ImportError:
    pass

try:
    from ansible.vars.hostvars import HostVars, HostVarsVars

    _IndentedDumper.add_representer(HostVars, _ansible_dict_representer)
    _IndentedDumper.add_representer(HostVarsVars, _ansible_dict_representer)
except ImportError:
    pass


DOCUMENTATION = """
    callback: ncs_collector
    type: aggregate
    short_description: Persists NCS raw collection data to disk from host stats
    description:
      - Intercepts 'ncs_collect' data from set_stats and writes it to the reporting directory.
      - Captures STIG task outcomes from runner events and persists them as raw artifacts.
      - Prefers structured STIG results emitted by internal.core.stig when present.
      - Ensures that data collection remains persistent even after the playbook finishes.
"""

DEFAULT_REPORT_DIRECTORY = "/srv/samba/reports"
FILE_MODE_INHERIT_MASK = 0o666

# Status priority: lower number = worse result. When the same rule fires
# multiple times (query, assert, remediate, declarative) we keep the worst.
#
#   failed          (0) — non-compliant, assertion failed or task errored
#   fixed           (1) — remediated (changed in real mode)
#   pass            (2) — compliant, no change needed
#   not_applicable  (3) — control does not apply to this host
#   na              (4) — not reviewed / not assessed (task skipped)
_STATUS_PRIORITY: dict[str, int] = {
    "failed": 0,
    "fixed": 1,
    "pass": 2,
    "not_applicable": 3,
    "na": 4,
}


def _find_repo_root(start_dir: str, max_up: int = 8) -> str:
    """Walk up from *start_dir* looking for a repo root marker.

    Checks both the real path (symlinks resolved) and the logical path
    (symlinks preserved) to handle setups where ``internal/`` is
    symlinked into ``collections/ansible_collections/``.
    """
    candidates = [os.path.realpath(start_dir)]
    logical = os.path.abspath(start_dir)
    if logical != candidates[0]:
        candidates.append(logical)

    for cur in candidates:
        for _ in range(max_up + 1):
            for marker in (
                os.path.join(cur, "collections", "ansible_collections"),
                os.path.join(cur, "files", "ncs_reporter_configs"),
            ):
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


def _load_platforms_from_schema_dir(schema_dir: str) -> list[dict[str, Any]]:
    """Build a platforms list from individual per-platform schema files."""
    platforms: list[dict[str, Any]] = []
    if not os.path.isdir(schema_dir):
        return platforms

    for filename in sorted(os.listdir(schema_dir)):
        if not filename.endswith(".yaml") and not filename.endswith(".yml"):
            continue
        if filename in ("platforms.yaml", "platforms.yml"):
            continue
        if "_fields" in filename or filename.startswith("."):
            continue

        filepath = os.path.join(schema_dir, filename)
        try:
            with open(filepath, encoding="utf-8") as f:
                schema = yaml.safe_load(f) or {}
        except Exception:
            continue

        platform_block = schema.get("platform")
        if not isinstance(platform_block, dict):
            continue

        if "paths" not in platform_block:
            platform_block["paths"] = {
                "raw_stig_artifact": "platform/{report_dir}/{hostname}/raw_stig_{target_type}.yaml",
                "report_fleet": "platform/{report_dir}/{schema_name}_fleet_report.html",
                "report_node_latest": "platform/{report_dir}/{hostname}/health_report.html",
                "report_node_historical": "platform/{report_dir}/{hostname}/health_report_{report_stamp}.html",
                "report_stig_host": "platform/{report_dir}/{hostname}/{hostname}_stig_{target_type}.html",
                "report_search_entry": "platform/{report_dir}/{hostname}/health_report.html",
                "report_site": "site_health_report.html",
                "report_stig_fleet": "stig_fleet_report.html",
            }

        if "schema_name" not in platform_block:
            platform_block["schema_name"] = schema.get("name", filename.replace(".yaml", "").replace(".yml", ""))

        platforms.append(platform_block)

        # Also extract children (or legacy sub_entries) — each inherits
        # parent paths/schema_name but carries its own target_types, etc.
        for sub in platform_block.get("children", platform_block.get("sub_entries", [])):
            if not isinstance(sub, dict):
                continue
            if "target_types" not in sub or not sub["target_types"]:
                continue
            sub_platform = dict(platform_block)
            sub_platform.update(sub)
            sub_platform.pop("sub_entries", None)
            if "paths" not in sub_platform:
                sub_platform["paths"] = platform_block.get("paths", {})
            platforms.append(sub_platform)

    return platforms


def _load_platforms_contract(
    repo_root: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], Callable[[list[dict[str, Any]], str], dict[str, Any]]]:
    path_contract = _import_path_contract_module()

    explicit_cfg = os.environ.get("NCS_PLATFORMS_CONFIG", "").strip()
    if explicit_cfg:
        cfg_path = explicit_cfg
        platforms = path_contract.load_platforms_config_file(cfg_path)
    else:
        cfg_path = os.path.join(repo_root, "files", "ncs_reporter_configs", "platforms.yaml")
        if os.path.isfile(cfg_path):
            platforms = path_contract.load_platforms_config_file(cfg_path)
        else:
            schema_dir = os.path.join(repo_root, "files", "ncs_reporter_configs")
            platforms = _load_platforms_from_schema_dir(schema_dir)
            if not platforms:
                raise RuntimeError(
                    f"No platform configs found. Looked for:\n"
                    f"  1. NCS_PLATFORMS_CONFIG env var (not set)\n"
                    f"  2. {cfg_path} (not found)\n"
                    f"  3. Schema files in {schema_dir} (none found or no 'platform' blocks)"
                )

    target_index = path_contract.build_target_type_index(platforms)
    return platforms, target_index, path_contract.resolve_platform_for_target_type


def _unwrap_custom_stats(raw_custom: dict) -> dict:
    """Unwrap ansible-core stats.custom into a flat {hostname: {var: value}} dict."""
    if not raw_custom:
        return {}

    run_data = raw_custom.get("_run")
    if isinstance(run_data, dict) and run_data:
        return run_data

    return {k: v for k, v in raw_custom.items() if not k.startswith("_")}


class CallbackModule(CallbackBase):
    CALLBACK_VERSION = 2.0
    CALLBACK_TYPE = "aggregate"
    CALLBACK_NAME = "ncs_collector"
    CALLBACK_NEEDS_ENABLED = True

    def __init__(self):
        super().__init__()
        self.repo_root = _find_repo_root(os.path.dirname(__file__))

        # STIG rules keyed by (host, target_type) so each STIG component
        # on the same inventory host gets its own bucket and artifact file.
        self._stig_rules: dict[tuple[str, str], dict[str, str]] = {}
        self._stig_meta: dict[tuple[str, str], dict[str, str]] = {}
        self._stig_result_details: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}

        self._host_report_dirs: dict[str, str] = {}

        # Maps inventory hostname (e.g. vCenter) -> real STIG target.
        self._target_host_map: dict[str, str] = {}

        # Maps inventory hostname -> STIG target type.
        self._target_type_map: dict[str, str] = {}

        try:
            self._platforms_config, self._target_type_index, resolve_fn = _load_platforms_contract(self.repo_root)
            self._resolve_platform_for_target: Callable[[list[dict[str, Any]], str], dict[str, Any]] = resolve_fn
        except Exception as exc:
            self._display.warning(
                f"[ncs_collector] Failed to load platforms config: {exc}. "
                f"STIG task telemetry will not be persisted. "
                f"ncs_collect payloads from set_stats will still be written."
            )
            self._platforms_config = []
            self._target_type_index = {}
            self._resolve_platform_for_target = lambda platforms, tt: (_ for _ in ()).throw(
                RuntimeError(f"No platforms config loaded; cannot resolve target_type '{tt}'")
            )

    # ------------------------------------------------------------------
    # Ansible callback hooks
    # ------------------------------------------------------------------

    def v2_playbook_on_stats(self, stats):
        """End of playbook — persist ncs_collect payloads and STIG telemetry."""
        raw_custom = getattr(stats, "custom", {}) or {}
        all_custom = _unwrap_custom_stats(raw_custom)

        for host in stats.processed.keys():
            custom_stats = all_custom.get(host, {})
            if not custom_stats:
                continue

            collect_keys = [k for k in custom_stats if k.startswith("ncs_collect")]
            if not collect_keys:
                continue

            for collect_key in collect_keys:
                collect_data = custom_stats[collect_key]
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

    def v2_runner_on_failed(self, result, ignore_errors: bool = False):
        self._track_target_context(result)
        self._record_stig_result(result, failed=True, skipped=False)

    def v2_runner_on_skipped(self, result):
        self._track_target_context(result)
        self._record_stig_result(result, failed=False, skipped=True)

    # ------------------------------------------------------------------
    # Target host and type tracking
    # ------------------------------------------------------------------

    def _track_target_context(self, result):
        """Capture _ncs_stig_target_host and _ncs_stig_target_type from set_fact results."""
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
    # Structured STIG result handling (preferred for internal.core.stig)
    # ------------------------------------------------------------------

    def _extract_structured_stig_result(self, result_data: dict[str, Any]) -> dict[str, Any] | None:
        """Return structured STIG payload from wrapper results if present."""
        if not isinstance(result_data, dict):
            return None

        stig = result_data.get("stig")
        if isinstance(stig, dict) and stig.get("status"):
            return stig

        # Allow future alternate result keys if needed.
        for value in result_data.values():
            if isinstance(value, dict) and value.get("status") and value.get("phase") and value.get("reason"):
                if {"id", "status", "phase", "reason"} & set(value.keys()):
                    return value

        return None

    def _map_structured_status(self, status: str) -> str:
        """
        Map wrapper statuses into collector statuses.

        Supported wrapper statuses:
          pass, fail, fixed, not_applicable, na, skipped, error
        """
        normalized = str(status or "").strip().lower()

        mapping = {
            "pass": "pass",
            "fixed": "fixed",
            "fix": "fixed",
            "fail": "failed",
            "failed": "failed",
            "not_applicable": "not_applicable",
            "na": "na",
            "skipped": "na",
            "error": "failed",
        }
        return mapping.get(normalized, "failed")

    def _record_structured_stig_result(
        self,
        *,
        result,
        result_data: dict[str, Any],
        structured: dict[str, Any],
    ) -> bool:
        """
        Consume structured result emitted by internal.core.stig.

        Returns True if handled, False if callback should fall back to legacy parsing.
        """
        task = getattr(result, "_task", None)
        if task is None:
            return False

        task_vars = getattr(task, "vars", {}) or {}

        try:
            inv_host = result._host.get_name()
        except Exception:
            inv_host = "unknown"

        # Resolve target host/type from task vars first, then tracked maps.
        host = task_vars.get("stig_target_host") or self._target_host_map.get(inv_host, inv_host)
        target_type = str(task_vars.get("stig_target_type") or self._target_type_map.get(inv_host, "") or "").lower()

        if not target_type:
            self._debug_stig_event(
                "structured-skip-no-target-type",
                task_name=getattr(task, "name", ""),
                structured=structured,
            )
            return False

        try:
            platform_cfg = self._resolve_platform_for_target(self._platforms_config, target_type)
        except Exception as exc:
            self._display.warning(
                f"[ncs_collector] Unknown STIG target_type '{target_type}' for structured result "
                f"on task '{getattr(task, 'name', '')}': {exc}"
            )
            return True

        platform_report_dir = str(platform_cfg.get("report_dir", "")).strip()
        if not platform_report_dir:
            self._display.warning(
                f"[ncs_collector] Missing report_dir for target_type '{target_type}' in platforms config"
            )
            return True

        rule_num = structured.get("id")
        if rule_num is not None:
            rule_num = str(rule_num).strip()

        if not rule_num:
            rule_num = self._extract_rule_number(getattr(task, "name", "") or "")

        if not rule_num:
            self._debug_stig_event(
                "structured-skip-no-rule",
                task_name=getattr(task, "name", ""),
                structured=structured,
                target_type=target_type,
            )
            return True

        status = self._map_structured_status(structured.get("status", "failed"))

        bucket_key = (str(host), str(target_type))
        host_rules = self._stig_rules.setdefault(bucket_key, {})

        existing = host_rules.get(rule_num)
        if existing is None or _STATUS_PRIORITY.get(status, 99) < _STATUS_PRIORITY.get(existing, 99):
            host_rules[rule_num] = status

        self._stig_meta[bucket_key] = {
            "platform": platform_report_dir,
            "target_type": str(target_type),
        }

        detail_bucket = self._stig_result_details.setdefault(bucket_key, {})
        existing_detail = detail_bucket.get(rule_num)
        if existing_detail is None or _STATUS_PRIORITY.get(status, 99) <= _STATUS_PRIORITY.get(existing_detail.get("status"), 99):
            detail_bucket[rule_num] = {
                "status": status,
                "reason": structured.get("reason", ""),
                "phase": structured.get("phase", ""),
                "task_name": getattr(task, "name", ""),
            }

        self._debug_stig_event(
            "structured-recorded",
            host=host,
            target_type=target_type,
            rule_num=rule_num,
            status=status,
            task_name=getattr(task, "name", ""),
            structured_status=structured.get("status"),
            reason=structured.get("reason"),
        )
        return True

    # ------------------------------------------------------------------
    # STIG result recording (from runner events)
    # ------------------------------------------------------------------

    def _record_stig_result(self, result, failed: bool = False, skipped: bool = False):
        task = getattr(result, "_task", None)
        if task is None:
            return

        task_name = getattr(task, "name", "") or ""
        result_data = getattr(result, "_result", {}) or {}

        # Aggregate loop results: fan them out and process each child independently.
        nested_results = result_data.get("results")
        if isinstance(nested_results, list) and nested_results:
            for child in nested_results:
                if not isinstance(child, dict):
                    continue

                child_failed = bool(child.get("failed", False))
                child_skipped = bool(child.get("skipped", False))

                if "_assert" in task_name and child.get("evaluated_to") is False:
                    child_failed = True

                self._record_stig_result_payload(
                    result=result,
                    task_name=task_name,
                    result_data=child,
                    failed=child_failed,
                    skipped=child_skipped,
                )
            return

        self._record_stig_result_payload(
            result=result,
            task_name=task_name,
            result_data=result_data,
            failed=failed,
            skipped=skipped,
        )

    def _record_stig_result_payload(
        self,
        *,
        result,
        task_name: str,
        result_data: dict[str, Any],
        failed: bool,
        skipped: bool,
    ) -> None:
        task = getattr(result, "_task", None)
        if task is None:
            return

        structured = self._extract_structured_stig_result(result_data)
        if structured:
            if self._record_structured_stig_result(
                result=result,
                result_data=result_data,
                structured=structured,
            ):
                return

        # When no_log censors the result, the structured stig data is hidden.
        # Without it we cannot determine compliance, so skip rather than
        # inferring a false "pass" from an ok/unchanged censored result.
        if result_data.get("censored"):
            return

        # Detect assert tasks using ignore_errors that actually failed.
        if not failed and not skipped and "_assert" in task_name:
            if result_data.get("evaluated_to") is False:
                failed = True

        task_vars = getattr(task, "vars", {}) or {}

        # Resolve target type.
        target_type = str(task_vars.get("stig_target_type", "") or "").lower()
        if not target_type:
            try:
                inv_host = result._host.get_name()
            except Exception:
                inv_host = "unknown"
            target_type = self._target_type_map.get(inv_host, "")
            if not target_type:
                self._debug_stig_event(
                    "skip-no-target-type",
                    task_name=task_name,
                    result_data=result_data,
                )
                return

        # Prefer explicit loop/result metadata over generic task names.
        rule_num = self._extract_rule_number_from_result(result_data)
        if not rule_num:
            rule_num = self._extract_rule_number(task_name)

        if not rule_num and target_type in {"vcsa", "vcenter"} and task_name:
            digest = hashlib.sha1(task_name.encode("utf-8")).hexdigest()
            rule_num = f"9{(int(digest[:8], 16) % 99999):05d}"

        if not rule_num:
            self._debug_stig_event(
                "skip-no-rule",
                task_name=task_name,
                result_data=result_data,
                target_type=target_type,
            )
            return

        phase = self._detect_phase(task_name)

        # Ignore pre-check/query style tasks that should not set final status.
        if phase in ("alias", "reset", "eval_remediate", "query", "check"):
            self._debug_stig_event(
                "skip-phase",
                task_name=task_name,
                rule_num=rule_num,
                phase=phase,
                skipped=skipped,
                failed=failed,
            )
            return

        # Resolve target host.
        host = task_vars.get("stig_target_host")
        if not host:
            try:
                inv_host = result._host.get_name()
            except Exception:
                inv_host = "unknown"
            host = self._target_host_map.get(inv_host, inv_host)

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

        changed = bool(result_data.get("changed", False))

        # ---------------------------------------------------------------
        # Status determination
        # ---------------------------------------------------------------
        # Detect explicit "not applicable" tasks: the task ran successfully
        # and its name contains _not_applicable. This means the control
        # does not apply to this host (e.g. GDM/dconf controls on a
        # headless server without gdm3 installed).
        is_not_applicable_task = "_not_applicable" in task_name

        if is_not_applicable_task and not failed and not skipped:
            # Task ran and passed → control confirmed as not applicable
            status = "not_applicable"
        elif skipped:
            # Task was skipped (phase gating, when-clause, etc.)
            status = "na"
        elif failed:
            status = "failed"
        elif phase == "assert":
            # Assertion passed (if it failed, caught above)
            status = "pass"
        elif phase == "remediate":
            # In audit/check mode, a remediation task that would change
            # the system indicates non-compliance, not a fix.
            status = "fixed" if changed else "pass"
        else:
            # Declarative tasks (lineinfile, service, copy, etc.)
            status = "fixed" if changed else "pass"

        bucket_key = (str(host), str(target_type))
        host_rules = self._stig_rules.setdefault(bucket_key, {})

        existing = host_rules.get(rule_num)
        if existing is None or _STATUS_PRIORITY.get(status, 99) < _STATUS_PRIORITY.get(existing, 99):
            host_rules[rule_num] = status

        self._stig_meta[bucket_key] = {
            "platform": platform_report_dir,
            "target_type": str(target_type),
        }

        self._debug_stig_event(
            "recorded",
            host=host,
            target_type=target_type,
            rule_num=rule_num,
            phase=phase,
            status=status,
            changed=changed,
            skipped=skipped,
            failed=failed,
            task_name=task_name,
        )

    # ------------------------------------------------------------------
    # Rule and phase extraction
    # ------------------------------------------------------------------

    def _detect_phase(self, task_name: str) -> str:
        """Classify a task name into a STIG result phase."""
        if not task_name:
            return "declarative"

        # Explicit "not_applicable" tasks are treated as assert-like for
        # phase purposes — they produce a definitive finding status.
        if "_not_applicable" in task_name:
            return "not_applicable"

        for suffix in ("query", "assert", "remediate", "reset", "alias", "eval_remediate"):
            if task_name.endswith(f"_{suffix}") or f"_{suffix}_" in task_name:
                return suffix

        # Support roles that use "_check" in task names.
        for suffix in ("_check", "_assert", "_remediate"):
            if suffix in task_name:
                return suffix.lstrip("_")

        return "declarative"

    def _extract_rule_number(self, task_name: str) -> str | None:
        if not task_name:
            return None

        text = str(task_name).strip()

        # Pattern 1: stigrule_270773a / stigrule_270773 / stigrule_270773_b -> 270773
        m = re.search(r"stigrule_(\d{4,})[A-Za-z]?(?:\b|_)", text, re.IGNORECASE)
        if m:
            return m.group(1)

        # Pattern 2: V-123456 -> 123456
        m = re.search(r"\bV-(\d{4,})\b", text, re.IGNORECASE)
        if m:
            return m.group(1)

        # Pattern 3: PREFIX-YY-123456 (VCPG-70-000002, PHTN-30-000016, VCEM-70-000001)
        # Use (?:^|[\s_]) instead of \b to also match after underscore (stigrule_PHTN-30-...)
        m = re.search(r"(?:^|[\s_])([A-Z]+-\d+-\d{4,})\b", text, re.IGNORECASE)
        if m:
            return m.group(1)

        # Pattern 4: bare numeric-ish loop label, including 270773a -> 270773
        m = re.fullmatch(r"(\d{4,})[A-Za-z]?", text)
        if m:
            return m.group(1)

        return None

    def _extract_rule_number_from_result(self, result_data: dict[str, Any]) -> str | None:
        if not isinstance(result_data, dict):
            return None

        # 1. Honor custom loop_var names first.
        loop_var_name = result_data.get("ansible_loop_var")
        if isinstance(loop_var_name, str) and loop_var_name:
            loop_item = result_data.get(loop_var_name)
            rule_num = self._extract_rule_number_from_loop_item(loop_item)
            if rule_num:
                return rule_num

        # 2. Standard loop item.
        rule_num = self._extract_rule_number_from_loop_item(result_data.get("item"))
        if rule_num:
            return rule_num

        # 3. Nested aggregate results.
        nested_results = result_data.get("results")
        if isinstance(nested_results, list):
            for entry in nested_results:
                rule_num = self._extract_rule_number_from_loop_item(entry)
                if rule_num:
                    return rule_num

        # 4. Display label fallback.
        item_label = result_data.get("_ansible_item_label")
        if isinstance(item_label, str) and item_label.strip():
            rule_num = self._extract_rule_number(item_label)
            if rule_num:
                return rule_num

        # 5. Direct keys on result data.
        for key in ("id", "rule_id", "rule_num", "rule", "vuln_id"):
            value = result_data.get(key)
            if value is None:
                continue
            value_str = str(value).strip()
            m = re.fullmatch(r"(\d{4,})[A-Za-z]?", value_str)
            if m:
                return m.group(1)
            rule_num = self._extract_rule_number(value_str)
            if rule_num:
                return rule_num

        return None

    def _extract_rule_number_from_loop_item(self, loop_item: Any) -> str | None:
        """Extract a STIG rule id from nested loop payloads, preferring explicit item.id."""
        if isinstance(loop_item, dict):
            # 1. Deepest nested registered-loop-result shape first: {item: {...}}
            inner_item = loop_item.get("item")
            if inner_item is not None:
                extracted = self._extract_rule_number_from_loop_item(inner_item)
                if extracted:
                    return extracted

            # 2. Explicit rule/id keys on the current object
            for key in ("id", "rule_id", "rule_num", "rule", "vuln_id"):
                value = loop_item.get(key)
                if value is None:
                    continue
                value_str = str(value).strip()

                m = re.fullmatch(r"(\d{4,})[A-Za-z]?", value_str)
                if m:
                    return m.group(1)

                extracted = self._extract_rule_number(value_str)
                if extracted:
                    return extracted

            # 3. Labels/names are lower-confidence than explicit id fields
            for key in ("_ansible_item_label", "name", "label", "msg"):
                value = loop_item.get(key)
                if isinstance(value, str) and value.strip():
                    extracted = self._extract_rule_number(value.strip())
                    if extracted:
                        return extracted

        elif isinstance(loop_item, str):
            extracted = self._extract_rule_number(loop_item.strip())
            if extracted:
                return extracted

        return None

    # ------------------------------------------------------------------
    # ncs_collect payload persistence
    # ------------------------------------------------------------------

    def _persist_host_data(self, host: str, collect_data: dict[str, Any]):
        """Write collection payload and config to disk."""
        platform_dir = collect_data.get("platform_dir", collect_data.get("platform", "unknown"))
        payload = collect_data.get("payload")
        config = collect_data.get("config")
        artifact_name = collect_data.get("name", "raw")

        report_dir = collect_data.get("report_directory") or DEFAULT_REPORT_DIRECTORY

        try:
            host_rel = os.path.join("platform", str(platform_dir), str(host))
            host_dir = self._resolve_under_report_root(report_dir, host_rel)
        except Exception as e:
            self._display.warning(f"[ncs_collector] Invalid output path for host '{host}': {e}")
            return

        try:
            self._ensure_dir_inherits_parent(host_dir)
        except OSError as e:
            self._display.warning(f"[ncs_collector] Could not create directory {host_dir}: {e}")
            return

        if payload is not None:
            raw_path = os.path.join(host_dir, f"raw_{artifact_name}.yaml")
            envelope: dict[str, Any] = {
                "metadata": {
                    "host": host,
                    "raw_type": artifact_name,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "engine": "ncs_collector_callback",
                },
                "data": payload,
            }
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
            target_type = meta.get("target_type", target_type_from_key)

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

            rows: list[dict[str, Any]] = []
            timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            detail_bucket = self._stig_result_details.get(bucket_key, {})

            for rule_num, status in rules.items():
                rule_id = str(rule_num)
                if "-" not in rule_id:
                    rule_id = f"V-{rule_id}"

                status_label = {
                    "pass": "Compliant",
                    "failed": "Non-Compliant",
                    "fixed": "Remediated to Compliant",
                    "not_applicable": "Not Applicable",
                    "na": "Not Reviewed",
                }.get(status, status)

                detail = detail_bucket.get(rule_num, {})
                reason = str(detail.get("reason", "")).strip()

                finding_detail = (
                    f"Automated compliance check performed by NCS Automation "
                    f"against {host} ({target_type}). "
                    f"Result: {status_label}. "
                    f"Timestamp: {timestamp}."
                )
                if reason:
                    finding_detail += f" Reason: {reason}"

                comment = f"Reviewed by NCS Automation: {status_label}. Checked {timestamp}."
                if reason:
                    comment += f" Reason: {reason}"

                worst_phase = str(detail.get("phase", "")).strip()

                rows.append(
                    {
                        "id": rule_id,
                        "rule_id": rule_id,
                        "rule_ref": f"stigrule_{rule_num}",
                        "name": host,
                        "status": status,
                        "title": "",
                        "severity": "",
                        "checktext": "",
                        "fixtext": "",
                        "finding_details": finding_detail,
                        "comments": comment,
                        "worst_phase": worst_phase,
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
        type_name = type(value).__name__

        if type_name.startswith("Ansible") or type_name.startswith("HostVars"):
            if isinstance(value, dict):
                return {str(k): self._to_builtin(v) for k, v in value.items()}
            if isinstance(value, (list, tuple)):
                return [self._to_builtin(v) for v in value]
            if isinstance(value, bytes):
                return value.decode("utf-8", errors="replace")
            if isinstance(value, bool):
                return bool(value)
            if isinstance(value, int):
                return int(value)
            if isinstance(value, float):
                return float(value)
            return str(value)

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

    def _debug_stig_event(self, event: str, **fields: Any) -> None:
        if os.environ.get("NCS_COLLECTOR_DEBUG_STIG", "").strip().lower() not in {"1", "true", "yes", "on"}:
            return

        safe_fields = {k: self._to_builtin(v) for k, v in fields.items()}
        self._display.display(
            f"[ncs_collector][debug] {event}: {safe_fields}",
            color="blue",
        )
