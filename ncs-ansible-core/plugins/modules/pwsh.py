#!/usr/bin/python

from __future__ import annotations

DOCUMENTATION = r"""
---
module: pwsh
short_description: Run PowerCLI commands against a vCenter/ESXi host
version_added: "1.1.0"
description:
  - Executes a PowerShell/PowerCLI script against a vCenter or ESXi host.
  - Handles connection boilerplate (Connect-VIServer), dollar-sign escaping,
    carriage-return stripping, and timeout management.
  - Pre-sets C($vmhost), C($esxcli), and C($view) variables for the target host.
options:
  script:
    description:
      - PowerShell commands to execute. Write normal PowerShell — no need to
        escape dollar signs. The variables C($vmhost), C($esxcli), and C($view)
        are pre-set for the target ESXi host.
    required: true
    type: str
  vcenter_hostname:
    description: vCenter or ESXi hostname to connect to.
    required: true
    type: str
  vcenter_username:
    description: vCenter username.
    required: true
    type: str
  vcenter_password:
    description: vCenter password. Passed via environment variable, never logged.
    required: true
    type: str
  esxi_hostname:
    description: Target ESXi host within the vCenter. Defaults to vcenter_hostname.
    required: false
    type: str
  timeout:
    description: Timeout in seconds for the PowerShell process.
    required: false
    type: int
    default: 90
  raw:
    description:
      - If true, skip the preamble and pre-set variables. Just run the script
        as-is in a pwsh process.
    required: false
    type: bool
    default: false
author: NCS Automation
"""

EXAMPLES = r"""
- name: Enable rhttpproxy FIPS
  internal.core.pwsh:
    script: |
      $args = $esxcli.system.security.fips140.rhttpproxy.set.CreateArgs()
      $args.enable = $true
      $esxcli.system.security.fips140.rhttpproxy.set.Invoke($args) | Out-Null
    vcenter_hostname: "{{ ansible_host }}"
    vcenter_username: "{{ vmware_username }}"
    vcenter_password: "{{ vmware_password }}"
    esxi_hostname: "{{ _current_esxi_host }}"
"""

RETURN = r"""
stdout:
  description: Standard output from the PowerShell script.
  type: str
  returned: always
stderr:
  description: Standard error from the PowerShell script.
  type: str
  returned: always
rc:
  description: Return code from the PowerShell process.
  type: int
  returned: always
"""

# This module is implemented entirely in the action plugin.
# This file exists only for documentation and argument validation.

from ansible.module_utils.basic import AnsibleModule


def main():
    module = AnsibleModule(
        argument_spec={
            "script": {"type": "str", "required": True},
            "vcenter_hostname": {"type": "str", "required": True},
            "vcenter_username": {"type": "str", "required": True},
            "vcenter_password": {"type": "str", "required": True, "no_log": True},
            "esxi_hostname": {"type": "str", "required": False, "default": ""},
            "timeout": {"type": "int", "required": False, "default": 90},
            "raw": {"type": "bool", "required": False, "default": False},
        },
        supports_check_mode=True,
    )
    # Action plugin handles execution; if we get here something is wrong.
    module.fail_json(msg="internal.core.pwsh must run as an action plugin on the controller, not on a remote target.")


if __name__ == "__main__":
    main()
