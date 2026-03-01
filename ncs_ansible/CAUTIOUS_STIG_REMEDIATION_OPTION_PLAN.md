# Plan: Abundance of Caution STIG Remediation

## 0. Usage Context: "Break-Glass" Option

**This interactive mode is NOT the default operating procedure for NCS.** 

It is designed as an optional "Break-Glass" workflow for:
*   **Extreme Cases:** Critical production systems where zero-downtime is mandatory and every change must be visually verified.
*   **Testing & Development:** First-time verification of new security controls or complex kernel-level hardening.
*   **Troubleshooting:** Stepping through remediation on a "Problem Child" host that has previously failed automation.

In normal fleet operations, STIG remediation remains fully autonomous.

---

This document outlines the "Plan-First" interactive workflow for STIG remediation. This approach ensures that no changes are made to the system without a prior audit, a generated remediation plan, and explicit just-in-time user approval.

## 1. The Strategy: Audit -> Plan -> Execute

We will move away from "Blind Hardening" to an "Evidence-Based" workflow.

1.  **Phase 1: Discovery (Audit):** Execute existing STIG audit tasks in `check_mode` to identify specific failures.
2.  **Phase 2: Planning (Manifest):** Aggregate failures into a "Remediation Plan" unique to the host.
3.  **Phase 3: Interactive Approval:** Review each failure and its specific evidence (e.g., current vs. expected permissions) and approve/deny the fix.
4.  **Phase 4: Targeted Execution:** Apply only the approved fixes.

---

## 2. Core Components

### A. The Metadata Map (`vars/stig_metadata.yaml`)
A central source of truth for human-readable rule descriptions.

```yaml
ubuntu_stig_metadata:
  "270645":
    title: "Configure systemd-timesyncd"
    desc: "Ensures time synchronization is handled by the modern systemd service."
  "270646":
    title: "Uninstall legacy NTP"
    desc: "Removes old NTP packages to prevent service conflicts."
```

### B. The Step-Confirm Helper (`tasks/stig_step.yaml`)
A reusable task file that provides the "Just-in-Time" pause.

```yaml
# Reusable Just-in-Time Prompt
- name: "CAUTION | Rule {{ rule_id }} | Confirmation"
  ansible.builtin.pause:
    prompt: |
      [ STIG RULE {{ rule_id }} ]
      TITLE: {{ ubuntu_stig_metadata[rule_id].title }}
      DESCRIPTION: {{ ubuntu_stig_metadata[rule_id].desc }}
      EVIDENCE: {{ audit_evidence | default('Manual verification required') }}

      Apply this fix now? (y/n/abort)
  register: _step_choice

- name: "CAUTION | Handle Abort"
  ansible.builtin.fail:
    msg: "User aborted at Rule {{ rule_id }}"
  when: _step_choice.user_input | lower == 'abort'

- name: "CAUTION | Set Action Flag"
  ansible.builtin.set_fact:
    _proceed: "{{ _step_choice.user_input | lower == 'y' }}"
```

---

## 3. The Implementation Pattern

Each STIG remediation task will follow this cautious structure:

```yaml
# 1. Inspect state
- name: "R-270645 | [Audit] Check status"
  ansible.builtin.command: systemctl is-active systemd-timesyncd
  register: _audit_timesync
  ignore_errors: true
  changed_when: false

# 2. Prompt for approval with evidence
- name: "R-270645 | [Caution] Confirm fix"
  ansible.builtin.include_tasks: stig_step.yaml
  vars:
    rule_id: "270645"
    audit_evidence: "Service status is: {{ _audit_timesync.stdout }}"
  when: ubuntu_stig_interactive | bool

# 3. Apply only if approved OR if not in interactive mode
- name: "R-270645 | [Remediate] Apply"
  ansible.builtin.apt:
    name: systemd-timesyncd
    state: present
  when: >
    (not ubuntu_stig_interactive | bool) or 
    (_proceed | default(false) | bool)
```

---

## 4. Benefits of this Approach

1.  **Visibility:** You see the "Evidence" (command output) *before* you are asked to approve the fix.
2.  **Granularity:** You can approve Rule A and deny Rule B based on live system state.
3.  **Safety:** The `abort` option allows you to stop the entire run if you see a previous task caused an unexpected side effect.
4.  **Traceability:** It enforces an "Audit-First" culture where we fix what is broken, rather than re-applying everything.

## 5. Next Steps
1. Create `vars/stig_metadata.yaml` for Ubuntu 24.04 rules.
2. Implement `tasks/stig_step.yaml` in the `internal.linux.ubuntu` role.
3. Update `tasks/ubuntu2404.yaml` to use the step-confirm pattern.
