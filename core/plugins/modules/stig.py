#!/usr/bin/python

from __future__ import annotations

DOCUMENTATION = r"""
---
module: stig
short_description: Wrap an existing module for STIG audit/remediation workflows
version_added: "1.0.0"
description:
  - Wraps an existing module invocation and adds STIG-oriented audit/remediation semantics.
  - The wrapped module's arguments remain flat at the top level.
  - Reserved keys beginning with C(_stig_) control wrapper behavior.
options:
  _stig_apply:
    description:
      - Fully qualified collection name of the wrapped module to execute.
    required: true
    type: str
  _stig_phase:
    description:
      - Execution phase.
    required: false
    type: str
    choices: [audit, remediate]
    default: audit
  _stig_manage:
    description:
      - Whether this control is enabled.
    required: false
    type: bool
    default: true
  _stig_gate:
    description:
      - Optional gate object.
    required: false
    type: dict
  _stig_gate_packages:
    description:
      - Optional package gate shorthand.
    required: false
    type: list
    elements: str
  _stig_gate_services:
    description:
      - Optional service gate shorthand.
    required: false
    type: list
    elements: str
  _stig_gate_files:
    description:
      - Optional file gate shorthand.
    required: false
    type: list
    elements: str
  _stig_validate:
    description:
      - Optional validator module.
    required: false
    type: str
  _stig_validate_args:
    description:
      - Arguments for the validator module.
    required: false
    type: dict
  _stig_notify:
    description:
      - Optional notify hints returned in result data.
    required: false
    type: list
    elements: str
  _stig_use_check_mode_probe:
    description:
      - Whether to use the wrapped module as the default compliance probe.
    required: false
    type: bool
    default: true
  _stig_strict_verify:
    description:
      - Whether to run a follow-up probe after remediation.
    required: false
    type: bool
    default: false
  _stig_id:
    description:
      - Explicit STIG ID override.
    required: false
    type: str
  _stig_na_reason:
    description:
      - Optional not-applicable reason when gate checks fail.
    required: false
    type: str
  _stig_result_key:
    description:
      - Top-level result key for structured STIG data.
    required: false
    type: str
    default: stig
notes:
  - This is implemented as an action plugin.
  - All non C(_stig_*) keys are passed to the wrapped module.
author:
  - internal.core
"""

EXAMPLES = r"""
- name: "stigrule_270741_usepam"
  internal.core.stig:
    _stig_apply: ansible.builtin.lineinfile
    path: /etc/ssh/sshd_config
    regexp: '^[[:space:]]*UsePAM[[:space:]]+'
    line: 'UsePAM yes'
    create: true
    _stig_gate_packages:
      - openssh-server
    _stig_notify:
      - ssh_restart

- name: "stigrule_270693_gdm_banner_text"
  internal.core.stig:
    _stig_apply: community.general.ini_file
    path: /etc/gdm3/greeter.dconf-defaults
    section: org/gnome/login-screen
    option: banner-message-text
    value: "{{ ubuntu2404STIG_stigrule_270693__etc_gdm3_greeter_dconf_defaults_text_value }}"
    no_extra_spaces: true
    _stig_gate_packages:
      - gdm3
    _stig_notify:
      - dconf_update
"""

RETURN = r"""
stig:
  description: Structured STIG result metadata.
  returned: always
  type: dict
"""

if __name__ == "__main__":
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(argument_spec={}, supports_check_mode=True)
    module.exit_json(changed=False)
