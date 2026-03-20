#!/usr/bin/python

from __future__ import annotations

DOCUMENTATION = r"""
---
module: stig
short_description: Wrap an existing module for STIG audit/remediation workflows
version_added: "1.0.0"
description:
  - Wraps an existing module invocation and adds STIG-oriented audit/remediation semantics.
  - The wrapped module can be specified two ways. Flat style uses C(_stig_apply)
    with module args at the top level. Nested style uses the module FQCN as a key
    with its args as a nested dict, giving a more natural task appearance.
  - Reserved keys beginning with C(_stig_) control wrapper behavior.
options:
  _stig_apply:
    description:
      - Fully qualified collection name of the wrapped module to execute (flat syntax).
        Alternatively, use the module FQCN as a nested key (see examples).
    required: false
    type: str
  _stig_phase:
    description:
      - Execution phase. C(audit) probes with check_mode; C(remediate) applies changes
        if non-compliant. C(begin) initializes a STIG pass (gathers facts, sets active
        phase). C(end) cleans up after a STIG pass. When omitted, inherits from
        C(_stig_active_phase) host fact (set by C(begin)), defaulting to C(audit).
    required: false
    type: str
    choices: [audit, remediate, begin, end]
    default: audit
  _stig_manage:
    description:
      - Whether this control is enabled. When omitted and C(_stig_manage_prefix)
        is set (via C(_stig_phase=begin)), the plugin auto-resolves by looking up
        C({prefix}stigrule_{id}_manage) in host/group vars, defaulting to C(true).
    required: false
    type: bool
    default: true
  _stig_manage_prefix:
    description:
      - Variable name prefix for auto-resolving C(_stig_manage). Set once during
        C(_stig_phase=begin) and stored as a host fact. For example, setting
        C(stig_2404_) causes the plugin to look up
        C(stig_2404_stigrule_{id}_manage) for each rule.
    required: false
    type: str
  _stig_gate:
    description:
      - Optional gate object with keys C(packages), C(services),
        C(services_running), C(files), C(vars).
    required: false
    type: dict
  _stig_gate_packages:
    description:
      - Optional package gate shorthand. Returns C(na) if any listed
        package is not installed.
    required: false
    type: list
    elements: str
  _stig_gate_services:
    description:
      - Optional service gate shorthand. Returns C(na) if any listed
        service does not exist in ansible_facts.services.
    required: false
    type: list
    elements: str
  _stig_gate_services_running:
    description:
      - Optional running-service gate shorthand. Returns C(na) if any
        listed service is not in state C(running). Checks both existence
        and active state, unlike C(_stig_gate_services) which only checks
        existence.
    required: false
    type: list
    elements: str
  _stig_gate_files:
    description:
      - Optional file gate shorthand. Returns C(na) if any listed
        file path does not exist.
    required: false
    type: list
    elements: str
  _stig_gate_vars:
    description:
      - Optional variable-based gate. Dict mapping variable names to
        expectations. Supported expectations are C(non-empty) (variable
        must be defined and non-blank), C(defined) (variable must exist
        in task_vars), and C(true) (variable must be truthy).
    required: false
    type: dict
  _stig_audit_only:
    description:
      - Mark this rule as audit-only. During the C(remediate) phase the
        validator still runs to detect compliance, but the apply module is
        never executed. Use this for rules that can detect drift but cannot
        auto-remediate (e.g. Secure Boot, SSL certificates, host profiles).
    required: false
    type: bool
    default: false
  _stig_remediation_errors:
    description:
      - Controls behavior when the remediation module fails.
        C(warn) (default) sets C(failed=False), emits a warning, and
        continues the play. C(halt) sets C(failed=True) and stops the play.
        C(ignore) sets C(failed=False) silently.
    required: false
    type: str
    choices: [warn, halt, ignore]
    default: warn
  _stig_check:
    description:
      - Shorthand for a shell-based compliance check. Provide a shell command
        where C(rc=0) means compliant. Automatically sets C(_stig_validate) to
        C(ansible.builtin.shell), C(_stig_validate_args) to C({cmd: <command>}),
        and C(_stig_use_check_mode_probe) to C(false). Mutually exclusive with
        C(_stig_validate) and C(_stig_validate_expr).
    required: false
    type: str
  _stig_validate:
    description:
      - Optional validator module run after remediation to confirm compliance.
    required: false
    type: str
  _stig_validate_args:
    description:
      - Arguments for the validator module.
    required: false
    type: dict
  _stig_validate_expr:
    description:
      - List of variable conditions evaluated at runtime against C(task_vars)
        as an alternative to C(_stig_validate). Each entry is a dict with a
        C(var) key naming the variable and one comparison key. Supported
        comparisons are C(equals) (case-insensitive string match),
        C(equals_exact) (case-sensitive exact string match),
        C(equals_unordered) (case-insensitive separator-delimited comparison),
        C(contains) (case-insensitive substring),
        C(contains_exact) (case-sensitive substring), C(startswith),
        C(endswith), C(matches) (regex), and C(not_empty) (truthy check).
        All conditions must pass for the rule to be considered compliant.
        Because this is evaluated inside the action plugin, it sidesteps
        Jinja2 early-resolution issues with C(_stig_validate_args).
    required: false
    type: list
    elements: dict
  _stig_notify:
    description:
      - Handler names to surface when remediation changes the system.
        Returned in C(_stig_notify) result key when C(changed=true) so
        the calling playbook can act on it.
    required: false
    type: list
    elements: str
  _stig_use_check_mode_probe:
    description:
      - Whether to use the wrapped module in check_mode as the compliance
        probe. The probe always runs with C(check_mode=True) regardless of
        the playbook's check_mode setting, preventing audit-mode mutations.
    required: false
    type: bool
    default: true
  _stig_strict_verify:
    description:
      - Whether to run a follow-up check_mode probe after remediation to
        confirm the system is now compliant.
    required: false
    type: bool
    default: false
  _stig_id:
    description:
      - Explicit STIG ID override. When omitted, inferred from the task name
        using the C(stigrule_<rule-id>) pattern, including numeric and
        prefixed IDs such as C(stigrule_270741) and C(stigrule_VCEM-70-000021).
    required: false
    type: str
  _stig_na_reason:
    description:
      - Optional reason string when gate checks fail.
    required: false
    type: str
  _stig_gate_status:
    description:
      - Status to report when gate checks fail. Use C(na) when the control
        genuinely does not apply (e.g. GDM rules on a headless server).
        Use C(not_reviewed) when the control applies but a prerequisite is
        missing (e.g. FIPS without an Ubuntu Pro token).
    required: false
    type: str
    choices: [na, not_reviewed]
    default: na
  _stig_result_key:
    description:
      - Top-level result key for structured STIG data.
    required: false
    type: str
    default: stig
  _stig_begin_gather:
    description:
      - List of fact modules to gather during C(_stig_phase=begin).
        Shorthand names like C(package_facts) are expanded to their
        FQCN (C(ansible.builtin.package_facts)).
    required: false
    type: list
    elements: str
notes:
  - This is implemented as an action plugin.
  - All non C(_stig_*) keys are passed to the wrapped module.
  - The probe always runs with check_mode=True to prevent system mutations
    during audit. Remediation always runs with check_mode=False.
  - When C(_stig_phase=begin) is used, it sets the C(_stig_active_phase)
    host fact so subsequent tasks can omit C(_stig_phase).
author:
  - internal.core
"""

EXAMPLES = r"""
# Lifecycle: begin a STIG pass, gathering facts once
- name: "Ubuntu STIG | Begin"
  internal.core.stig:
    _stig_phase: begin
    _stig_apply: ansible.builtin.setup
    _stig_begin_gather:
      - package_facts
      - service_facts

# Nested syntax — module name as key (preferred)
- name: "stigrule_270741"
  internal.core.stig:
    _stig_gate_packages:
      - openssh-server
    _stig_notify:
      - ssh_restart
    ansible.builtin.lineinfile:
      path: /etc/ssh/sshd_config
      regexp: '^\s*UsePAM\s+'
      line: 'UsePAM yes'

# Flat syntax — module name via _stig_apply (also supported)
- name: "stigrule_270741_usepam"
  internal.core.stig:
    _stig_apply: ansible.builtin.lineinfile
    _stig_phase: "{{ _ubuntu2404_stig_phase }}"
    _stig_manage: "{{ stig_2404_stigrule_270741_manage | default(true) }}"
    path: /etc/ssh/sshd_config
    regexp: '^\s*UsePAM\s+'
    line: 'UsePAM yes'
    create: true
    _stig_gate_packages:
      - openssh-server
    _stig_notify:
      - ssh_restart

# Gate on running service (SSSD must be active, not just installed)
- name: "stigrule_271049_sssd_conf"
  internal.core.stig:
    _stig_apply: ansible.builtin.lineinfile
    path: /etc/sssd/sssd.conf
    regexp: '^\s*certificate_verification\s*='
    line: 'certificate_verification = ocsp_dgst=sha1'
    _stig_gate_services_running:
      - sssd

# Gate on variable (FIPS requires Ubuntu Pro token)
- name: "stigrule_270744_fips"
  internal.core.stig:
    _stig_apply: ansible.builtin.command
    cmd: ua enable fips --assume-yes
    _stig_gate_vars:
      stig_2404_stigrule_270744_pro_token: "non-empty"

# _stig_check shorthand — shell command where rc=0 = compliant
- name: "stigrule_270755"
  internal.core.stig:
    _stig_check: |
      [ -z "$(ls -L -d /sys/class/net/*/wireless 2>/dev/null)" ]
    cmd: |
      set -eu
      for iface in $(ls -L -d /sys/class/net/*/wireless 2>/dev/null \
        | xargs -r dirname | xargs -r basename); do
        ip link set "$iface" down || true
      done

# Auto-manage with prefix — begin sets the prefix, tasks omit _stig_manage
- name: "Ubuntu STIG | Begin"
  internal.core.stig:
    _stig_phase: begin
    _stig_manage_prefix: "stig_2404_"
    _stig_begin_gather:
      - package_facts
      - service_facts

# Lifecycle: end a STIG pass
- name: "Ubuntu STIG | End"
  internal.core.stig:
    _stig_phase: end
    _stig_apply: ansible.builtin.setup
"""

RETURN = r"""
stig:
  description: Structured STIG result metadata.
  returned: always
  type: dict
  contains:
    id:
      description: STIG rule ID (inferred or explicit).
      type: str
    phase:
      description: Execution phase (audit, remediate, begin, end).
      type: str
    status:
      description: Compliance status (pass, fail, error, na, skipped).
      type: str
    reason:
      description: Human-readable explanation of the status.
      type: str
    host:
      description: Inventory hostname.
      type: str
    gate:
      description: Gate evaluation details.
      type: dict
    probe:
      description: Check-mode probe result (when applicable).
      type: dict
    remediation:
      description: Remediation module result (when applicable).
      type: dict
    validator:
      description: Post-remediation validator result (when applicable).
      type: dict
    notify:
      description: Handler hints.
      type: list
"""

if __name__ == "__main__":
    from ansible.module_utils.basic import AnsibleModule

    module = AnsibleModule(argument_spec={}, supports_check_mode=True)
    module.exit_json(changed=False)
