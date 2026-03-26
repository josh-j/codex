from __future__ import annotations

import shlex
import subprocess
from typing import Any

from ansible.plugins.action import ActionBase


class ActionModule(ActionBase):
    """Run PowerCLI commands against vCenter/ESXi with automatic connection handling.

    Eliminates boilerplate: preamble, $-escaping, \\r stripping, timeout,
    and pre-sets $vmhost / $esxcli / $view for the target host.
    """

    TRANSFERS_FILES = False
    _REQUIRES_CONNECTION = False

    # PowerCLI preamble: configure, connect, resolve host.
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
        result = super().run(tmp, task_vars)
        task_vars = task_vars or {}

        args = self._task.args
        script = args.get("script", "")
        vcenter = args.get("vcenter_hostname", "")
        username = args.get("vcenter_username", "")
        password = args.get("vcenter_password", "")
        esxi_host = args.get("esxi_hostname", "") or vcenter
        timeout = int(args.get("timeout", 90))
        raw = bool(args.get("raw", False))

        if not script:
            result["failed"] = True
            result["msg"] = "The 'script' parameter is required."
            return result
        if not raw and (not vcenter or not username or not password):
            result["failed"] = True
            result["msg"] = "vcenter_hostname, vcenter_username, and vcenter_password are required (unless raw=true)."
            return result

        # Build the full PowerShell script.
        if raw:
            full_script = script
        else:
            full_script = self._PREAMBLE + "\n" + script

        # Run pwsh with credentials in environment variables (never on command line).
        env = {
            "_PWSH_VCENTER": vcenter,
            "_PWSH_USER": username,
            "_PWSH_PASS": password,
            "_PWSH_ESXI": esxi_host,
        }

        try:
            proc = subprocess.run(
                ["pwsh", "-NoProfile", "-Command", "-"],
                input=full_script,
                capture_output=True,
                text=True,
                timeout=timeout,
                env={**_safe_env(), **env},
            )
        except FileNotFoundError:
            result["failed"] = True
            result["msg"] = "pwsh (PowerShell) is not installed or not in PATH."
            return result
        except subprocess.TimeoutExpired:
            result["failed"] = True
            result["msg"] = f"PowerShell script timed out after {timeout}s."
            result["rc"] = 124
            result["stdout"] = ""
            result["stderr"] = "timeout"
            return result

        stdout = proc.stdout.replace("\r\n", "\n").replace("\r", "").strip()
        stderr = proc.stderr.replace("\r\n", "\n").replace("\r", "").strip()

        result["rc"] = proc.returncode
        result["stdout"] = stdout
        result["stdout_lines"] = stdout.splitlines()
        result["stderr"] = stderr
        result["stderr_lines"] = stderr.splitlines()
        result["changed"] = proc.returncode == 0 and not self._task.check_mode

        if proc.returncode != 0:
            result["failed"] = True
            result["msg"] = f"PowerShell exited with rc={proc.returncode}: {stderr[:300]}"

        return result


def _safe_env() -> dict[str, str]:
    """Return a minimal base environment for subprocess."""
    import os
    keep = ("PATH", "HOME", "USER", "LANG", "LC_ALL", "TERM", "DOTNET_ROOT",
            "DOTNET_CLI_HOME", "PSModulePath", "POWERSHELL_TELEMETRY_OPTOUT")
    return {k: v for k, v in os.environ.items() if k in keep}
