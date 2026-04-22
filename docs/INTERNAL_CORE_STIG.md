# `internal.core.stig` — STIG wrapper module reference

`internal.core.stig` is the task-level primitive every built-in STIG in this
repo is written against. It wraps an arbitrary Ansible module invocation with
STIG audit/remediation semantics — gating, check-mode probing, fact-based
validation, auto-disable by variable prefix, lifecycle phases — so each rule
reads as a single task instead of a probe/apply/verify triad.

- **Module:** `ncs-ansible-core/plugins/modules/stig.py` (doc stub)
- **Implementation:** `ncs-ansible-core/plugins/action/stig.py` (action plugin)
- **Structured result key:** `stig` (configurable via `_stig_result_key`)
- **PowerShell sibling:** `internal.core.stig_pwsh` — same contract with a
  PowerShell apply module and `_stig_script` shorthand, used by the Windows
  server role.

See the authoritative option docs in the module's `DOCUMENTATION` block
(`ncs-ansible-core/plugins/modules/stig.py`); this doc is the narrative +
quick-reference companion.

---

## Design

A STIG rule normally wants to:

1. Decide whether it applies at all (package installed, service running,
   site var set, rule toggled off by operator).
2. Measure current state without mutating anything.
3. If drifted and we're in remediate mode, apply a fix.
4. Re-measure to confirm it took.
5. Report a structured pass/fail/na with a reason.

`internal.core.stig` folds all five steps into one task. The wrapped module
(any Ansible module — `ansible.builtin.lineinfile`, `community.vmware.vmware_host_config_manager`,
`ansible.windows.win_regedit`, …) is what does the actual work; the wrapper
decides when to run it, runs it with the correct check-mode flag for the
phase, and attaches the structured result.

### Phases

Controlled by `_stig_phase` (usually inherited from the `_stig_active_phase`
host fact set during `begin`):

| Phase | Purpose |
|---|---|
| `begin` | Initializes the pass. Gathers facts listed in `_stig_begin_gather`, persists `_stig_active_phase` and `_stig_manage_prefix` as host facts, and does not run an apply module. Call once at the top of a STIG pass. |
| `audit` | Probes with `check_mode=True`. Never mutates. Emits `pass` / `fail` / `na` based on the probe, validator, or `_stig_validate_expr`. |
| `remediate` | If the probe detects drift, runs the apply module with `check_mode=False`. Then optionally re-probes (`_stig_strict_verify`). |
| `end` | Cleanup hook. Clears the active-phase fact; no apply module. |

When `_stig_phase` is omitted, the plugin reads `_stig_active_phase` from
host vars. If that's also unset it defaults to `audit`. In practice: call
`begin` in the prelude, and every rule task inherits the correct phase for
the rest of the play.

### Auto-manage by prefix

Set `_stig_manage_prefix: "<slug>_"` during `begin`. From then on, every
task named `stigrule_<id>` auto-resolves `_stig_manage` by looking up
`<slug>_stigrule_<id>_manage` in task vars, defaulting to `true`. That's
how an operator disables a single rule by setting
`stig_2404_stigrule_270741_manage: false` without having to touch the
rule task itself.

### Rule ID inference

`_stig_id` is usually inferred from the task `name:` using the pattern
`stigrule_<id>` — numeric (`stigrule_270741`) or prefixed
(`stigrule_VCEM-70-000021`) both work. Override with `_stig_id:` if the
task name can't follow the convention.

### Gates

Gate checks short-circuit the rule to `na` (or `not_reviewed`, via
`_stig_gate_status`) when a prerequisite isn't met. A rule that gates on
`openssh-server` and lands on a host without it reports as
not-applicable instead of failing. Shorthand keys:

| Key | Behavior |
|---|---|
| `_stig_gate_packages` | All packages must be installed (uses `ansible_facts.packages`). |
| `_stig_gate_services` | All services must exist in `ansible_facts.services`. |
| `_stig_gate_services_running` | All services must exist **and** be in state `running`. |
| `_stig_gate_files` | All file paths must exist. |
| `_stig_gate_vars` | Dict: each var must satisfy its expectation (`non-empty`, `defined`, or `true`). |
| `_stig_gate` | Long-form: a dict with keys `packages`, `services`, `services_running`, `files`, `vars`. |

### Audit probes

Three mutually exclusive ways to decide "is the host compliant right now?":

1. **`_stig_use_check_mode_probe` (default `true`)** — run the wrapped
   apply module with `check_mode=True` and treat `changed=false` as
   compliant. The probe always forces check_mode regardless of the
   playbook's own setting, so audit mode can never mutate.
2. **`_stig_validate` + `_stig_validate_args`** — run a separate module
   (typically `ansible.builtin.shell` or a `command`) whose success means
   compliant.
3. **`_stig_validate_expr`** — a list of conditions evaluated in-process
   against `task_vars`. No module runs; the plugin just reads variables.
   Use this when you've already gathered facts in the prelude (e.g. ESXi
   `_adv_*` facts) so each rule is a pure comparison. Supported
   comparisons: `equals`, `equals_exact`, `equals_unordered`, `contains`,
   `contains_exact`, `startswith`, `endswith`, `matches` (regex),
   `not_empty`.

`_stig_check: "<shell>"` is a shorthand: rc=0 means compliant. Equivalent
to `_stig_validate: ansible.builtin.shell` plus
`_stig_validate_args: {cmd: "<shell>"}` plus `_stig_use_check_mode_probe: false`.

### Audit-only rules

Some controls can be detected but not remediated (Secure Boot state,
certificate validity, host profiles, hardware flags). Set
`_stig_audit_only: true` and the validator still runs in remediate phase
but the apply module never executes. Combine with `_stig_validate_expr`
for a pure read-only check.

### Remediation error policy

If the apply module fails during remediation:

| `_stig_remediation_errors` | Behavior |
|---|---|
| `warn` (default) | `failed=False`, emit a warning, continue the play. |
| `halt` | `failed=True`, stop the play. |
| `ignore` | `failed=False`, no warning. |

### Handler hints

`_stig_notify: [handler_a, handler_b]` surfaces handler names in the
structured result under `notify` when `changed=true`. The calling play
can react. The wrapper does not invoke handlers itself — it just carries
the hint upstream.

---

## Specifying the apply module

Two syntaxes, both supported:

**Nested (preferred)** — module FQCN as a key, its args as the nested dict:

```yaml
- name: "stigrule_270741"
  internal.core.stig:
    _stig_gate_packages: [openssh-server]
    _stig_notify: [ssh_restart]
    ansible.builtin.lineinfile:
      path: /etc/ssh/sshd_config
      regexp: '^\s*UsePAM\s+'
      line: "UsePAM yes"
```

**Flat (`_stig_apply`)** — module FQCN as a value, args alongside the
`_stig_*` keys:

```yaml
- name: "stigrule_270741"
  internal.core.stig:
    _stig_apply: ansible.builtin.lineinfile
    path: /etc/ssh/sshd_config
    regexp: '^\s*UsePAM\s+'
    line: "UsePAM yes"
    _stig_gate_packages: [openssh-server]
    _stig_notify: [ssh_restart]
```

Nested is preferred for readability — the task reads like a normal
`lineinfile` call with STIG metadata sprinkled on top.

---

## Lifecycle example

```yaml
# Prelude — runs once per host at the top of the pass
- name: "Ubuntu STIG | Begin"
  internal.core.stig:
    _stig_phase: begin
    _stig_manage_prefix: "stig_2404_"
    _stig_begin_gather:
      - package_facts
      - service_facts

# Rules — each task inherits phase + manage-prefix from begin
- name: "stigrule_270741"
  internal.core.stig:
    _stig_gate_packages: [openssh-server]
    ansible.builtin.lineinfile:
      path: /etc/ssh/sshd_config
      regexp: '^\s*UsePAM\s+'
      line: "UsePAM yes"

- name: "stigrule_270751"
  internal.core.stig:
    _stig_gate_vars:
      stig_2404_stigrule_270751_chrony_server: non-empty
    _stig_validate_expr:
      - var: chrony_conf_contents
        contains: "{{ stig_2404_stigrule_270751_chrony_server }}"
    ansible.builtin.lineinfile:
      path: /etc/chrony/chrony.conf
      regexp: '^\s*server\s+'
      line: "server {{ stig_2404_stigrule_270751_chrony_server }} iburst"

# End — clears _stig_active_phase
- name: "Ubuntu STIG | End"
  internal.core.stig:
    _stig_phase: end
```

---

## Key reference

All keys start with `_stig_`. Everything else in the task body is
forwarded to the wrapped apply module verbatim.

### Lifecycle

| Key | Type | Default | Purpose |
|---|---|---|---|
| `_stig_phase` | str (`begin`\|`audit`\|`remediate`\|`end`) | inherit → `audit` | Execution phase. |
| `_stig_begin_gather` | list[str] | `[]` | Fact modules to gather on `begin`. Shortnames expand (`package_facts` → `ansible.builtin.package_facts`). |
| `_stig_manage_prefix` | str | — | Variable name prefix for auto-resolving `_stig_manage`. Set once during `begin`. |
| `_stig_active_phase` | (host fact) | — | Set by `begin`, read by subsequent tasks. Not passed directly. |

### Apply module

| Key | Type | Default | Purpose |
|---|---|---|---|
| `_stig_apply` | str | — | FQCN of the module to wrap (flat form). |
| (nested key) | dict | — | Alternative to `_stig_apply`: put the module FQCN as a task key with its args as the nested dict. |

### Identity / control

| Key | Type | Default | Purpose |
|---|---|---|---|
| `_stig_id` | str | inferred from task name (`stigrule_<id>`) | Explicit rule ID override. |
| `_stig_manage` | bool | `true` (or resolved from `_stig_manage_prefix`) | When `false`, the rule is skipped with status `skipped`. |
| `_stig_result_key` | str | `stig` | Top-level result key. |
| `_stig_audit_only` | bool | `false` | Remediation never runs, even in remediate phase. |

### Gates

| Key | Type | Semantics |
|---|---|---|
| `_stig_gate_packages` | list[str] | Every package must be installed. |
| `_stig_gate_services` | list[str] | Every service must exist. |
| `_stig_gate_services_running` | list[str] | Every service must exist and be running. |
| `_stig_gate_files` | list[str] | Every path must exist. |
| `_stig_gate_vars` | dict[str, `non-empty`\|`defined`\|`true`] | Each var must satisfy its expectation. |
| `_stig_gate` | dict | Long form: `{packages, services, services_running, files, vars}`. |
| `_stig_gate_status` | `na` \| `not_reviewed` | What status to report on gate failure. Default `na`. |
| `_stig_na_reason` | str | Optional reason string surfaced in the result. |

### Compliance check

| Key | Type | Semantics |
|---|---|---|
| `_stig_use_check_mode_probe` | bool (default `true`) | Use the wrapped module in `check_mode=True` as the probe. |
| `_stig_validate` | str | Separate validator module FQCN. |
| `_stig_validate_args` | dict | Args for the validator module. |
| `_stig_validate_expr` | list[dict] | In-process conditions against `task_vars`. See comparisons below. |
| `_stig_check` | str | Shell-command shorthand: `rc=0` = compliant. Mutually exclusive with the above two. |
| `_stig_strict_verify` | bool (default `false`) | After remediation, re-probe in check_mode to confirm. |

`_stig_validate_expr` entry shape:

```yaml
- var: <fact_or_var_name>
  equals: "expected value"          # case-insensitive string
  # or: equals_exact, equals_unordered, contains, contains_exact,
  #     startswith, endswith, matches (regex), not_empty: true
```

Multiple conditions AND together. All must pass for the rule to be compliant.

### Remediation behavior

| Key | Type | Semantics |
|---|---|---|
| `_stig_remediation_errors` | `warn` \| `halt` \| `ignore` (default `warn`) | What to do if the apply module fails. |
| `_stig_notify` | list[str] | Handler names to surface in `notify` when `changed=true`. |

---

## Result shape

Every task returns an `ansible_facts`-style result with a `stig` key:

```yaml
stig:
  id: "270741"
  phase: audit
  status: pass            # pass | fail | error | na | not_reviewed | skipped
  reason: "compliant"
  host: "srv-01"
  gate: { ok: true, ... }
  probe: { ... }          # check-mode probe result (when used)
  remediation: { ... }    # apply-module result (remediate only)
  validator: { ... }      # _stig_validate or _stig_validate_expr result
  notify: [ssh_restart]
```

The callback plugin `internal.core.ncs_collector` keys off `stig.id`,
`stig.status`, and `stig.phase` when writing the `raw_stig_audit.yaml`
artifact that `ncs-reporter` later consumes.

---

## Conventions in this repo

- Task `name:` is exactly `stigrule_<id>` — numeric V-ID for DISA
  benchmarks, or the vendor-prefixed STIG-ID where appropriate
  (`stigrule_VCEM-70-000021`). The name is the callback plugin's join
  key; don't prefix it with platform hints.
- Defaults for per-rule tunables live in `default.yaml` next to the
  numbered task files, keyed `<manage_prefix>stigrule_<id>_<field>`.
  Site-specific inputs (syslog host, NTP, LDAP, banners) go in a
  `SITE-SPECIFIC` banner block at the top of the same file.
- Pre-gather heavy facts once in `00_prelude.yaml` (ESXi `_adv_*`,
  Ubuntu `package_facts`/`service_facts`, Windows `ansible_facts.services`)
  and let rule tasks use `_stig_validate_expr` against those facts
  instead of re-probing per rule.
- Prefer `_stig_validate_expr` over `ansible.builtin.shell` for audit —
  expressions are faster, don't require a round trip, and sidestep
  Jinja2 early-resolution problems.
- `_stig_audit_only: true` for things Ansible can't fix (Secure Boot,
  TPM attestation, hardware inventory). Don't silently swallow them;
  report `fail` / `pass` honestly so the CKLB renderer can surface the
  state.

## See also

- [STIG migration workflow](_dev/STIG_MIGRATION_WORKFLOW.md) — how to
  port a legacy STIG role to `internal.core.stig`.
- [STIG bug postmortem](_dev/STIG_BUGS_ENCOUNTERED.md) — catalog of
  real bugs encountered during the Ubuntu 24.04 and Photon OS 3
  migrations; useful as a checklist when authoring new rules.
- `prompts/stig_from_xccdf.md` — agent prompt for scaffolding a new
  `stig_<version>/` folder from an XCCDF benchmark.
