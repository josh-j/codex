# STIG Bugs Encountered

Comprehensive catalog of bugs found and fixed during the Ubuntu 24.04 STIG
implementation. Fixed across commits `0134e8e` (43 rules) and `f975135`
(163/167 rules passing).

Each entry notes whether the `internal.core.stig` action plugin now prevents
the class of bug at the framework level.

---

## 1. Audit Mode Mutating Systems (Critical)

**Rules:** All remediation tasks (~116 occurrences)

Tasks used `not (ansible_check_mode | default(false))` as the guard to skip
remediation during audit. `ansible_check_mode` is not reliably propagated
through `import_tasks`/`include_tasks` boundaries, so remediation could run
during audit, mutating live systems.

**Fix:** Replaced all 116 occurrences with `_ubuntu2404_stig_phase != 'audit'`,
a variable explicitly set in `00_prelude.yaml`.

**Plugin prevents:** Yes. Probe always runs with `check_mode=True`; remediation
always runs with `check_mode=False`, regardless of playbook check_mode.

---

## 2. Firewall Lockout (Critical)

**Rule:** SV-270655 (UFW enable)

UFW was enabled without first adding an SSH allow rule, severing remote access
on SSH-only hosts.

**Fix:** Added `stigrule_270655_ufw_allow_ssh` (OpenSSH allow) before enable.

**Plugin prevents:** Partially. `_stig_gate` could gate on connectivity, but
ordering is a manual concern.

---

## 3. PAM Faillock Broke sudo (Critical)

**Rule:** SV-270690 (pam_faillock)

Inserting `pam_faillock.so` lines into `/etc/pam.d/common-auth` without
adjusting the `pam_unix.so` `success=N` skip count caused the PAM stack to
misalign, breaking `sudo` and all PAM-authenticated commands.

**Fix:** Replaced two `lineinfile` tasks with a single shell task running an
embedded Python script that atomically bumps the skip count and inserts faillock
lines.

**Plugin prevents:** No. PAM stack manipulation requires atomic multi-line edits
with arithmetic.

---

## 4. Auditd Immutable Flag Deadlocks

**Rule:** SV-270832 (immutable audit rules), plus all audit rule verifications

The `-e 2` immutable flag was co-located with other rules. Once loaded, the
kernel locks audit config, causing `augenrules --load` failures, handler flush
failures, and auditd entering a failed state on restart.

**Fix (multi-part):**
1. Moved `-e 2` to dedicated `99-stig-immutable.rules` (loads last)
2. Added stash/restore logic: clear immutable before remediation, restore after
3. Made `reload_audit_rules` handler non-fatal (`failed_when: false`)
4. Added auditd recovery: detect failed state, reset, hide immutable, restart

**Plugin prevents:** No. Cross-task coordination and kernel-level concerns.

---

## 5. auditctl Kernel Format Mismatch

**Rules:** All audit rule verifications in `41_audit_rule_audits.yaml`,
`42_auditd_controls.yaml`

Checks used `grep -Fqx` (exact line match) against `auditctl -l` output. The
kernel normalizes rules: `-k keyname` becomes `-F key=keyname`, `-S all` may be
added. Every live audit rule check failed.

**Fix:** Changed to `grep -F` (substring) and added `sed 's/ -k / -F key=/g'`
transformation. Added bypass when kernel is immutable (`enabled 2`).

**Plugin prevents:** No. Kernel normalization is domain-specific.

---

## 6. grep -Fqx Fragile Matching

**Rules:** All `stigrule_line_check`, `stigrule_single_line_check`,
`stigrule_dconf_lock_check`, `stigrule_dconf_ini_checks`, and individual rules:
270652, 270678, 270681, 270691, 270705, 270718, 270818, 270819, 270832

Config files may have trailing whitespace or different spacing around `=`.
`grep -Fqx` requires character-for-character match including whitespace.

**Fix:** Replaced all `grep -Fqx` with `grep -Fq` (substring match). For
sysctl checks, used `grep -Eq` with flexible whitespace regex.

**Plugin prevents:** Yes. Check-mode probe uses the actual module (lineinfile,
sysctl), which handles formatting differences natively.

---

## 7. sysctl Audit Path Mismatch

**Rule:** SV-270753 (tcp_syncookies)

Audit checked `/etc/sysctl.conf` but remediation wrote to
`/etc/sysctl.d/10-kernel-hardening.conf`.

**Fix:** Changed audit path to match remediation target.

**Plugin prevents:** Yes. Same module arguments used for both probe and
remediation, so paths are always consistent.

---

## 8. Missing Remediations (20+ Rules)

**Rules:**
- SSH: SV-270708, 270709, 270717, 270722, 270691
- System: SV-270652, 270753
- PAM: SV-270721, 270723, 270690
- Auditd: SV-270818, 270819
- Core dumps: SV-270746
- ASLR: SV-270772

Rules had audit checks but no corresponding remediation tasks.

**Fix:** Added complete remediation tasks for each. SSH settings consolidated
into `sshd_config.d/01-stig.conf`. Auditd.conf remediation added with
`auditd_sighup` handler. Core dump remediation added coredump.conf, sysctl,
and limits.d entries.

**Plugin prevents:** Partially. The plugin's single-task design
(`_stig_apply` handles both phases) makes it structurally difficult to have
an audit without a corresponding remediation.

---

## 9. Duplicate Task Definitions

**Rules:** SV-270650 (AIDE), SV-270831 (AIDE audit tools), SV-270723/270738
(pam_pkcs11)

Same rules defined in multiple task files, running twice and potentially
producing conflicting results.

**Fix:** Removed duplicates, kept canonical copies in their primary files.

**Plugin prevents:** No direct prevention, but `_stig_id` makes duplicates
easier to detect.

---

## 10. Jinja2 NoneType in SSSD Lookup

**Rule:** SV-270734 (SSSD offline_credentials)

`lookup('file', '/etc/sssd/sssd.conf', errors='ignore') | default('')`
returned `None` (not empty string) when file was missing, causing NoneType
error on string operations.

**Fix:** Changed `| default('')` to `| default('', true)` to also replace
falsy values.

**Plugin prevents:** Indirectly. `_stig_gate_files` checks file existence
before attempting to read, avoiding the NoneType path.

---

## 11. Service State Assertions

**Rules:** SV-270660 (apparmor), SV-270657 (auditd), SV-270663 (SSSD),
SV-270666 (SSH)

**(a) AppArmor oneshot:** Assert required `state == 'running'`, but apparmor
is a oneshot service showing `state == 'stopped'` after profile load.
Fix: Added `valid_states: ["running", "stopped"]`.

**(b) Stale facts:** Service facts gathered once at start didn't reflect
packages installed during remediation. Fix: Added `service_facts` refresh.

**(c) Auditd failed state:** Immutable flag issues left auditd in `failed`
state. Fix: Added recovery (reset, hide immutable, restart, restore).

**(d) Non-fatal start:** Made auditd start `failed_when: false` to avoid
aborting the entire rescue block.

**Plugin prevents:** Yes for (a). `_stig_gate_services` (exists) vs
`_stig_gate_services_running` (active) distinguishes oneshot from long-running
services.

---

## 12. Root Account Lock Check Pattern

**Rule:** SV-270724 (root account locked)

Pattern `' root L '` had a leading space. `passwd -S root` output starts with
`root`, not ` root`.

**Fix:** Changed to `'root L '`.

**Plugin prevents:** No. Content-level pattern error.

---

## 13. SSSD ldap_user_certificate Section Placement

**Rule:** SV-270736 (SSSD ldap_user_certificate)

`lineinfile` added `ldap_user_certificate=userCertificate;binary` to
`sssd.conf` without `insertafter`, so it could land in the wrong INI section.

**Fix:** Added `insertafter: '^\[domain/'`.

**Plugin prevents:** No. INI section placement is module-argument specific.

---

## 14. FIPS Token Handling

**Rule:** SV-270744 (FIPS mode)

FIPS remediation attempted `ua enable fips` without checking whether an Ubuntu
Pro token was defined, producing confusing failures.

**Fix:** Added debug warning when token is empty; audit correctly fails when
FIPS is not enabled and no token available.

**Plugin prevents:** Yes. `_stig_gate_vars` with
`stig_2404_stigrule_270744_pro_token: "non-empty"` gates the rule.

---

## 15. AppArmor Enforce Missing

**Rule:** SV-270660 (AppArmor)

Remediation enabled/started apparmor but did not run `aa-enforce` to put
profiles into enforce mode.

**Fix:** Added `aa-enforce /etc/apparmor.d/*` task.

**Plugin prevents:** No. Domain-specific remediation completeness.

---

## 16. Audit Log Assert Variable Mismatch

**Rules:** SV-270827 (permissions), SV-270828 (ownership)

Assert task named `stigrule_270828` was supposed to verify log permissions
(270827) but referenced the wrong register variable.

**Fix:** Renamed task, corrected register reference and manage variable.

**Plugin prevents:** Partially. `_stig_id` inference from task names would
flag a mismatch.

---

## 17. auditd.conf action_mail_acct Invalid Email

**Rule:** SV-270819 (action_mail_acct)

Default `root@localhost` may not be accepted by all MTA configurations.

**Fix:** Changed to `root@localhost.localdomain`.

**Plugin prevents:** No. Value correctness issue.

---

## 18. Playbook SSH Key Requirement

**Rules:** All (playbook-level)

Playbooks unconditionally wrote a vault SSH key, failing when no key was
defined.

**Fix:** Added `when: vault_logservers_private_key | default('') | trim | length > 0`
guard and `omit` fallback for `ansible_ssh_private_key_file`.

**Plugin prevents:** No. Playbook configuration issue.

---

## 19. False Compliance for Non-Installed Components

**Rules:** SV-270721/270723 (pam_pkcs11), SV-270734/270735/270736 (SSSD)

Config file checks passed when skeleton configs existed but the underlying
software was absent or not running.

**Fix:** Added functional pre-checks: `dpkg -l pam-pkcs11` and `.so` file
existence for pam_pkcs11; `systemctl is-active sssd.service` for SSSD.

**Plugin prevents:** Yes. `_stig_gate_packages`, `_stig_gate_services`, and
`_stig_gate_services_running` gate rules on software presence and state.

---

## 20. Sudo Group Auto-Whitelist

**Rule:** SV-270748 (authorized sudo group members)

Ansible user was auto-excluded from the sudo group membership check, masking
a real finding.

**Fix:** Removed the auto-whitelist.

**Plugin prevents:** No. Policy/logic issue.

---

## 21. Immutable Flag Check Location

**Rule:** SV-270832 (audit rules immutable)

Check only looked in `/etc/audit/audit.rules` (compiled output), not the
source `rules.d/*.rules` files.

**Fix:** Changed grep to search both locations.

**Plugin prevents:** No. Domain-specific knowledge required.

---

## Plugin Prevention Summary

| Category | Plugin Prevents? |
|----------|-----------------|
| 1. Audit-mode mutations | **Yes** |
| 2. Firewall lockout | Partially |
| 3. PAM stack breakage | No |
| 4. Auditd immutable deadlocks | No |
| 5. auditctl format mismatch | No |
| 6. grep fragile matching | **Yes** |
| 7. Audit/remediation path mismatch | **Yes** |
| 8. Missing remediations | Partially |
| 9. Duplicate tasks | No |
| 10. Jinja2 NoneType | Indirectly |
| 11. Service state assertions | **Yes** (oneshot) |
| 12. Regex typos | No |
| 13. INI section placement | No |
| 14. Missing variable gating | **Yes** |
| 15. Missing remediation steps | No |
| 16. Assert variable mismatch | Partially |
| 17. Invalid config values | No |
| 18. Playbook config | No |
| 19. Functional pre-checks | **Yes** |
| 20. Policy exceptions | No |
| 21. Check file location | No |

The plugin structurally prevents **6 full categories** and partially mitigates
**4 more** out of 21 total.
