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
      - "Output layout: when the collect payload includes tree_path (a list of slug segments),
        the bundle lands at <report_root>/<*tree_path>/raw.yaml. When absent, falls back to
        the legacy platform/<platform_dir>/<host>/raw_<type>.yaml layout."
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
#   na              (4) — gate skipped (prerequisite not met)
#   not_reviewed    (5) — control disabled via _stig_manage=false
_STATUS_PRIORITY: dict[str, int] = {
    "failed": 0,
    "fixed": 1,
    "pass": 2,
    "not_applicable": 3,
    "na": 4,
    "not_reviewed": 5,
}

# Wrapper status → collector status.
_STATUS_MAP: dict[str, str] = {
    "pass": "pass",
    "fixed": "fixed",
    "fix": "fixed",
    "fail": "failed",
    "failed": "failed",
    "not_applicable": "not_applicable",
    "na": "na",
    "skipped": "na",
    "not_reviewed": "not_reviewed",
    "error": "failed",
}


def _resolved_or_empty(val: Any) -> str:
    """Return *val* as a string, or ``""`` if it contains unresolved Jinja2."""
    if not val:
        return ""
    s = str(val)
    if "{{" in s and "}}" in s:
        return ""
    return s


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
                os.path.join(cur, "files", "ncs-reporter_configs"),
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
        if any(x in filename for x in ("_fields", "_alerts", "_widgets")) or filename.startswith("."):
            continue

        filepath = os.path.join(schema_dir, filename)
        try:
            with open(filepath, encoding="utf-8") as f:
                schema = yaml.safe_load(f) or {}
        except Exception:
            continue

        if not isinstance(schema, dict):
            continue

        # Unwrap config: wrapper (NCS configs nest platform under config:)
        if "config" in schema and isinstance(schema["config"], dict):
            schema = {**schema["config"], **{k: v for k, v in schema.items() if k != "config"}}

        platform_block = schema.get("platform")
        if isinstance(platform_block, str) and platform_block:
            platform_block = {"input_dir": platform_block, "report_dir": platform_block, "name": platform_block.split("/")[0]}
        elif isinstance(platform_block, dict):
            # Handle dict form: {path: "linux/photon", render: false}
            p_path = platform_block.get("path") or platform_block.get("report_dir") or platform_block.get("input_dir") or ""
            if p_path and "report_dir" not in platform_block:
                platform_block["report_dir"] = p_path
            if p_path and "input_dir" not in platform_block:
                platform_block["input_dir"] = p_path
            if p_path and "name" not in platform_block:
                platform_block["name"] = p_path.split("/")[0]
        if not isinstance(platform_block, dict):
            continue

        if "paths" not in platform_block:
            platform_block["paths"] = {
                "raw_stig_artifact": "platform/{report_dir}/{hostname}/raw_stig_{target_type}.yaml",
                "report_fleet": "platform/{report_dir}/{schema_name}_inventory.html",
                "report_node_latest": "platform/{report_dir}/{hostname}/{hostname}.html",
                "report_node_historical": "platform/{report_dir}/{hostname}/{hostname}_{report_stamp}.html",
                "report_stig_host": "platform/{report_dir}/{hostname}/{hostname}_stig_{target_type}.html",
                "report_search_entry": "platform/{report_dir}/{hostname}/{hostname}.html",
                "report_site": "site.html",
                "report_stig_fleet": "site.stig.html",
            }

        if "schema_name" not in platform_block:
            platform_block["schema_name"] = schema.get("name", filename.replace(".yaml", "").replace(".yml", ""))

        # Extract STIG target_types from config if not already set
        if "target_types" not in platform_block:
            stig_cfg = schema.get("stig", {})
            if isinstance(stig_cfg, dict):
                r2p = stig_cfg.get("rule_prefix_to_platform", {})
                p2c = stig_cfg.get("platform_to_checklist", {})
                if isinstance(r2p, dict) and r2p:
                    platform_block["target_types"] = sorted(set(r2p.values()))
                elif isinstance(p2c, dict) and p2c:
                    platform_block["target_types"] = sorted(p2c.keys())

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
        if os.path.isdir(explicit_cfg):
            platforms = _load_platforms_from_schema_dir(explicit_cfg)
        else:
            platforms = path_contract.load_platforms_config_file(explicit_cfg)
    else:
        candidates = [repo_root]
        platforms: list[dict[str, Any]] = []
        searched: list[str] = []
        for root in candidates:
            cfg_path = os.path.join(root, "files", "ncs-reporter_configs", "platforms.yaml")
            if os.path.isfile(cfg_path):
                platforms = path_contract.load_platforms_config_file(cfg_path)
                break
            schema_dir = os.path.join(root, "files", "ncs-reporter_configs")
            if os.path.isdir(schema_dir):
                platforms = _load_platforms_from_schema_dir(schema_dir)
                if platforms:
                    break
            searched.append(schema_dir)

        # Last resort: try the ncs-reporter package's bundled configs directly
        if not platforms:
            try:
                import ncs_reporter  # noqa: F811

                pkg_configs = os.path.join(os.path.dirname(ncs_reporter.__file__), "configs")
                if os.path.isdir(pkg_configs):
                    platforms = _load_platforms_from_schema_dir(pkg_configs)
                    searched.append(pkg_configs)
            except ImportError:
                pass

        if not platforms:
            raise RuntimeError(
                "No platform configs found. Searched:\n"
                + "\n".join(f"  - {s}" for s in searched)
                + "\nSet NCS_REPO_ROOT or NCS_PLATFORMS_CONFIG env var."
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
        self.repo_root = os.environ.get("NCS_REPO_ROOT", "").strip() or _find_repo_root(os.path.dirname(__file__))

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
            if self._target_type_index:
                self._display.v(
                    f"[ncs_collector] Loaded platform configs. "
                    f"target_types={sorted(self._target_type_index.keys())}"
                )
            else:
                self._display.warning(
                    f"[ncs_collector] Platform configs loaded but no target_types found. "
                    f"STIG telemetry may not persist. repo_root={self.repo_root!r}"
                )
        except Exception as exc:
            self._display.warning(
                f"[ncs_collector] Failed to load platforms config: {exc}. "
                f"repo_root={self.repo_root!r}. Set NCS_REPO_ROOT env var to override. "
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
        # Coerce tagged Ansible types (AnsibleTaggedList, etc.) to plain
        # Python builtins before any dict traversal — tagged lists don't
        # have .get() and will crash downstream code that expects dicts.
        all_custom = self._to_builtin(_unwrap_custom_stats(raw_custom))

        for host in stats.processed.keys():
            custom_stats = all_custom.get(host, {})
            if not custom_stats or not isinstance(custom_stats, dict):
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
          pass, fail, fixed, not_applicable, na, skipped, not_reviewed, error
        """
        normalized = str(status or "").strip().lower()
        return _STATUS_MAP.get(normalized, "failed")

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

        # Resolve target host/type from structured result first, then task vars, then tracked maps.
        # Guard against raw Jinja2 from AnsibleUnsafeText (include_tasks apply: vars:).
        host = (
            _resolved_or_empty(structured.get("target_host"))
            or _resolved_or_empty(task_vars.get("stig_target_host"))
            or self._target_host_map.get(inv_host, inv_host)
        )
        target_type = str(
            _resolved_or_empty(structured.get("target_type"))
            or _resolved_or_empty(task_vars.get("stig_target_type"))
            or self._target_type_map.get(inv_host, "")
            or ""
        ).lower()

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
        host = _resolved_or_empty(task_vars.get("stig_target_host"))
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
        """Write collection payload and config to disk.

        When ``per_host_split`` is present in *collect_data*, the payload is
        split into per-host entries and each is persisted under its own
        directory.  This is used for ESXi collection where data is gathered
        via vCenter but should be stored per-ESXi-host.

        ``per_host_split`` is a dict with:
        - ``list_path``: dot-separated path into the payload to a list or
          dict-of-lists whose inner results contain per-host entries.
        - ``name_key``: key within each entry that holds the hostname
          (e.g. ``"item"`` for Ansible loop results).
        """
        split_cfg = collect_data.get("per_host_split")
        if isinstance(split_cfg, dict):
            self._persist_host_data_split(host, collect_data, split_cfg)
            return

        self._persist_single_host(host, collect_data)

    def _persist_host_data_split(
        self,
        ansible_host: str,
        collect_data: dict[str, Any],
        split_cfg: dict[str, str],
    ):
        """Split payload into per-host entries and persist each separately."""
        payload = collect_data.get("payload")
        if not isinstance(payload, dict):
            self._display.warning(
                f"[ncs_collector] per_host_split requires a dict payload for '{ansible_host}'"
            )
            self._persist_single_host(ansible_host, collect_data)
            return

        list_path = str(split_cfg.get("list_path", "")).strip()
        name_key = str(split_cfg.get("name_key", "item")).strip()
        if not list_path:
            self._display.warning(
                f"[ncs_collector] per_host_split missing list_path for '{ansible_host}'"
            )
            self._persist_single_host(ansible_host, collect_data)
            return

        # Navigate into the payload to find the list
        obj: Any = payload
        path_resolved = True
        for part in list_path.split("."):
            if isinstance(obj, dict):
                if part in obj:
                    obj = obj[part]
                else:
                    path_resolved = False
                    obj = {}
                    break
            else:
                path_resolved = False
                obj = {}
                break

        # Extract list items (handle Ansible register format with .results)
        items: list[dict[str, Any]] = []
        if isinstance(obj, dict) and "results" in obj:
            items = obj.get("results", [])
        elif isinstance(obj, list):
            items = obj
        elif isinstance(obj, dict):
            items = list(obj.values()) if obj else []

        if not items:
            if not path_resolved:
                self._display.warning(
                    f"[ncs_collector] per_host_split could not resolve path '{list_path}' for '{ansible_host}'"
                )
            else:
                self._display.v(
                    f"[ncs_collector] per_host_split found no items at '{list_path}' for '{ansible_host}' (empty collection)"
                )
            self._persist_single_host(ansible_host, collect_data)
            return

        # Persist each host entry
        persisted = 0
        for entry in items:
            if not isinstance(entry, dict):
                continue
            # Unwrap Ansible retry wrapper — when retries/until are used on a
            # loop task, each result entry has an 'attempts' list containing the
            # actual task result(s).  Use the last successful attempt.
            if "attempts" in entry and isinstance(entry["attempts"], list):
                for attempt in reversed(entry["attempts"]):
                    if isinstance(attempt, dict) and not attempt.get("failed"):
                        # Merge attempt data into entry (item, ansible_facts, etc.)
                        merged = dict(entry)
                        merged.update(attempt)
                        merged.pop("attempts", None)
                        entry = merged
                        break
            if entry.get("failed") or entry.get("skipped"):
                continue
            entry_host = str(entry.get(name_key, "")).strip()
            if not entry_host:
                continue

            # Write per-host payload with assembled data.
            per_host_data = dict(collect_data)
            per_host_data.pop("per_host_split", None)
            # Build assembled payload for this host from full context + entry
            per_host_data["payload"] = self._assemble_split_host_payload(
                entry, entry_host, payload, split_cfg,
            )

            # When the parent emission set a tree_path AND declared
            # tree_path_host_keys, extend the per-host tree_path by pulling
            # those keys from the assembled payload (slugified) and append
            # the hostname. This lands each host at a deep tree node like
            # vsphere/<vc>/<dc>/<cluster>/<host>/raw.yaml.
            host_keys = collect_data.get("tree_path_host_keys")
            parent_tp = self._sanitize_tree_path(collect_data.get("tree_path"))
            if parent_tp and isinstance(host_keys, (list, tuple)) and host_keys:
                segments = list(parent_tp)
                assembled = per_host_data["payload"] if isinstance(per_host_data.get("payload"), dict) else {}
                for key in host_keys:
                    raw_val = assembled.get(key) if isinstance(key, str) else None
                    slug = self._slugify(str(raw_val)) if raw_val else ""
                    if slug:
                        segments.append(slug)
                segments.append(entry_host)
                per_host_data["tree_path"] = segments

            self._persist_single_host(entry_host, per_host_data)
            persisted += 1

        if persisted == 0:
            self._display.warning(
                f"[ncs_collector] per_host_split yielded no valid hosts for '{ansible_host}'"
            )
            self._persist_single_host(ansible_host, collect_data)
        else:
            self._display.display(
                f"[ncs_collector] Split '{ansible_host}' into {persisted} per-host entries",
                color="cyan",
            )

    @staticmethod
    def _assemble_split_host_payload(
        entry: dict[str, Any],
        hostname: str,
        full_payload: dict[str, Any],
        split_cfg: dict[str, str],
    ) -> dict[str, Any]:
        """Assemble a flat per-host payload from a loop entry + full context.

        Extracts this host's ansible_facts from the entry, then merges
        related per-host data (NICs, services) and shared context (clusters)
        from the full payload. Returns a flat dict ready for the reporter.
        """
        facts = entry.get("ansible_facts", {})
        if not isinstance(facts, dict):
            facts = {}

        def _safe_float(v: Any, d: float = 0.0) -> float:
            try:
                return float(v)
            except (TypeError, ValueError):
                return d

        def _safe_int(v: Any, d: int = 0) -> int:
            try:
                return int(v)
            except (TypeError, ValueError):
                return d

        # Core host metrics from ansible_facts
        mem_total = _safe_float(facts.get("ansible_memtotal_mb", 0))
        mem_free = _safe_float(facts.get("ansible_memfree_mb", 0))
        mem_used = mem_total - mem_free

        assembled: dict[str, Any] = {
            "name": hostname,
            "version": facts.get("ansible_distribution_version", ""),
            "build": facts.get("ansible_distribution_build", ""),
            "connection_state": facts.get("ansible_host_connection_state", "unknown"),
            "overall_status": facts.get("ansible_overall_status", "unknown"),
            "in_maintenance_mode": facts.get("ansible_in_maintenance_mode", False),
            "lockdown_mode": facts.get("ansible_lockdown_mode", "unknown"),
            "mem_mb_total": mem_total,
            "mem_mb_used": mem_used,
            "mem_used_pct": round((mem_used / mem_total) * 100, 1) if mem_total > 0 else 0.0,
            "cpu_used_pct": _safe_float(facts.get("ansible_cpu_used_pct", 0.0)),
            "vm_count": _safe_int(facts.get("ansible_vm_count", 0)),
            "uptime_seconds": _safe_int(facts.get("ansible_uptime", 0)),
            "ssh_enabled": False,
            "shell_enabled": False,
            "ntp_running": False,
            "datastores": [],
            "nics": [],
            "vmknics": [],
            "hardware_alerts": [],
            "cluster": "",
            "datacenter": "",
        }

        def _safe_dict(val: Any) -> dict:
            return val if isinstance(val, dict) else {}

        def _safe_list(val: Any) -> list:
            return val if isinstance(val, list) else []

        # Datastores from facts
        for ds in _safe_list(facts.get("ansible_datastore")):
            if isinstance(ds, dict):
                assembled["datastores"].append({
                    "name": ds.get("name", ""), "total": ds.get("total", ""), "free": ds.get("free", ""),
                })

        # Merge NIC info from full payload
        # hosts_info values are already unwrapped .results lists from the collect play.
        hosts_info = _safe_dict(full_payload.get("hosts_info"))
        if hosts_info:
            for nic_result in _safe_list(hosts_info.get("host_nics")):
                if not isinstance(nic_result, dict):
                    continue
                host_nics = _safe_dict(_safe_dict(nic_result.get("hosts_vmnic_info")).get(hostname))
                for nic in _safe_list(host_nics.get("vmnic_details")):
                    if isinstance(nic, dict):
                        assembled["nics"].append({
                            "device": nic.get("device", ""),
                            "link_status": nic.get("status", "unknown"),
                            "speed_mbps": _safe_int(nic.get("speed", 0)),
                            "driver": nic.get("driver", ""),
                            "switch": nic.get("vswitch", ""),
                        })

            # Merge service info from full payload
            for svc_result in _safe_list(hosts_info.get("host_services")):
                if not isinstance(svc_result, dict):
                    continue
                host_svcs = _safe_dict(svc_result.get("host_service_info")).get(hostname, [])
                for svc in _safe_list(host_svcs):
                    if isinstance(svc, dict):
                        key = svc.get("key", "")
                        if key == "TSM-SSH":
                            assembled["ssh_enabled"] = svc.get("running", False)
                        elif key == "TSM":
                            assembled["shell_enabled"] = svc.get("running", False)
                        elif key == "ntpd":
                            assembled["ntp_running"] = svc.get("running", False)

            # Merge extended host properties (lockdown, status, CPU usage, VM count)
            for ext_result in _safe_list(hosts_info.get("host_extended")):
                if not isinstance(ext_result, dict) or ext_result.get("item") != hostname:
                    continue
                ext_facts = _safe_dict(ext_result.get("ansible_facts"))
                summary = _safe_dict(ext_facts.get("summary"))
                config = _safe_dict(ext_facts.get("config"))
                hw = _safe_dict(summary.get("hardware"))
                qs = _safe_dict(summary.get("quickStats"))

                overall = summary.get("overallStatus", "")
                if overall:
                    assembled["overall_status"] = overall

                lockdown = config.get("lockdownMode", "")
                if lockdown:
                    assembled["lockdown_mode"] = lockdown

                cpu_mhz_used = _safe_float(qs.get("overallCpuUsage", 0))
                cpu_mhz_per_core = _safe_float(hw.get("cpuMhz", 0))
                cpu_cores = _safe_int(hw.get("numCpuCores", 0))
                cpu_total = cpu_mhz_per_core * cpu_cores
                if cpu_total > 0:
                    assembled["cpu_used_pct"] = round((cpu_mhz_used / cpu_total) * 100, 1)

                vms = ext_facts.get("vm")
                if isinstance(vms, list):
                    assembled["vm_count"] = len(vms)
                break

        # Merge cluster context from full payload
        for dc_result in _safe_list(_safe_dict(full_payload.get("clusters_info")).get("results")):
            if not isinstance(dc_result, dict):
                continue
            datacenter = dc_result.get("item", "")
            clusters = dc_result.get("clusters_info") or dc_result.get("clusters") or {}
            if isinstance(clusters, dict):
                for cluster_name, cluster_data in clusters.items():
                    if isinstance(cluster_data, dict):
                        for host in _safe_list(cluster_data.get("hosts")):
                            if isinstance(host, dict) and host.get("name") == hostname:
                                assembled["cluster"] = cluster_name
                                assembled["datacenter"] = datacenter

        return assembled

    def _persist_single_host(self, host: str, collect_data: dict[str, Any]):
        """Write collection payload and config to disk for a single host.

        Path layout: when ``collect_data['tree_path']`` is a non-empty list
        of slug segments, the bundle lands at
        ``<report_root>/<*tree_path>/raw.yaml`` (and config at
        ``<report_root>/<*tree_path>/config.yaml``). This is the hierarchical
        layout the reporter expects for the tree-model view.

        Fallback: when ``tree_path`` is absent the legacy layout is used:
        ``<report_root>/platform/<platform_dir>/<host>/raw_<artifact>.yaml``.
        This lets per-platform collect roles migrate one at a time.
        """
        platform_dir = collect_data.get("platform_dir", collect_data.get("platform", "unknown"))
        payload = collect_data.get("payload")
        config = collect_data.get("config")
        artifact_name = str(platform_dir).rsplit("/", 1)[-1]

        report_dir = collect_data.get("report_directory") or DEFAULT_REPORT_DIRECTORY

        tree_path = self._sanitize_tree_path(collect_data.get("tree_path"))
        if tree_path:
            host_rel = os.path.join(*tree_path)
            raw_filename = self._sanitize_filename(collect_data.get("raw_filename")) or "raw.yaml"
            config_filename = self._sanitize_filename(collect_data.get("config_filename")) or "config.yaml"
        else:
            host_rel = os.path.join("platform", str(platform_dir), str(host))
            raw_filename = f"raw_{artifact_name}.yaml"
            config_filename = "config.yaml"

        try:
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
            raw_path = os.path.join(host_dir, raw_filename)
            envelope: dict[str, Any] = {
                "metadata": {
                    "host": host,
                    "audit_type": f"raw_{artifact_name}",
                    "raw_type": artifact_name,
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "engine": "ncs_collector_callback",
                },
                "data": payload,
            }
            self._write_yaml(raw_path, envelope)
        else:
            self._display.warning(
                f"[ncs_collector] No payload for '{artifact_name}' on host '{host}' — raw file skipped. "
                f"Check that the assemble task defined the collection variable."
            )

        if config:
            config_path = os.path.join(host_dir, config_filename)
            config_envelope = {
                "metadata": {
                    "host": host,
                    "type": "config",
                    "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                },
                "config": config,
            }
            self._write_yaml(config_path, config_envelope)

    @staticmethod
    def _slugify(name: str) -> str:
        """Lowercase, hyphenate non-alnum runs, strip edge hyphens.

        Must match the reporter's :func:`ncs_reporter.models.node_path.slugify`
        so bundles the callback writes under a tree path resolve against the
        tree node names the renderer derives from the same inputs.
        """
        if not isinstance(name, str):
            return ""
        lowered = name.strip().lower()
        hyphenated = re.sub(r"[^a-z0-9]+", "-", lowered).strip("-")
        return hyphenated

    @staticmethod
    def _sanitize_filename(value: Any) -> str | None:
        """Return a safe filename or ``None`` if not provided / invalid.

        Rejects separators, traversal tokens, and empty strings.
        """
        if not isinstance(value, str):
            return None
        s = value.strip()
        if not s or s in (".", "..") or "/" in s or "\\" in s:
            return None
        return s

    @staticmethod
    def _sanitize_tree_path(value: Any) -> list[str]:
        """Return a list of clean string slug segments, or an empty list.

        Rejects values that aren't list-shaped, segments that aren't strings,
        empty segments, and path-traversal characters. Strips whitespace.
        """
        if not isinstance(value, (list, tuple)):
            return []
        cleaned: list[str] = []
        for seg in value:
            if not isinstance(seg, str):
                return []
            s = seg.strip()
            if not s or s in (".", "..") or "/" in s or "\\" in s:
                return []
            cleaned.append(s)
        return cleaned

    # ------------------------------------------------------------------
    # STIG task telemetry persistence
    # ------------------------------------------------------------------

    def _persist_stig_task_data(self):
        if not self._stig_rules:
            self._display.v("[ncs_collector] No STIG rules recorded; nothing to persist.")
            return

        self._display.display(
            f"[ncs_collector] Persisting STIG data for {len(self._stig_rules)} target(s)...",
            color="cyan",
        )

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

            tree_path = self._sanitize_tree_path(meta.get("tree_path"))
            if tree_path:
                raw_rel = os.path.join(*tree_path, "raw.stig.yaml")
            else:
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
                    "not_reviewed": "Not Reviewed",
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
            data = self._to_builtin(data)
            dir_ = os.path.dirname(path) or "."
            with tempfile.NamedTemporaryFile("w", dir=dir_, suffix=".tmp", delete=False, encoding="utf-8") as tmp:
                yaml.dump(data, tmp, Dumper=_IndentedDumper, default_flow_style=False, indent=2)
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
