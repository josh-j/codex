from __future__ import annotations

import copy
import re
from typing import Any

from ansible.errors import AnsibleActionFail
from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    TRANSFERS_FILES = False

    RESERVED_KEYS = {
        "_stig_apply",
        "_stig_audit_only",
        "_stig_phase",
        "_stig_manage",
        "_stig_manage_prefix",
        "_stig_gate",
        "_stig_gate_packages",
        "_stig_gate_services",
        "_stig_gate_services_running",
        "_stig_gate_files",
        "_stig_gate_vars",
        "_stig_remediation_errors",
        "_stig_check",
        "_stig_validate",
        "_stig_validate_args",
        "_stig_validate_expr",
        "_stig_notify",
        "_stig_use_check_mode_probe",
        "_stig_strict_verify",
        "_stig_id",
        "_stig_na_reason",
        "_stig_gate_status",
        "_stig_result_key",
        "_stig_begin_gather",
        "_stig_skip_post_validate",
        "_stig_module_defaults",
    }

    # Valid phases including lifecycle hooks.
    _VALID_PHASES = {"audit", "remediate", "begin", "end"}

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}

        # -------------------------------------------------------------
        # Extra-var filtering: stig_only / stig_skip
        # Allows targeting individual rules without Ansible tags:
        #   -e "stig_only=270818"
        #   -e '{"stig_only": ["270818","270819"]}'
        #   -e '{"stig_skip": ["270747"]}'
        # -------------------------------------------------------------
        skip_result = self._check_stig_filter(task_vars)
        if skip_result is not None:
            result.update(skip_result)
            return result

        raw_args = copy.deepcopy(self._task.args)

        apply_module, raw_args = self._resolve_apply_module(raw_args)

        # Phase resolution: explicit > inherited from begin > default audit.
        phase_raw = raw_args.pop("_stig_phase", None)
        if phase_raw is not None:
            phase = str(phase_raw).strip().lower()
        else:
            phase = str(task_vars.get("_stig_active_phase", "audit")).strip().lower()

        if phase not in self._VALID_PHASES:
            raise AnsibleActionFail(
                f"Unsupported _stig_phase '{phase}'. Expected one of: {', '.join(sorted(self._VALID_PHASES))}."
            )

        # Handle lifecycle phases early.
        if phase == "begin":
            return self._run_begin(raw_args, task_vars, result, apply_module)
        if phase == "end":
            return self._run_end(raw_args, task_vars, result)

        # Infer stig_id early so auto-manage lookup can use it.
        explicit_stig_id = raw_args.pop("_stig_id", None)
        stig_id = explicit_stig_id or self._infer_stig_id(self._task.get_name())

        # Auto-resolve _stig_manage from host var when not explicitly provided.
        raw_args.pop("_stig_manage_prefix", None)  # consumed by begin, strip here
        manage_raw = raw_args.pop("_stig_manage", None)
        if manage_raw is not None:
            manage = self._to_bool(manage_raw)
        else:
            manage_prefix = str(task_vars.get("_stig_manage_prefix", "")).strip()
            if manage_prefix and stig_id:
                var_name = f"{manage_prefix}stigrule_{stig_id}_manage"
                raw_val = task_vars.get(var_name, True)
                # Template Jinja2 expressions loaded via include_vars.
                if self._templar.is_possibly_template(raw_val):
                    with self._templar.set_temporary_context(available_variables=task_vars):
                        raw_val = self._templar.template(raw_val)
                manage = self._to_bool(raw_val)
            else:
                manage = True

        if not manage:
            result_key = raw_args.pop("_stig_result_key", "stig")
            result.update(
                changed=False,
                skipped=True,
                compliant=None,
                **{
                    result_key: self._build_stig_result(
                        task_vars=task_vars,
                        stig_id=stig_id,
                        phase=phase,
                        status="not_reviewed",
                        reason="Control disabled by _stig_manage=false",
                    )
                },
            )
            return result

        # Wrapper metadata
        audit_only = self._to_bool(raw_args.pop("_stig_audit_only", False))
        notify = raw_args.pop("_stig_notify", []) or []
        stig_check = raw_args.pop("_stig_check", None)
        validate_module = raw_args.pop("_stig_validate", None)
        validate_args = raw_args.pop("_stig_validate_args", {}) or {}
        validate_expr = raw_args.pop("_stig_validate_expr", None)

        # _stig_check is a shorthand: shell command where rc=0 = compliant.
        if stig_check is not None:
            if validate_module or validate_expr:
                raise AnsibleActionFail(
                    "_stig_check is mutually exclusive with _stig_validate / _stig_validate_expr."
                )
            validate_module = "ansible.builtin.shell"
            validate_args = {"cmd": stig_check}
            # _stig_check implies no check_mode probe.
            raw_args.pop("_stig_use_check_mode_probe", None)
            use_check_mode_probe = False
        else:
            use_check_mode_probe = self._to_bool(raw_args.pop("_stig_use_check_mode_probe", True))
        strict_verify = self._to_bool(raw_args.pop("_stig_strict_verify", False))
        na_reason = raw_args.pop("_stig_na_reason", None)
        gate_status = str(raw_args.pop("_stig_gate_status", "na")).strip().lower()
        result_key = raw_args.pop("_stig_result_key", "stig")
        skip_post_validate = self._to_bool(raw_args.pop("_stig_skip_post_validate", False))
        error_mode = str(raw_args.pop("_stig_remediation_errors", "warn")).strip().lower()
        module_defaults = raw_args.pop("_stig_module_defaults", {}) or {}

        # Gate inputs
        gate = copy.deepcopy(raw_args.pop("_stig_gate", {}) or {})
        gate_packages = raw_args.pop("_stig_gate_packages", []) or []
        gate_services = raw_args.pop("_stig_gate_services", []) or []
        gate_services_running = raw_args.pop("_stig_gate_services_running", []) or []
        gate_files = raw_args.pop("_stig_gate_files", []) or []
        gate_vars = raw_args.pop("_stig_gate_vars", {}) or {}
        # Pop begin_gather even though it's not used here, to avoid passing it to the wrapped module.
        raw_args.pop("_stig_begin_gather", None)

        if gate_packages:
            gate.setdefault("packages", gate_packages)
        if gate_services:
            gate.setdefault("services", gate_services)
        if gate_services_running:
            gate.setdefault("services_running", gate_services_running)
        if gate_files:
            gate.setdefault("files", gate_files)
        if gate_vars:
            gate.setdefault("vars", gate_vars)

        gate_eval = self._evaluate_gate(gate=gate, task_vars=task_vars)
        if not gate_eval["passed"]:
            result.update(
                changed=False,
                skipped=True,
                compliant=None,
                **{
                    result_key: self._build_stig_result(
                        task_vars=task_vars,
                        stig_id=stig_id,
                        phase=phase,
                        status=gate_status,
                        reason=na_reason or gate_eval["reason"],
                        gate=gate_eval,
                        notify=notify,
                    )
                },
            )
            return result

        wrapped_args = copy.deepcopy(raw_args)

        # Merge _stig_module_defaults into wrapped args for non-shell modules.
        # This propagates play-level module_defaults (e.g. vCenter credentials)
        # through to wrapped modules like community.vmware.* without leaking
        # them into shell/command modules where they'd cause validation errors.
        if module_defaults and apply_module not in self._SHELL_MODULES:
            wrapped_args = {**module_defaults, **wrapped_args}

        probe = None
        compliant = False

        # When _stig_validate_expr is provided, it is the authoritative
        # compliance check — skip the check_mode probe entirely so we
        # don't waste time running a dummy shell command.
        validator_before = None
        if validate_expr:
            compliant, expr_details = self._evaluate_expr(validate_expr, task_vars)
            validator_before = {"passed": compliant, "details": expr_details}
            use_check_mode_probe = False
        elif validate_module and not use_check_mode_probe:
            validator_before = self._run_module(
                module_name=validate_module,
                module_args=validate_args,
                task_vars=task_vars,
                check_mode=False,
            )
            compliant = self._validator_passed(validator_before)

        # Primary audit probe — runs in check_mode to avoid mutations.
        # Skipped when validate_expr already determined compliance above.
        if use_check_mode_probe:
            probe = self._run_module(
                module_name=apply_module,
                module_args=wrapped_args,
                task_vars=task_vars,
                check_mode=True,
            )
            if probe.get("failed"):
                result.update(
                    changed=False,
                    failed=True,
                    compliant=False,
                    msg=probe.get("msg", f"Wrapped module {apply_module} failed during probe"),
                    **{
                        result_key: self._build_stig_result(
                            task_vars=task_vars,
                            stig_id=stig_id,
                            phase=phase,
                            status="error",
                            reason="Wrapped module failed during probe",
                            gate=gate_eval,
                            probe=probe,
                            notify=notify,
                        )
                    },
                )
                return result
            compliant = not bool(probe.get("changed", False))

        if phase == "audit":
            status = "pass" if compliant else "fail"
            reason = (
                "Wrapped module reported no changes"
                if use_check_mode_probe and compliant
                else "Wrapped module would change target"
                if use_check_mode_probe
                else "Validator passed"
                if compliant
                else "Validator failed"
            )
            result.update(
                changed=False,
                failed=False,
                compliant=compliant,
                **{
                    result_key: self._build_stig_result(
                        task_vars=task_vars,
                        stig_id=stig_id,
                        phase=phase,
                        status=status,
                        reason=reason,
                        gate=gate_eval,
                        probe=probe,
                        validator=validator_before,
                        notify=notify,
                    )
                },
            )
            return result

        # Audit-only rules: report compliance but never apply remediation.
        if audit_only and phase == "remediate":
            status = "pass" if compliant else "fail"
            reason = ("Audit-only rule — validator passed" if compliant
                      else "Audit-only rule — validator failed (not auto-remediable)")
            result.update(
                changed=False, failed=False, compliant=compliant,
                **{result_key: self._build_stig_result(
                    task_vars=task_vars, stig_id=stig_id, phase=phase,
                    status=status, reason=reason, gate=gate_eval,
                    probe=probe, validator=validator_before, notify=notify,
                )}
            )
            return result

        # Remediate phase
        if compliant:
            result.update(
                changed=False,
                failed=False,
                compliant=True,
                **{
                    result_key: self._build_stig_result(
                        task_vars=task_vars,
                        stig_id=stig_id,
                        phase=phase,
                        status="pass",
                        reason="Already compliant",
                        gate=gate_eval,
                        probe=probe,
                        notify=notify,
                    )
                },
            )
            return result

        # Apply remediation with check_mode explicitly off.
        remediation = self._run_module(
            module_name=apply_module,
            module_args=wrapped_args,
            task_vars=task_vars,
            check_mode=False,
        )
        if remediation.get("failed"):
            should_fail = (error_mode == "halt")
            if error_mode == "warn":
                self._display.warning(
                    f"[stig] Remediation failed for {stig_id}: "
                    f"{remediation.get('msg', 'unknown error')}"
                )
            result.update(
                changed=bool(remediation.get("changed", False)),
                failed=should_fail,
                compliant=False,
                msg=remediation.get("msg", f"Wrapped module {apply_module} failed during remediation"),
                **{
                    result_key: self._build_stig_result(
                        task_vars=task_vars,
                        stig_id=stig_id,
                        phase=phase,
                        status="error",
                        reason="Wrapped module failed during remediation",
                        gate=gate_eval,
                        probe=probe,
                        remediation=remediation,
                        notify=notify,
                    )
                },
            )
            return result

        post_validator = None
        final_compliant = True
        final_reason = "Remediation applied"

        if validate_module and not skip_post_validate:
            post_validator = self._run_module(
                module_name=validate_module,
                module_args=validate_args,
                task_vars=task_vars,
                check_mode=False,
            )
            final_compliant = self._validator_passed(post_validator)
            final_reason = (
                "Remediation applied and validator passed"
                if final_compliant
                else "Remediation applied but validator failed"
            )
        elif strict_verify and use_check_mode_probe:
            post_probe = self._run_module(
                module_name=apply_module,
                module_args=wrapped_args,
                task_vars=task_vars,
                check_mode=True,
            )
            post_validator = post_probe
            final_compliant = not bool(post_probe.get("changed", False))
            final_reason = (
                "Remediation applied and follow-up probe reports compliant"
                if final_compliant
                else "Remediation applied but follow-up probe still reports drift"
            )

        result.update(
            changed=bool(remediation.get("changed", False)),
            failed=False,
            compliant=final_compliant,
            **{
                result_key: self._build_stig_result(
                    task_vars=task_vars,
                    stig_id=stig_id,
                    phase=phase,
                    status="pass" if final_compliant else "fail",
                    reason=final_reason,
                    gate=gate_eval,
                    probe=probe,
                    remediation=remediation,
                    validator=post_validator,
                    notify=notify,
                )
            },
        )

        if notify and remediation.get("changed"):
            result["_stig_notify"] = notify

        return result

    # ------------------------------------------------------------------
    # Lifecycle: begin / end
    # ------------------------------------------------------------------

    def _run_begin(
        self,
        raw_args: dict[str, Any],
        task_vars: dict[str, Any],
        result: dict[str, Any],
        apply_module: str,
    ) -> dict[str, Any]:
        """Handle _stig_phase=begin — gather facts once and set active phase."""
        gather_list = list(raw_args.pop("_stig_begin_gather", []) or [])
        result_key = raw_args.pop("_stig_result_key", "stig")
        manage_prefix = raw_args.pop("_stig_manage_prefix", "")

        # Strip remaining stig keys so they don't bleed into module args.
        for key in list(raw_args):
            if key.startswith("_stig_"):
                raw_args.pop(key)

        gathered = {}
        for fact_module in gather_list:
            # Resolve shorthand: "package_facts" -> "ansible.builtin.package_facts"
            fqcn = fact_module if "." in fact_module else f"ansible.builtin.{fact_module}"
            gather_result = self._run_module(
                module_name=fqcn,
                module_args={},
                task_vars=task_vars,
            )
            if gather_result.get("failed"):
                result.update(
                    changed=False,
                    failed=True,
                    msg=f"Failed to gather {fqcn}: {gather_result.get('msg', '')}",
                    **{
                        result_key: self._build_stig_result(
                            task_vars=task_vars,
                            phase="begin",
                            status="error",
                            reason=f"Failed to gather {fqcn}",
                        )
                    },
                )
                return result
            gathered[fact_module] = True
            # Merge gathered facts into task_vars so subsequent gate checks see them.
            new_facts = gather_result.get("ansible_facts", {})
            if new_facts:
                task_vars.setdefault("ansible_facts", {}).update(new_facts)

        # Set the active phase fact so subsequent tasks inherit it.
        # Default the active phase to "audit" — the role's phase variable
        # will override this when it calls begin with the correct phase.
        active_phase = str(raw_args.pop("_stig_active_phase", "audit")).strip().lower()

        set_fact_args: dict[str, Any] = {"_stig_active_phase": active_phase}
        if manage_prefix:
            set_fact_args["_stig_manage_prefix"] = manage_prefix

        set_fact_result = self._run_module(
            module_name="ansible.builtin.set_fact",
            module_args=set_fact_args,
            task_vars=task_vars,
        )

        facts: dict[str, Any] = {"_stig_active_phase": active_phase}
        if manage_prefix:
            facts["_stig_manage_prefix"] = manage_prefix

        result.update(
            changed=False,
            failed=False,
            skipped=False,
            ansible_facts=facts,
            **{
                result_key: self._build_stig_result(
                    task_vars=task_vars,
                    phase="begin",
                    status="pass",
                    reason=f"STIG pass initialized (phase={active_phase}, gathered={list(gathered)})",
                )
            },
        )
        return result

    def _run_end(
        self,
        raw_args: dict[str, Any],
        task_vars: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        """Handle _stig_phase=end — cleanup phase facts."""
        result_key = raw_args.pop("_stig_result_key", "stig")

        # Clear the active phase fact.
        self._run_module(
            module_name="ansible.builtin.set_fact",
            module_args={"_stig_active_phase": ""},
            task_vars=task_vars,
        )

        result.update(
            changed=False,
            failed=False,
            skipped=False,
            ansible_facts={"_stig_active_phase": ""},
            **{
                result_key: self._build_stig_result(
                    task_vars=task_vars,
                    phase="end",
                    status="pass",
                    reason="STIG pass completed",
                )
            },
        )
        return result

    # ------------------------------------------------------------------
    # Module execution with check_mode support
    # ------------------------------------------------------------------

    # Modules that are actually action plugins wrapping the command module.
    _SHELL_MODULES = frozenset({
        "shell", "ansible.builtin.shell", "ansible.legacy.shell",
        "command", "ansible.builtin.command", "ansible.legacy.command",
        "pwsh", "internal.core.pwsh", "__pwsh_internal__",
    })

    def _run_module(
        self,
        module_name: str,
        module_args: dict[str, Any],
        task_vars: dict[str, Any],
        check_mode: bool | None = None,
    ) -> dict[str, Any]:
        """Execute a module, optionally overriding check_mode on the task."""
        args = copy.deepcopy(module_args)
        resolved_name = module_name

        # shell/command are action plugins, not modules — route through
        # the command module with _uses_shell for shell.
        _pwsh_modules = ("pwsh", "internal.core.pwsh")
        if module_name in self._SHELL_MODULES and module_name not in _pwsh_modules:
            if "cmd" in args and "_raw_params" not in args:
                args["_raw_params"] = args.pop("cmd")
            if module_name in ("shell", "ansible.builtin.shell", "ansible.legacy.shell"):
                args["_uses_shell"] = True
            resolved_name = "ansible.legacy.command"
        elif module_name in _pwsh_modules:
            resolved_name = "internal.core.pwsh"

        if check_mode is not None:
            original_check_mode = self._task.check_mode
            self._task.check_mode = check_mode
            try:
                return self._execute_module(
                    module_name=resolved_name,
                    module_args=args,
                    task_vars=task_vars,
                    wrap_async=False,
                )
            finally:
                self._task.check_mode = original_check_mode
        return self._execute_module(
            module_name=resolved_name,
            module_args=args,
            task_vars=task_vars,
            wrap_async=False,
        )

    # ------------------------------------------------------------------
    # Gate evaluation
    # ------------------------------------------------------------------

    def _evaluate_gate(self, gate: dict[str, Any], task_vars: dict[str, Any]) -> dict[str, Any]:
        packages = list(gate.get("packages", []) or [])
        services = list(gate.get("services", []) or [])
        services_running = list(gate.get("services_running", []) or [])
        files = list(gate.get("files", []) or [])
        gate_vars = dict(gate.get("vars", {}) or {})

        ansible_facts = task_vars.get("ansible_facts", {}) or {}
        pkg_facts = ansible_facts.get("packages", {}) or {}
        svc_facts = ansible_facts.get("services", {}) or {}

        missing_packages = [pkg for pkg in packages if pkg not in pkg_facts]
        missing_services = [svc for svc in services if svc not in svc_facts]
        not_running = [
            svc for svc in services_running
            if svc_facts.get(svc, {}).get("state") != "running"
        ]
        missing_files: list[str] = []

        for path in files:
            stat_result = self._execute_module(
                module_name="ansible.builtin.stat",
                module_args={"path": path},
                task_vars=task_vars,
                wrap_async=False,
            )
            exists = bool((stat_result.get("stat") or {}).get("exists", False))
            if not exists:
                missing_files.append(path)

        # Variable-based gating.
        missing_vars: list[str] = []
        for var_name, expected in gate_vars.items():
            actual = task_vars.get(var_name, "")
            if expected == "non-empty" and not str(actual).strip():
                missing_vars.append(var_name)
            elif expected == "defined" and var_name not in task_vars:
                missing_vars.append(var_name)
            elif expected == "true" and not self._to_bool(actual):
                missing_vars.append(var_name)

        reasons = []
        if missing_packages:
            reasons.append(f"Missing packages: {', '.join(missing_packages)}")
        if missing_services:
            reasons.append(f"Missing services: {', '.join(missing_services)}")
        if not_running:
            reasons.append(f"Services not running: {', '.join(not_running)}")
        if missing_files:
            reasons.append(f"Missing files: {', '.join(missing_files)}")
        if missing_vars:
            reasons.append(f"Gate variables not satisfied: {', '.join(missing_vars)}")

        return {
            "passed": not reasons,
            "packages": packages,
            "services": services,
            "services_running": services_running,
            "files": files,
            "vars": gate_vars,
            "missing_packages": missing_packages,
            "missing_services": missing_services,
            "not_running": not_running,
            "missing_files": missing_files,
            "missing_vars": missing_vars,
            "reason": "; ".join(reasons) if reasons else "All gate conditions passed",
        }

    def _validator_passed(self, validator_result: dict[str, Any]) -> bool:
        if not isinstance(validator_result, dict):
            return False
        if validator_result.get("failed"):
            return False
        if "rc" in validator_result and validator_result.get("rc") is not None:
            return int(validator_result["rc"]) == 0
        return not bool(validator_result.get("changed", False))

    def _evaluate_expr(self, expr: list[dict], task_vars: dict[str, Any]) -> tuple[bool, dict]:
        """Evaluate a list of variable conditions against current task_vars."""
        details: dict[str, str] = {}
        for cond in expr:
            var_name = cond.get("var", "")
            actual = str(task_vars.get(var_name, "")).strip()
            details[var_name] = actual
            actual_lower = actual.lower()
            if "equals" in cond:
                if actual_lower != str(cond["equals"]).strip().lower():
                    return False, details
            elif "equals_exact" in cond:
                if actual != str(cond["equals_exact"]).strip():
                    return False, details
            elif "equals_unordered" in cond:
                sep = str(cond.get("separator", ","))
                expected_parts = sorted(s.strip().lower() for s in str(cond["equals_unordered"]).split(sep) if s.strip())
                actual_parts = sorted(s.strip().lower() for s in actual.split(sep) if s.strip())
                if actual_parts != expected_parts:
                    return False, details
            elif "contains" in cond:
                if str(cond["contains"]).strip().lower() not in actual_lower:
                    return False, details
            elif "contains_exact" in cond:
                if str(cond["contains_exact"]).strip() not in actual:
                    return False, details
            elif "startswith" in cond:
                if not actual.startswith(str(cond["startswith"]).strip()):
                    return False, details
            elif "endswith" in cond:
                if not actual.endswith(str(cond["endswith"]).strip()):
                    return False, details
            elif "matches" in cond:
                if not re.search(str(cond["matches"]), actual):
                    return False, details
            elif "not_empty" in cond and cond["not_empty"]:
                if not actual:
                    return False, details
        return True, details

    def _infer_stig_id(self, task_name: str) -> str | None:
        if not task_name:
            return None
        match = re.search(r"stigrule_([A-Za-z0-9]+(?:-[A-Za-z0-9]+)*[A-Za-z0-9]*)", task_name)
        return match.group(1) if match else None

    def _check_stig_filter(self, task_vars: dict[str, Any]) -> dict[str, Any] | None:
        """Skip this task if it doesn't match stig_only or is in stig_skip.

        Returns a skip result dict if the task should be skipped, None otherwise.
        """
        stig_only = task_vars.get("stig_only")
        stig_skip = task_vars.get("stig_skip")

        if stig_only is None and stig_skip is None:
            return None

        task_name = self._task.get_name() or ""
        stig_id = self._infer_stig_id(task_name)

        # If we can't determine the stig_id, let the task run — it may be
        # a begin/end lifecycle task or infrastructure task.
        if not stig_id:
            return None

        # Normalize the base rule number (270689a -> 270689) for matching,
        # but also keep the full id for exact matches.
        base_id = re.match(r"(\d+)", stig_id)
        base_num = base_id.group(1) if base_id else stig_id

        # stig_only: only run rules in this list
        if stig_only is not None:
            allow_list = [str(x).strip() for x in stig_only] if isinstance(stig_only, list) else [str(stig_only).strip()]
            matched = any(
                stig_id == entry or base_num == entry
                for entry in allow_list
            )
            if not matched:
                return {
                    "changed": False,
                    "skipped": True,
                    "stig": {
                        "id": stig_id,
                        "task_name": task_name,
                        "phase": "filter",
                        "status": "skipped",
                        "reason": f"Excluded by stig_only filter (wanted {allow_list})",
                    },
                }

        # stig_skip: skip rules in this list
        if stig_skip is not None:
            deny_list = [str(x).strip() for x in stig_skip] if isinstance(stig_skip, list) else [str(stig_skip).strip()]
            if stig_id in deny_list or base_num in deny_list:
                return {
                    "changed": False,
                    "skipped": True,
                    "stig": {
                        "id": stig_id,
                        "task_name": task_name,
                        "phase": "filter",
                        "status": "skipped",
                        "reason": f"Excluded by stig_skip filter",
                    },
                }

        return None

    def _build_stig_result(
        self,
        task_vars: dict[str, Any],
        phase: str,
        status: str,
        reason: str,
        stig_id: str | None = None,
        gate: dict[str, Any] | None = None,
        probe: dict[str, Any] | None = None,
        remediation: dict[str, Any] | None = None,
        validator: dict[str, Any] | None = None,
        notify: list[str] | None = None,
    ) -> dict[str, Any]:
        return {
            "id": stig_id,
            "task_name": self._task.get_name(),
            "phase": phase,
            "status": status,
            "reason": reason,
            "host": task_vars.get("inventory_hostname"),
            "target_host": self._resolve_var(
                task_vars, "stig_target_host", "_ncs_stig_target_host", "inventory_hostname",
            ),
            "target_type": str(self._resolve_var(
                task_vars, "stig_target_type", "_ncs_stig_target_type",
            ) or "").lower(),
            "gate": gate or {},
            "probe": probe,
            "remediation": remediation,
            "validator": validator,
            "notify": notify or [],
        }

    @staticmethod
    def _resolve_apply_module(raw_args: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Resolve the wrapped module name and flatten args.

        Supports two syntaxes:

        Flat (original):
            _stig_apply: ansible.builtin.lineinfile
            path: /etc/ssh/sshd_config
            ...

        Nested (module name as key):
            ansible.builtin.lineinfile:
              path: /etc/ssh/sshd_config
              ...
        """
        # Try explicit _stig_apply first (flat syntax).
        apply_module = raw_args.pop("_stig_apply", None)
        if apply_module:
            return apply_module, raw_args

        # Nested syntax: find the one key that isn't _stig_* prefixed.
        nested_keys = [k for k in raw_args if not k.startswith("_stig_")]
        if len(nested_keys) == 1 and isinstance(raw_args.get(nested_keys[0]), dict):
            module_name = nested_keys[0]
            module_args = raw_args.pop(module_name)
            raw_args.update(module_args)
            return module_name, raw_args

        # Bare shell args (e.g. cmd: "true") — treat as ansible.builtin.shell.
        if nested_keys and all(
            k in ("cmd", "_raw_params", "creates", "removes", "chdir",
                   "executable", "stdin", "stdin_add_newline",
                   "strip_empty_ends", "warn")
            for k in nested_keys
        ):
            return "ansible.builtin.shell", raw_args

        # No wrapped module at all — audit-only rules using _stig_validate_expr
        # don't need one; use a harmless "true" shell command as the wrapped module.
        if not nested_keys:
            raw_args["cmd"] = "true"
            return "ansible.builtin.shell", raw_args

        raise AnsibleActionFail(
            "internal.core.stig requires either '_stig_apply' or exactly one "
            "nested module key (e.g. 'ansible.builtin.lineinfile: {...}')."
        )

    def _resolve_var(self, task_vars: dict[str, Any], *keys: str) -> Any:
        """Return the first non-empty value for *keys*, templating Jinja2 strings."""
        for key in keys:
            val = task_vars.get(key)
            if val is None:
                continue
            if self._templar.is_possibly_template(val):
                with self._templar.set_temporary_context(available_variables=task_vars):
                    val = self._templar.template(val)
            if val:
                return val
        return None

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
