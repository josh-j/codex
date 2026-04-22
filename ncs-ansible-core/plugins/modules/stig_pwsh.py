#!/usr/bin/python

from __future__ import annotations

DOCUMENTATION = r"""
---
module: stig_pwsh
short_description: STIG wrapper specialized for PowerCLI remediation
version_added: "1.1.0"
description:
  - Combines C(internal.core.stig) audit/remediate semantics with automatic
    PowerCLI execution.  Write normal PowerShell in C(script) — the plugin
    handles connection, dollar-sign escaping, CR stripping, and timeouts.
  - Pre-sets C($vmhost), C($esxcli), and C($view) for the target ESXi host.
  - Connection credentials come from C(_stig_module_defaults) (set via
    play-level C(module_defaults)) — no per-task credential boilerplate.
  - Defaults that differ from C(internal.core.stig): C(_stig_apply) is
    handled internally, C(_stig_use_check_mode_probe) defaults to false,
    C(_stig_skip_post_validate) defaults to true.
options:
  script:
    description:
      - PowerShell commands for remediation.  Only executed when the rule is
        non-compliant and the phase is C(remediate).  For audit-only rules,
        omit this or set C(_stig_audit_only=true).
    required: false
    type: str
    default: "Write-Host 'audit-only'"
  esxi_hostname:
    description:
      - Target ESXi host.  Overrides the hostname from C(_stig_module_defaults).
    required: false
    type: str
  timeout:
    description: Timeout in seconds for the PowerShell process.
    required: false
    type: int
    default: 90
extends_documentation_fragment:
  - internal.core.stig
author: NCS Automation
"""

EXAMPLES = r"""
# Audit-only — just validate_expr, no script needed
- name: "stigrule_256430"
  internal.core.stig_pwsh:
    _stig_audit_only: true
    _stig_validate_expr:
      - var: _encryption_require_secure_boot
        equals: "true"

# Remediation — script runs only when non-compliant in remediate mode
- name: "stigrule_256442"
  internal.core.stig_pwsh:
    _stig_validate_expr:
      - var: _fips_rhttpproxy_enabled
        equals: "true"
    script: |
      $args = $esxcli.system.security.fips140.rhttpproxy.set.CreateArgs()
      $args.enable = $true
      $esxcli.system.security.fips140.rhttpproxy.set.Invoke($args) | Out-Null
"""

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "script": {"type": "str", "required": False, "default": "Write-Host 'audit-only'"},
            "esxi_hostname": {"type": "str", "required": False, "default": ""},
            "timeout": {"type": "int", "required": False, "default": 90},
        },
        supports_check_mode=True,
    )
    module.fail_json(msg="internal.core.stig_pwsh must run as an action plugin on the controller.")


if __name__ == "__main__":
    main()
