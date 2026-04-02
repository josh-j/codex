from __future__ import annotations

import os
import subprocess
from typing import Any

from ansible_collections.internal.core.plugins.action.stig import ActionModule as StigActionModule


class ActionModule(StigActionModule):
    """STIG wrapper specialized for PowerCLI remediation.

    Subclasses internal.core.stig and handles PowerCLI execution internally.
    Write normal PowerShell in ``script`` — no dollar-sign escaping, no
    connection boilerplate.  ``$vmhost``, ``$esxcli``, and ``$view`` are
    pre-set for the target ESXi host.

    Connection credentials come from ``_stig_module_defaults`` (set via
    play-level ``module_defaults``) — no per-task repetition needed.

    Defaults that differ from ``internal.core.stig``:
    - ``_stig_use_check_mode_probe``: false
    - ``_stig_skip_post_validate``: true
    - ``_stig_apply``: handled internally (pwsh)
    """

    # Sentinel module name used internally — never actually dispatched.
    _PWSH_APPLY = "__pwsh_internal__"

    _PREAMBLE = """\
$ProgressPreference = 'SilentlyContinue'
Set-PowerCLIConfiguration -InvalidCertificateAction Ignore -Confirm:$false | Out-Null
Set-PowerCLIConfiguration -ParticipateInCeip:$false -Confirm:$false | Out-Null
Connect-VIServer -Server $env:_PWSH_VCENTER -User $env:_PWSH_USER -Password $env:_PWSH_PASS -Force -WarningAction SilentlyContinue | Out-Null

$vmhost = Get-VMHost -Name $env:_PWSH_ESXI -ErrorAction SilentlyContinue
if (-not $vmhost) { $vmhost = Get-VMHost | Select-Object -First 1 }
$esxcli = Get-EsxCli -VMHost $vmhost -V2
$view = $vmhost | Get-View
"""

    def run(self, tmp: str | None = None, task_vars: dict[str, Any] | None = None) -> dict[str, Any]:
        task_vars = task_vars or {}

        # Inject pwsh-specific defaults before the parent processes args.
        args = self._task.args

        # Set _stig_apply to our sentinel so the parent doesn't complain.
        args.setdefault("_stig_apply", self._PWSH_APPLY)

        # Sensible defaults for pwsh rules.
        args.setdefault("_stig_use_check_mode_probe", False)
        args.setdefault("_stig_skip_post_validate", True)

        # If no script provided, set a harmless default (audit-only rules).
        args.setdefault("script", "Write-Host 'audit-only'")

        # Stash pwsh-specific args before the parent pops them.
        self._pwsh_script = args.pop("script", "Write-Host 'audit-only'")
        self._pwsh_esxi = args.pop("esxi_hostname", "")
        self._pwsh_timeout = int(args.pop("timeout", 90))

        # The parent's _resolve_apply_module will find _stig_apply and use it.
        # We need a dummy "cmd" so the parent doesn't try to re-resolve.
        args.setdefault("cmd", "true")

        return super().run(tmp, task_vars)

    def _run_module(
        self,
        module_name: str,
        module_args: dict[str, Any],
        task_vars: dict[str, Any],
        check_mode: bool | None = None,
    ) -> dict[str, Any]:
        """Intercept calls to the pwsh sentinel and run PowerShell directly."""
        if module_name != self._PWSH_APPLY:
            return super()._run_module(module_name, module_args, task_vars, check_mode)

        # Resolve connection params from _stig_module_defaults or task vars.
        md = self._task.args.get("_stig_module_defaults", {}) or {}
        # Also check what the parent already parsed (module_defaults are popped
        # early, so check original task args via a fallback chain).
        vcenter = (md.get("hostname") or md.get("vcenter_hostname")
                   or task_vars.get("ansible_host", ""))
        username = (md.get("username") or md.get("vcenter_username")
                    or task_vars.get("vmware_username", ""))
        password = (md.get("password") or md.get("vcenter_password")
                    or task_vars.get("vmware_password", ""))
        esxi_host = self._pwsh_esxi or task_vars.get("_current_esxi_host", "") or vcenter

        if not vcenter or not username or not password:
            return {
                "failed": True,
                "msg": ("stig_pwsh: missing connection params. Provide them via "
                        "module_defaults (_stig_module_defaults) or task vars "
                        "(ansible_host, vmware_username, vmware_password)."),
            }

        full_script = self._PREAMBLE + "\n" + self._pwsh_script

        env = {
            "_PWSH_VCENTER": str(vcenter),
            "_PWSH_USER": str(username),
            "_PWSH_PASS": str(password),
            "_PWSH_ESXI": str(esxi_host),
        }

        try:
            proc = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", "-"],
                input=full_script,
                capture_output=True,
                text=True,
                timeout=self._pwsh_timeout,
                env={**_safe_env(), **env},
            )
        except FileNotFoundError:
            return {"failed": True, "msg": "pwsh (PowerShell) is not installed or not in PATH."}
        except subprocess.TimeoutExpired:
            return {
                "failed": True,
                "msg": f"PowerShell script timed out after {self._pwsh_timeout}s.",
                "rc": 124, "stdout": "", "stderr": "timeout",
            }

        stdout = proc.stdout.replace("\r\n", "\n").replace("\r", "").strip()
        stderr = proc.stderr.replace("\r\n", "\n").replace("\r", "").strip()

        result: dict[str, Any] = {
            "rc": proc.returncode,
            "stdout": stdout,
            "stdout_lines": stdout.splitlines(),
            "stderr": stderr,
            "stderr_lines": stderr.splitlines(),
            "changed": proc.returncode == 0,
        }

        if proc.returncode != 0:
            result["failed"] = True
            result["msg"] = f"PowerShell exited with rc={proc.returncode}: {stderr[:300]}"

        return result


def _safe_env() -> dict[str, str]:
    """Return a minimal base environment for subprocess."""
    keep = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "DOTNET_ROOT",
            "DOTNET_CLI_HOME", "PSModulePath", "POWERSHELL_TELEMETRY_OPTOUT")
    return {k: v for k, v in os.environ.items() if k in keep}
