# Scaffold a ground-up `stig_<version>/` task folder from an XCCDF benchmark

You are a coding agent working in the **ncs-framework** umbrella repo.
This repo already ships several fully-built STIG task folders that share
a common shape. Your job here is to take a DISA XCCDF benchmark for a
new STIG and produce a brand-new `stig_<version>/` task folder that
matches those conventions exactly — not a port of one specific sibling,
but a clean scaffold driven by the XCCDF itself.

Do **not** wire the new folder into the collection's dispatcher or any
playbook. Scaffolding only. The operator will review the folder in isolation,
then register it.

---

## 0. Inputs you must collect from the operator before starting

Ask for any of these that are missing. Do not guess:

1. **XCCDF path(s)** — usually `*_Manual-xccdf.xml` out of the DISA STIG zip.
   If a profile has multiple benchmarks, take all of them.
2. **Target platform + sub-platform**, one of:
   - `linux/ubuntu`, `linux/photon`, `linux/rhel`, `linux/<other>`
   - `vmware/esxi`, `vmware/vcsa`, `vmware/vm`
   - `windows/server`, `windows/domain`, `windows/workstation`
   - `aci/<sub>`
   This selects the destination:
   `ncs-ansible-<platform>/roles/<sub_platform>/tasks/stig_<version>/`.
3. **Version slug** — lowercase, no spaces, matches existing style.
   Examples in-tree: `stig_2404`, `stig_photon3`, `stig_v7r4`, `stig_v1r4`,
   `stig_ws2022`. Pick whatever reads cleanly for the new benchmark (e.g.
   `stig_rhel9_v2r3`, `stig_esxi8_v1r1`, `stig_win11_v2r1`).
4. **`_stig_manage_prefix`** — the variable-name prefix the `internal.core.stig`
   plugin uses for `_stig_manage` auto-resolution and for per-rule tunables.
   Examples: `stig_2404_` (Ubuntu), `esxi_stig_` (ESXi), `stig_ws2022_`
   (Windows Server 2022). The convention is `<version_slug>_` or
   `<sub_platform>_stig_`.

---

## 1. Reference files — read these before generating anything

Open each of these and study the shape. Reproduce the shape, not the content.

- Folder layouts:
  - `ncs-ansible-linux/roles/ubuntu/tasks/stig_2404/` — OS-service groupings,
    good reference for Linux STIGs.
  - `ncs-ansible-vmware/roles/esxi/tasks/stig_v7r4/` — config-manager /
    advanced-settings / module-based groupings, good reference for
    API-driven platforms.
  - `ncs-ansible-windows/roles/server/tasks/stig_ws2022/` — minimal Windows
    reference.
- Dispatchers:
  - `ncs-ansible-linux/roles/ubuntu/tasks/stig_2404/main.yaml`
  - `ncs-ansible-vmware/roles/esxi/tasks/stig_v7r4/main.yaml`
- Prelude: `ncs-ansible-linux/roles/ubuntu/tasks/stig_2404/00_prelude.yaml`
- Defaults: `ncs-ansible-linux/roles/ubuntu/tasks/stig_2404/default.yaml`
- Canonical rule shape: `ncs-ansible-vmware/roles/esxi/tasks/stig_v7r4/10_config_manager.yaml`
- The STIG wrapper module itself: `ncs-ansible-core/plugins/modules/stig.py`
  — read the DOCUMENTATION block so you know every `_stig_*` key available
  (`_stig_apply`, `_stig_validate_expr`, `_stig_gate_*`, `_stig_manage`,
  `_stig_manage_prefix`, `_stig_phase`, nested-FQCN form, etc.).

---

## 2. Parse the XCCDF

For every `<Rule>` element, extract:

- `@id` — the STIG-ID (e.g. `SV-256376r960735_rule`, `ESXI-70-000002`).
- `version` — the V-ID (e.g. `V-256376`). Strip the `V-` for the numeric rule
  id used in task names.
- `title` — one-line control description.
- `<check><check-content>` — the audit procedure DISA expects.
- `<fixtext>` — the remediation text.
- `<ident system="http://cyber.mil/cci">` entries — CCIs.
- `severity` — cat I/II/III.

Keep this in memory as a structured list; you will need it for bucketing,
default-var generation, and comment generation.

---

## 3. Bucket rules into topical numbered files

Group by subject so each file stays readable. Use 10/20/30… spacing so later
inserts are cheap. Typical buckets by platform:

**Linux** (modeled on `stig_2404/`):
- `10_packages_services` — apt/dnf/systemd state
- `20_ssh_crypto` — sshd_config, crypto policies
- `30a_kernel_boot`, `30b_ssh_system`, `30c_accounts_pam`, `30d_audit_logging`
- `31_system_config_audits` (audit-only)
- `32_access_pam`
- `33_fs_network_pki`
- `34_aide`
- `35_remaining_fs_audit`
- `40_audit_rules`, `40a_audit_rule_flush`, `41_audit_rule_audits` (audit-only)
- `42_auditd_controls`
- `90_post_stig`

**ESXi-like / API-driven** (modeled on `stig_v7r4/`):
- `10_config_manager` — settings via `vmware_host_config_manager`
- `20_advanced_settings` — advanced config
- `30_other_modules`
- `40_vswitch_security`
- `50_network_audit`, `60_firmware_audit`, `61_remaining_audit_only_rules`
- `70_ssh_config`
- `80_explicit_remediation`, `81_service_manager`
- `90_post_stig`

**Windows** (modeled on `stig_ws2022/`):
- `10_security_baseline`
- Add topical splits (`20_account_policies`, `30_audit_policy`,
  `40_firewall`, `50_services`, etc.) only once rule count justifies it.

Pick groupings that actually fit the benchmark you were given. Do not create
empty bucket files.

---

## 4. Generate `default.yaml`

Shape it like `stig_2404/default.yaml`:

1. Top banner block titled **SITE-SPECIFIC — must be configured per-environment
   before use**. Put every var that has no safe default here: syslog/SIEM host,
   NTP server, authorized sudoers, LDAP URI, welcome/banner text, etc. Leave
   them as `""` or empty lists with a comment pointing at the rule(s) that
   consume them.
2. Below the banner, one block per rule that has a tunable, keyed
   `<_stig_manage_prefix>stigrule_<numeric-V-ID>_<field>`. Set DISA-default
   values. Example: `stig_2404_stigrule_270751_chrony_server: "172.25.70.11"`.
3. No `_manage` flags in `default.yaml` — the plugin auto-resolves
   `<prefix>stigrule_<id>_manage` at runtime, so only define one if the
   operator needs to ship disabled-by-default.

Each block gets a one-line comment with the V-ID and STIG-ID.

---

## 5. Generate the numbered topical task files

Every rule is exactly one task that invokes `internal.core.stig`. Follow the
shape in `stig_v7r4/10_config_manager.yaml`:

```yaml
---
# <platform>/<sub>/tasks/<version_slug>/<filename>.yaml
# <one-line summary of what this file covers>

- block:

    # --- V-<id> / <STIG-ID>: <short title> ---
    - name: "stigrule_<id>"
      internal.core.stig:
        _stig_gate_vars:
          <var_name>: non-empty        # only when the rule needs a site var
        _stig_validate_expr:
          - var: <fact_or_var>
            equals: "{{ <prefix>stigrule_<id>_<field> }}"
        ansible.builtin.lineinfile:
          path: /etc/ssh/sshd_config
          regexp: '^(?i)ciphers'
          line: "Ciphers {{ <prefix>stigrule_<id>_ciphers }}"
          validate: /usr/sbin/sshd -t -f %s
```

Rules that have no mechanical remediation stay audit-only — provide
`_stig_validate_expr` (or, as a last resort, a shell check) with no
remediation module attached.

Rules:

- Task `name:` is exactly `stigrule_<numeric V-ID>`. No prefix, no extra
  words. This is what the callback plugin keys on.
- Comment above the task always cites **V-ID / STIG-ID** and a short title.
- Use `_stig_gate_vars` for required site vars (the rule short-circuits to
  `na` if the var is empty/unset).
- Use `_stig_gate_packages` / `_stig_gate_services` / `_stig_gate_services_running`
  when the rule only applies if something is installed/present/active.
- Prefer nested-FQCN remediation form over `_stig_apply:` + flat module args.
- For ESXi-style advanced settings, follow the facts-against-`_adv_*`
  convention you see in `10_config_manager.yaml` — pre-gather once in the
  prelude, audit against the fact, remediate via the module.

---

## 6. Generate `00_prelude.yaml`

Mirror `stig_2404/00_prelude.yaml`:

1. `include_vars` on `default.yaml` (tag `always`).
2. `set_fact` for `_ncs_stig_target_type: "<sub_platform>"`.
3. `set_fact` for the per-version phase var (`_<version_slug>_stig_phase`) and
   `_stig_active_phase`, both derived from `_stig_phase_hint |
   default(check_mode ? 'audit' : 'remediate')`.
4. `set_fact` for `_stig_manage_prefix: "<prefix>"`.
5. `package_facts` / `service_facts` (or the platform equivalent — e.g. for
   VMware this is where you populate `_adv_*` via `vmware_host_config_manager`
   info calls; see the ESXi prelude).
6. Install-or-ensure-present tasks for anything rules downstream absolutely
   require, gated on `phase != 'audit'`.

---

## 7. Generate `main.yaml`

Wire the numbered files in numeric order. Use:

- `import_tasks` for files whose rules are phase-aware via the wrapper plugin
  (the common case).
- `include_tasks` with `when: _<slug>_stig_phase == 'audit'` for files that
  are **entirely** audit-only (pure asserts, no remediation). Mirror how
  `stig_2404/main.yaml` mixes the two.
- Always call `00_prelude.yaml` first and `90_post_stig.yaml` (if present)
  last.
- For platforms with hard pre/post-flight requirements (e.g. ESXi services
  that must be re-locked), wrap the body in `block: … always:` and put the
  post-flight in `always:`, exactly like `stig_v7r4/main.yaml`.

---

## 8. Optional `90_post_stig.yaml`

Only emit if the platform actually needs cleanup: stop the services you
started, re-apply filesystem locks, restart auditd, rebind interfaces, etc.
Otherwise skip it and do not reference it from `main.yaml`.

---

## 9. Validate before reporting done

From `ncs-ansible/`:

```bash
just lint           # ruff
just ansible-lint
```

Resolve every finding. If a rule genuinely cannot be mechanized with the
wrappers available, keep it as an audit-only assert and call it out in your
final report instead of silencing the lint.

---

## 10. Output contract

- Every generated YAML starts with `---` and a path comment on line 2
  (e.g. `# <platform>/<sub>/tasks/<version>/<filename>.yaml`). A short
  file-header block describing the file's scope is fine (see
  `stig_v7r4/10_config_manager.yaml`).
- No per-task narration comments (no "this task does X"). The only comment
  above a rule is `# --- V-<id> / <STIG-ID>: <short title> ---`.
- Line length ≤ 120.
- Do not use `ansible.builtin.shell` for audits that can be expressed via
  `_stig_validate_expr` against pre-gathered facts.
- Do not register the new folder into the collection's top-level `stig.yaml`
  or any playbook.

## 11. Final report back to the operator

- List of files created, with paths.
- Rule count per topical bucket.
- Any rules that landed as audit-only because they could not be mechanized,
  with the V-ID and a one-line reason each.
- The names of any new site-specific vars added to `default.yaml` that must
  be filled in before the folder can run in `remediate` mode.
