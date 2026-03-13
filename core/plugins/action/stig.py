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
        "_stig_phase",
        "_stig_manage",
        "_stig_gate",
        "_stig_gate_packages",
        "_stig_gate_services",
        "_stig_gate_files",
        "_stig_validate",
        "_stig_validate_args",
        "_stig_notify",
        "_stig_use_check_mode_probe",
        "_stig_strict_verify",
        "_stig_id",
        "_stig_na_reason",
        "_stig_result_key",
    }

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}

        raw_args = copy.deepcopy(self._task.args)

        apply_module = raw_args.pop("_stig_apply", None)
        if not apply_module:
            raise AnsibleActionFail("internal.core.stig requires '_stig_apply'.")

        phase = str(raw_args.pop("_stig_phase", "audit")).strip().lower()
        if phase not in {"audit", "remediate"}:
            raise AnsibleActionFail(f"Unsupported _stig_phase '{phase}'. Expected 'audit' or 'remediate'.")

        manage = self._to_bool(raw_args.pop("_stig_manage", True))
        if not manage:
            result.update(
                changed=False,
                skipped=True,
                compliant=None,
                stig=self._build_stig_result(
                    task_vars=task_vars,
                    phase=phase,
                    status="skipped",
                    reason="Control disabled by _stig_manage=false",
                ),
            )
            return result

        # Wrapper metadata
        explicit_stig_id = raw_args.pop("_stig_id", None)
        notify = raw_args.pop("_stig_notify", []) or []
        validate_module = raw_args.pop("_stig_validate", None)
        validate_args = raw_args.pop("_stig_validate_args", {}) or {}
        use_check_mode_probe = self._to_bool(raw_args.pop("_stig_use_check_mode_probe", True))
        strict_verify = self._to_bool(raw_args.pop("_stig_strict_verify", False))
        na_reason = raw_args.pop("_stig_na_reason", None)
        result_key = raw_args.pop("_stig_result_key", "stig")

        # Gate inputs
        gate = copy.deepcopy(raw_args.pop("_stig_gate", {}) or {})
        gate_packages = raw_args.pop("_stig_gate_packages", []) or []
        gate_services = raw_args.pop("_stig_gate_services", []) or []
        gate_files = raw_args.pop("_stig_gate_files", []) or []

        if gate_packages:
            gate.setdefault("packages", gate_packages)
        if gate_services:
            gate.setdefault("services", gate_services)
        if gate_files:
            gate.setdefault("files", gate_files)

        stig_id = explicit_stig_id or self._infer_stig_id(self._task.get_name())

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
                        status="na",
                        reason=na_reason or gate_eval["reason"],
                        gate=gate_eval,
                        notify=notify,
                    )
                },
            )
            return result

        wrapped_args = copy.deepcopy(raw_args)

        probe = None
        compliant = False

        # Primary audit probe
        if use_check_mode_probe:
            probe = self._run_module(
                module_name=apply_module,
                module_args=wrapped_args,
                task_vars=task_vars,
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

        validator_before = None
        if validate_module and not use_check_mode_probe:
            validator_before = self._run_module(
                module_name=validate_module,
                module_args=validate_args,
                task_vars=task_vars,
            )
            compliant = self._validator_passed(validator_before)

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

        remediation = self._run_module(
            module_name=apply_module,
            module_args=wrapped_args,
            task_vars=task_vars,
        )
        if remediation.get("failed"):
            result.update(
                changed=bool(remediation.get("changed", False)),
                failed=True,
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

        if validate_module:
            post_validator = self._run_module(
                module_name=validate_module,
                module_args=validate_args,
                task_vars=task_vars,
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

        if notify:
            result["_stig_notify"] = notify

        return result

    def _run_module(self, module_name: str, module_args: dict[str, Any], task_vars: dict[str, Any]) -> dict[str, Any]:
        # Use FQCN whenever possible; Ansible recommends this for action plugins
        # that execute modules.
        return self._execute_module(
            module_name=module_name,
            module_args=copy.deepcopy(module_args),
            task_vars=task_vars,
            wrap_async=False,
        )

    def _evaluate_gate(self, gate: dict[str, Any], task_vars: dict[str, Any]) -> dict[str, Any]:
        packages = list(gate.get("packages", []) or [])
        services = list(gate.get("services", []) or [])
        files = list(gate.get("files", []) or [])

        ansible_facts = task_vars.get("ansible_facts", {}) or {}
        pkg_facts = ansible_facts.get("packages", {}) or {}
        svc_facts = ansible_facts.get("services", {}) or {}

        missing_packages = [pkg for pkg in packages if pkg not in pkg_facts]
        missing_services = [svc for svc in services if svc not in svc_facts]
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

        reasons = []
        if missing_packages:
            reasons.append(f"Missing packages: {', '.join(missing_packages)}")
        if missing_services:
            reasons.append(f"Missing services: {', '.join(missing_services)}")
        if missing_files:
            reasons.append(f"Missing files: {', '.join(missing_files)}")

        return {
            "passed": not reasons,
            "packages": packages,
            "services": services,
            "files": files,
            "missing_packages": missing_packages,
            "missing_services": missing_services,
            "missing_files": missing_files,
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

    def _infer_stig_id(self, task_name: str) -> str | None:
        if not task_name:
            return None
        match = re.search(r"stigrule_(\d+[A-Za-z0-9]*)", task_name)
        return match.group(1) if match else None

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
            "gate": gate or {},
            "probe": probe,
            "remediation": remediation,
            "validator": validator,
            "notify": notify or [],
        }

    @staticmethod
    def _to_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(value)
