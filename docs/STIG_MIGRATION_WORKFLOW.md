# STIG Migration & Testing Verification Workflow

This document captures the end-to-end workflow for migrating a platform's STIG role to `internal.core.stig` and verifying it against the official DISA CKLB. It is based on the Photon OS 3.0 and ESXi 7.0 migrations completed in March 2026.

---

## Table of Contents

1. [Overview](#overview)
2. [Phase 1 — Planning](#phase-1--planning)
3. [Phase 2 — Implementation](#phase-2--implementation)
4. [Phase 3 — Infrastructure Setup](#phase-3--infrastructure-setup)
5. [Phase 4 — Iterative Testing](#phase-4--iterative-testing)
6. [Phase 5 — CKLB Verification](#phase-5--cklb-verification)
7. [Phase 6 — Fix Mismatches](#phase-6--fix-mismatches)
8. [Common Pitfalls](#common-pitfalls)
9. [Reference Commands](#reference-commands)

---

## Overview

The migration workflow converts a legacy STIG role (using raw Ansible modules or query+assert patterns) to the `internal.core.stig` action plugin. The plugin provides:

- **Unified audit/remediate** — one task file, two modes via `check_mode`
- **Structured results** — the `ncs_collector` callback captures pass/fail/na per rule
- **Gate logic** — skip rules when packages/services/files are missing
- **Validator probes** — shell-based compliance checks for non-idempotent operations

The goal is 100% CKLB rule coverage with accurate pass/fail reporting verified against the official DISA check commands.

---

## Phase 1 — Planning

### 1.1 Inventory the CKLB

Extract all rules from the CKLB skeleton and map them to implementation tasks:

```bash
python3 -c "
import json
with open('files/ncs-reporter_configs/cklb_skeletons/<SKELETON>.json') as f:
    cklb = json.load(f)
for r in cklb['stigs'][0]['rules']:
    print(f'{r[\"rule_version\"]:>20} | {r[\"group_id_src\"]:>12} | {r[\"severity\"]:<8} | {r[\"group_title\"][:60]}')
"
```

This gives you the complete rule list with V-IDs, rule versions (e.g., `PHTN-30-000001`), severities, and titles.

### 1.2 Categorize Rules

Group rules by implementation pattern:

| Pattern | When to use | Example |
|---------|-------------|---------|
| `lineinfile` | Config file key=value settings | sshd_config, login.defs, auditd.conf |
| `ansible.builtin.file` | File/directory permissions, ownership | /var/log, /root, sshd_config perms |
| `shell+validator` | Non-idempotent operations, PAM, complex checks | pam_tally2, grub, systemctl mask |
| `validate_expr` | Pre-gathered facts, no shell probe needed | ESXi advanced settings, bulk-gathered data |
| `stig_pwsh` | PowerCLI/vSphere rules (ESXi, vCenter) | esxcli, Get-VMHost, firewall rulesets |
| `ansible.posix.sysctl` | Kernel parameters | tcp_syncookies, ip_forward |
| `ansible.builtin.service` | Service enable/start | auditd, sshd |
| `audit-only` | Cannot auto-remediate (duplicate UIDs, unowned files) | `cmd: "true"` with validator |
| `template` (raw) | Multi-line config files | audit rules, modprobe.conf |

### 1.3 Identify What to Delete

List all artifacts from the old implementation that will be replaced:
- Old task files (version-branched)
- Version-specific defaults/vars files
- Templates only used by the old version
- Version-branching logic in `stig.yaml` and `remediate.yaml`

### 1.4 Map Multi-Rule IDs

Some CKLB entries share a single implementation (e.g., audit rules template covers 10+ rules). Each CKLB rule MUST have its own `stigrule_` task for the collector to report it. Plan individual validator tasks for shared implementations.

---

## Phase 2 — Implementation

### 2.1 File Structure

```
roles/<platform>/
├── defaults/main.yml          # All run_* control flags + role behaviour vars
├── vars/main.yml              # Static values (paths, thresholds)
├── handlers/main.yml          # Static handler names with listen aliases
├── tasks/
│   ├── main.yaml              # Dispatcher: include_tasks {{ action }}.yaml
│   ├── discover.yaml           # OS validation + telemetry
│   ├── stig.yaml              # Three-phase orchestrator
│   ├── remediate.yaml          # Sets hardening=true, includes stig.yaml
│   ├── <platform>.yaml         # Import dispatcher for sub-task files
│   └── <platform>_stigs/
│       ├── 00_prelude.yaml     # Phase setup, facts, prereq installs, backups
│       ├── 10_packages_services.yaml
│       ├── 20_ssh_crypto.yaml
│       ├── 30_system_config.yaml
│       ├── 40_audit_config.yaml
│       └── 50_file_permissions.yaml
```

### 2.2 Three-Phase Orchestrator (`stig.yaml`)

```yaml
# Phase 0: Determine mode
_stig_audit_only: "{{ enable_audit and not enable_hardening }}"

# Phase 1: Execute tasks (check_mode = audit_only)
include_tasks: <platform>.yaml
  apply:
    check_mode: "{{ _stig_audit_only }}"

# Phase 2: Post-remediation verification (remediate only)
include_tasks: <platform>.yaml
  apply:
    check_mode: true
  when: not _stig_audit_only
```

### 2.3 Prelude (`00_prelude.yaml`)

Critical setup tasks that run before any STIG rules:

1. **Set `_stig_active_phase`** — the action plugin reads this to determine audit vs remediate
2. **Gather package facts** — with fallback for systems where `package_facts` module fails
3. **Gather service facts** — for gate checks
4. **Install prerequisites** (remediate only) — packages like `audit`, `rsyslog` that other rules depend on
5. **Refresh facts** after installs — so gate checks see newly installed packages
6. **Create backups** (remediate only)

**Package facts fallback pattern** (for systems where the Python RPM binding doesn't load):

```yaml
- name: "Gather package facts"
  ansible.builtin.package_facts:
    manager: rpm
  ignore_errors: true
  register: _pkg_facts_result

- name: "Fallback package facts via rpm -qa"
  ansible.builtin.shell:
    cmd: |
      python3 -c "
      import subprocess, json
      pkgs = subprocess.check_output(['rpm', '-qa', '--qf', '%{NAME}\n'], text=True).strip().split('\n')
      print(json.dumps({p: [{'source': 'rpm'}] for p in set(pkgs) if p}))
      "
  register: _rpm_qa_json
  when: _pkg_facts_result is failed or (ansible_facts.packages | default({})) == {}

- name: "Set fallback package facts"
  ansible.builtin.set_fact:
    ansible_facts: "{{ ansible_facts | combine({'packages': _rpm_qa_json.stdout | from_json}) }}"
  when: _rpm_qa_json is not skipped and _rpm_qa_json.rc | default(1) == 0
```

### 2.4 Rule Task Patterns

**Lineinfile rule:**
```yaml
- name: "stigrule_PHTN-30-000080"
  internal.core.stig:
    _stig_apply: ansible.builtin.lineinfile
    _stig_manage: "{{ run_sshd_x11forwarding }}"
    _stig_notify: [handler_restart_sshd]
    path: /etc/ssh/sshd_config
    regexp: '^#?\s*X11Forwarding\s'
    line: "X11Forwarding no"
    state: present
```

**Shell + validator rule:**
```yaml
- name: "stigrule_PHTN-30-000076"
  internal.core.stig:
    _stig_apply: ansible.builtin.shell
    _stig_use_check_mode_probe: false
    _stig_manage: "{{ run_service_debug_shell }}"
    _stig_validate: ansible.builtin.shell
    _stig_validate_args:
      cmd: |
        state="$(systemctl is-enabled debug-shell.service 2>/dev/null)" || state="not-found"
        [ "$state" = "masked" ] || [ "$state" = "disabled" ] || [ "$state" = "not-found" ]
    cmd: |
      set -eu
      systemctl stop debug-shell.service 2>/dev/null || true
      systemctl mask debug-shell.service
```

**Audit-only rule (no auto-remediation):**
```yaml
- name: "stigrule_PHTN-30-000033"
  internal.core.stig:
    _stig_apply: ansible.builtin.shell
    _stig_use_check_mode_probe: false
    _stig_manage: "{{ run_duplicate_user_uids }}"
    _stig_validate: ansible.builtin.shell
    _stig_validate_args:
      cmd: |
        set -eu
        test -z "$(awk -F: '{print $3}' /etc/passwd | sort -n | uniq -d)"
    _stig_skip_post_validate: true
    cmd: "true"
```

**Template rule** (cannot be wrapped — use raw task with phase gate):
```yaml
- name: "stigrule_PHTN-30-000001"
  internal.core.stig:
    _stig_apply: ansible.builtin.shell
    _stig_use_check_mode_probe: false
    _stig_manage: "{{ run_auditd_rules }}"
    _stig_gate_packages: [audit]
    _stig_validate: ansible.builtin.shell
    _stig_validate_args:
      cmd: |
        set -eu
        [ -f /etc/audit/rules.d/audit.STIG.rules ]
        grep -cE '^\s*-[aw]' /etc/audit/rules.d/audit.STIG.rules | grep -qv '^0$'
    cmd: "true"

- name: "stigrule_PHTN-30-000001 - Deploy audit rules template"
  ansible.builtin.template:
    src: audit.STIG.rules
    dest: /etc/audit/rules.d/audit.STIG.rules
  when:
    - run_auditd_rules | bool
    - "'audit' in (ansible_facts.packages | default({}))"
    - _phase != 'audit'
```

**Validate-expr rule** (pre-gathered facts, no shell probe):
```yaml
- name: "stigrule_256379"
  internal.core.stig:
    _stig_apply: community.vmware.vmware_host_config_manager
    _stig_manage: "{{ (esxi_70_000005_manage | default(true)) and (_esxi_bulk_ok | default(false)) }}"
    _stig_validate_expr:
      - var: _adv_Security_AccountLockFailures
        equals: "{{ esxi_stig_account_lock_failures | default(3) }}"
    _stig_use_check_mode_probe: false
    _stig_skip_post_validate: true
    esxi_hostname: "{{ _current_esxi_host }}"
    options:
      Security.AccountLockFailures: "{{ esxi_stig_account_lock_failures | default(3) }}"
```

`_stig_validate_expr` evaluates variable conditions without running any module. Supported operators:
- `equals` — case-insensitive string comparison
- `equals_unordered` — comma-separated values compared as sets (order-independent), with optional `separator` key
- `contains` — substring check (case-insensitive)
- `matches` — regex match
- `not_empty` — value must be non-empty

Use `_stig_validate_expr` with a "bulk gather" pattern (one shell/pwsh invocation that collects all data, parsed into Ansible facts via `set_fact`) to eliminate per-rule shell probes. This is the primary performance optimization for platforms with expensive probe commands (e.g., PowerCLI on ESXi: 17 probes × 4.5s → 1 gather × 7s).

**PowerCLI rule** (ESXi/vSphere — use `internal.core.stig_pwsh`):
```yaml
# Audit-only — no script needed
- name: "stigrule_256430"
  internal.core.stig_pwsh:
    _stig_audit_only: true
    _stig_manage: "{{ ... }}"
    _stig_validate_expr:
      - var: _encryption_require_secure_boot
        equals: "true"

# With remediation — just the PowerShell, no boilerplate
- name: "stigrule_256442"
  internal.core.stig_pwsh:
    _stig_manage: "{{ ... }}"
    _stig_validate_expr:
      - var: _fips_rhttpproxy_enabled
        equals: "true"
    script: |
      $args = $esxcli.system.security.fips140.rhttpproxy.set.CreateArgs()
      $args.enable = $true
      $esxcli.system.security.fips140.rhttpproxy.set.Invoke($args) | Out-Null
```

`internal.core.stig_pwsh` is a specialization of `internal.core.stig` that:
- Handles PowerCLI connection boilerplate (Connect-VIServer, `$vmhost`/`$esxcli`/`$view` setup)
- Eliminates `\$` escaping — write normal PowerShell in `script`
- Passes credentials via environment variables (from `_stig_module_defaults`)
- Defaults `_stig_use_check_mode_probe: false` and `_stig_skip_post_validate: true`
- Strips `\r` and handles timeouts automatically

### 2.5 Key Rules

- **DO NOT use `block`/`module_defaults`** for STIG rules. Ansible-core 2.17 does not call runner callbacks for tasks inside blocks when the action plugin returns `skipped: True`. Every `stigrule_` task must be a top-level task with explicit parameters.
- **DO NOT use `no_log: true`** on `stigrule_` tasks. Ansible censors the entire result dict including structured STIG data, making the rule invisible to `ncs_collector`. Credentials passed via environment variables (e.g., `$env:VC_PASS`) are already safe — the actual password value never appears in task output.
- **DO NOT use `ansible.builtin.template` or `ansible.builtin.systemd`** as `_stig_apply` — they are action plugins, not modules. Use `ansible.builtin.service` instead of `systemd`. Use raw template tasks gated on phase for templates.
- **Use `internal.core.stig_pwsh`** for PowerCLI rules instead of `_stig_apply: ansible.builtin.shell` with manual `\$` escaping and preamble boilerplate. It handles connection, escaping, CR stripping, and timeouts automatically.
- **Handler names must be static** — `_stig_notify` cannot resolve dynamic `{{ role_name }}` handler names. Use fixed names like `photon_restart_sshd` with `listen` aliases for backwards compatibility.
- **Use `--` before grep patterns starting with `-`** to prevent them being parsed as options: `grep -qE -- '-w\s+/etc/passwd' file`.
- **Avoid `grep -P` (PCRE)** — some minimal Linux installs (Photon 3) compile grep without PCRE support. Use `grep -E` (ERE), `awk`, or `sed` instead.
- **Use `| default({})` for `ansible_facts.packages`** in `when` clauses on raw tasks — if `package_facts` failed, the dict won't exist.

---

## Phase 3 — Infrastructure Setup

### 3.1 Test VM Preparation

1. **Provision a clean VM** of the target OS
2. **Set static IP** and enable SSH root login with password auth
3. **Create a VM snapshot** (`pre-stig-test`) for rollback between test cycles
4. **Verify Ansible connectivity**:

```bash
.venv/bin/ansible -i "IP," -m ping all \
  -e "ansible_user=root ansible_password=PASS ansible_python_interpreter=/usr/bin/python3"
```

### 3.2 Ansible Version Compatibility

Check the target OS Python version. Ansible-core version requirements:

| Target Python | Max ansible-core |
|--------------|-----------------|
| 3.7          | 2.17.x          |
| 3.8-3.9      | 2.18.x          |
| 3.10+        | latest           |

If needed, create a compatibility venv:
```bash
uv venv .venv-compat
uv pip install --python .venv-compat/bin/python 'ansible-core>=2.17,<2.18'
```

### 3.3 Required Collections

```bash
.venv/bin/ansible-galaxy collection install ansible.posix -p collections/
```

---

## Phase 4 — Iterative Testing

### 4.1 Test Loop

```
┌─────────────────────────────┐
│  Rollback VM to snapshot    │
├─────────────────────────────┤
│  Run audit playbook         │
│  Check for fatals/errors    │
│  Fix task issues            │
├─────────────────────────────┤
│  Run remediate playbook     │
│  Check changed count        │
│  Verify SSH still works     │
├─────────────────────────────┤
│  Run audit playbook again   │
│  Generate STIG report       │
│  Identify remaining gaps    │
└─────────────────────────────┘
         ↑ repeat until clean
```

### 4.2 Audit Run

```bash
ANSIBLE_CALLBACKS_ENABLED=internal.core.ncs_collector \
  .venv/bin/ansible-playbook playbooks/<platform>_stig_audit.yml \
  -i "IP," -v \
  -e "ansible_user=root ansible_password=PASS ansible_python_interpreter=/usr/bin/python3 target_hosts=all"
```

**What to check:**
- `PLAY RECAP` — 0 failed, 0 rescued
- `ncs_collector` — STIG data persisted
- Rule count — all `stigrule_` tasks executed

### 4.3 Remediation Run

```bash
ANSIBLE_CALLBACKS_ENABLED=internal.core.ncs_collector \
  .venv/bin/ansible-playbook playbooks/<platform>_stig_remediate.yml \
  -i "IP," -v \
  -e "ansible_user=root ansible_password=PASS ansible_python_interpreter=/usr/bin/python3 target_hosts=all"
```

**What to check:**
- `changed` count > 0 (remediations applied)
- SSH still works after run (sshd config changes can break connectivity)
- No rescued tasks

### 4.4 STIG Report

```bash
.venv/bin/python internal/linux/roles/ubuntu/files/stig_report.py \
  /srv/samba/reports/platform/<path>/raw_stig_<type>.yaml \
  files/ncs-reporter_configs/cklb_skeletons/<skeleton>.json
```

**Target metrics:**
- 0 "No collector data" — every CKLB rule maps to a task
- 0 "Not Reviewed" — all rules either pass, fail, or have documented gate reasons
- Passing % increases with each iteration

### 4.5 Common Iteration Issues

| Symptom | Cause | Fix |
|---------|-------|-----|
| `rescued=N` | A task fataled, triggering rescue block | Fix the failing task; all subsequent tasks were skipped |
| `"No collector data"` in report | Rule has no matching `stigrule_` task | Add a task for that CKLB rule |
| `"Missing packages: X"` | Gate blocked rule because package not installed | Add prereq install to prelude |
| Rules not in raw_stig output | Collector regex didn't extract rule ID | Check `_extract_rule_number` patterns |
| SSH connection lost after remediate | sshd config change broke SSH | Disable `FipsMode`/`ListenAddress` with `-e run_sshd_fipsmode=false` |
| `module is missing interpreter line` | Tried to wrap action plugin (template/systemd) | Use raw task or `ansible.builtin.service` |

---

## Phase 5 — CKLB Verification

Once the report shows acceptable compliance, verify against the actual DISA check commands.

### 5.1 Extract Check Commands

```python
import json, re
with open('files/ncs-reporter_configs/cklb_skeletons/<SKELETON>.json') as f:
    cklb = json.load(f)
for r in cklb['stigs'][0]['rules']:
    check = r.get('check_content', '')
    cmds = re.findall(r'^# (.+)$', check, re.MULTILINE)
    # cmds contains the shell commands from the DISA check procedure
```

### 5.2 Run Check Commands on VM

For each rule:
1. Read the `check_content` to understand pass/fail criteria
2. Run the extracted shell command(s) on the target VM
3. Evaluate output against the DISA criteria
4. Compare with automation result

### 5.3 Parallel Verification

Split the 113 rules into 3 batches and run verification agents in parallel. Each agent:
- SSHes to the VM and runs the DISA check commands
- Evaluates pass/fail per the `check_content` text
- Compares with the automation's reported status
- Reports mismatches

### 5.4 Expected Mismatch Categories

| Category | Example | Resolution |
|----------|---------|------------|
| **Validator too strict/loose** | Regex doesn't match actual config format | Fix validator regex |
| **Missing options** | PAM line missing `onerr=fail audit` | Add options to remediation |
| **Wrong check command** | Using `rpm -Va` instead of `rpm -V audit` | Match DISA check exactly |
| **Gate reports N/A, DISA says FAIL** | Missing file gated as N/A but STIG requires it | Remove gate, add remediation to create file |
| **Regex option parsing** | `grep '-w...'` interpreted as grep `-w` flag | Use `grep -- '-w...'` |
| **Shell incompatibility** | `grep -P` not available | Use `grep -E` or `awk` |

---

## Phase 6 — Fix Mismatches

### 6.1 Priority Order

1. **False passes** (automation says pass, DISA says fail) — highest priority, security gap
2. **False fails** (automation says fail, DISA says pass) — noise, wastes reviewer time
3. **N/A vs fail** — gate logic too aggressive, should remediate instead
4. **Validator regex issues** — match the exact DISA check command semantics

### 6.2 Validation After Fixes

After each fix batch:
1. Rollback VM to snapshot
2. Run remediate playbook
3. Run audit playbook
4. Generate report
5. Spot-check fixed rules with DISA commands

### 6.3 Final Acceptance Criteria

- [ ] **113/113 CKLB rules** have corresponding `stigrule_` tasks
- [ ] **0 "Not Reviewed"** and **0 "No collector data"** in report
- [ ] All **Open findings** are intentionally disabled (`_stig_manage: false`) with documented reasons
- [ ] **CKLB verification** shows 0 false passes (our pass = DISA pass)
- [ ] **Remediate playbook** completes with 0 failed, 0 rescued
- [ ] **Post-remediation audit** shows no regression
- [ ] SSH connectivity survives remediation
- [ ] Playbook syntax check passes: `ansible-playbook --syntax-check`

---

## Common Pitfalls

### Ansible-Specific

- **`module_defaults` blocks hide tasks from callbacks** — flatten all `stigrule_` tasks to top-level
- **`ansible.builtin.template`** and **`ansible.builtin.systemd`** are action plugins — cannot be used as `_stig_apply`
- **`set_fact` inside `include_tasks`** with `check_mode` override — facts propagate but `ansible_check_mode` reflects the override
- **`package_facts` requires Python bindings** — `python3-rpm` on RHEL/Photon, `python3-apt` on Debian. Always provide a fallback.

### Shell-Specific

- **`grep -P`** (PCRE) not available on all systems — use `grep -E` (ERE)
- **`grep -oP '...\K...'`** — use `awk` instead: `awk '/pattern/ {sub(/.*=\s*/, ""); print}'`
- **Patterns starting with `-`** — `grep '-w /etc/passwd'` fails because `-w` is a grep flag. Use `grep -- '-w /etc/passwd'`
- **`set -eu`** in validators — non-zero exit from `systemctl is-enabled` (even for "masked") triggers `set -e` abort. Handle with `|| state="fallback"`.
- **`xargs dirname`** with empty input — fails on some systems. Add `2>/dev/null` or check for empty.

### PowerCLI-Specific

- **Use `internal.core.stig_pwsh`** — eliminates `\$` escaping, preamble boilerplate, and credential handling. Write normal PowerShell.
- **Single-quote vs double-quote context** — if you must use `ansible.builtin.shell` for PowerCLI, the `_pwsh_preamble` uses `\$` escaping designed for double-quoted bash context (`pwsh -Command "..."`). Using single quotes (`pwsh -Command '...'`) passes `\$` literally to PowerShell, breaking the connection. Prefer `stig_pwsh` to avoid this entirely.
- **Comma-separated value ordering** — ESXi may return values like `sslv3,tlsv1,tlsv1.1` in a different order than configured. Use `equals_unordered` in `_stig_validate_expr` instead of `equals` for such fields.
- **Bulk gather pattern** — spawn one `pwsh` process that collects all data (advanced settings, esxcli queries, port groups, etc.) and outputs JSON. Parse into Ansible facts, then use `_stig_validate_expr` for each rule. This reduces 17 × 4.5s PowerCLI invocations to 1 × 7s.

### Collector-Specific

- **Rule ID extraction regex** — `\b` word boundary doesn't match after `_` (underscore is a word character). The collector's Pattern 3 uses `(?:^|[\s_])` to handle `stigrule_PHTN-30-...`.
- **`_infer_stig_id`** in action plugin returns `None` for non-numeric IDs — the collector falls back to `_extract_rule_number` from the task name.
- **Skipped results from gate checks** — the action plugin returns `skipped: True` with structured data. The collector's `v2_runner_on_ok` handles this.
- **`no_log: true` censors structured STIG data** — when a task has `no_log: true`, Ansible replaces the entire result dict with `{"censored": "..."}`. The collector cannot extract the STIG status. Without the censored-result guard, the collector infers "pass" from any ok/unchanged censored task — a **false pass**. The fix: the collector skips censored results that have no structured data, and `stigrule_` tasks should never use `no_log`.

### Testing-Specific

- **pam_tally2 lockout** — failed SSH attempts from parallel agents can lock the root account. Reset with `pam_tally2 --user=root --reset` or by mounting the disk.
- **SSH FipsMode** — enabling this on systems without kernel FIPS breaks sshd. Always test with `-e run_sshd_fipsmode=false` initially.
- **ListenAddress** — binding to a specific IP that doesn't match the VM's interface kills SSH. Disable with `-e run_sshd_listenaddress=false`.
- **VM snapshot before testing** — always snapshot before remediation. Rollback is faster than debugging a broken system.

---

## Reference Commands

### Rollback VM (Proxmox)
```bash
ssh root@PROXMOX 'qm stop VMID --timeout 30; sleep 3; qm rollback VMID SNAPSHOT; sleep 2; qm start VMID'
```

### Count Rules in Task Files
```bash
grep -ohP 'PHTN-30-\d{6}' tasks/<platform>_stigs/*.yaml | sort -u | wc -l
```

### Compare CKLB vs Raw Data
```python
import yaml, json
raw_ids = {row['id'] for row in yaml.safe_load(open('raw_stig.yaml')).get('data', [])}
cklb_ids = {r['rule_version'] for stig in json.load(open('skeleton.cklb'))['stigs'] for r in stig['rules']}
print(f'Missing: {sorted(cklb_ids - raw_ids)}')
print(f'Extra: {sorted(raw_ids - cklb_ids)}')
```

### Debug Collector
```bash
NCS_COLLECTOR_DEBUG_STIG=1 ANSIBLE_CALLBACKS_ENABLED=internal.core.ncs_collector \
  ansible-playbook ... 2>&1 | grep '\[ncs_collector\]'
```

### YAML Syntax Validation
```bash
python3 -c "
import yaml, glob
for f in glob.glob('roles/*/tasks/**/*.yaml', recursive=True):
    yaml.safe_load(open(f))
print('All OK')
"
```

---

## Photon 3 Migration Results

Final results on a minimal Photon OS 3.0 VM (non-VCSA):

| Metric | Value |
|--------|-------|
| Total CKLB rules | 113 |
| Not a Finding | 110 (97.3%) |
| Open (intentionally disabled) | 3 (2.7%) |
| Not Reviewed | 0 |
| CKLB verification match rate | 106/113 (93.8%) → fixed to ~100% |
| Remediation changes applied | 98 |
| Prerequisite packages installed | audit, rsyslog |
| Ansible-core version | 2.17.14 (Python 3.7 compat) |

## ESXi 7.0 Migration Results

Final results on a standalone ESXi 7.0 VM (no vCenter, no TPM):

| Metric | Value |
|--------|-------|
| Total CKLB rules | 75 |
| Not a Finding (post-remediation) | 59 (78.7%) |
| Open (expected — no TPM/AD/NTP) | 13 (17.3%) |
| Not Applicable (missing vars) | 3 (4.0%) |
| Not Reviewed | 0 |
| Audit wall clock time | 29s (down from 138s — 79% reduction) |
| Bulk PowerCLI gather | 7s (replaces 17 × 4.5s individual probes) |
| Rules using `stig_pwsh` | 25 |
| Rules using `validate_expr` | 48 |
| Ansible-core version | 2.18.x |

### ESXi Performance Optimization

The bulk gather pattern (`pwsh_bulk_gather.yaml`) connects to vCenter once and collects all data needed by ~48 rules in a single PowerShell invocation. Each rule then uses `_stig_validate_expr` to check pre-gathered facts instead of spawning a new `pwsh` process.

| Component | Before | After |
|-----------|--------|-------|
| PowerCLI shell probes (17×) | 77s | 0s (expr) |
| config_manager check-mode probes (26×) | 13s | 0s (expr) |
| Bulk gather (1×) | — | 7s |
| SSH config gather (1×) | 11s | 11s |
| Total | 138s | 29s |
