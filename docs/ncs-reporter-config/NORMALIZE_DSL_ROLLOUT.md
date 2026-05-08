# Normalize DSL Rollout Plan

Plan for finishing the migration of platform `ncs_configs/` away from
ad-hoc `script:` / `template:` producers and `compute:` pipelines that
re-shape raw collector payloads, and onto the declarative `normalize:` DSL
introduced in the VMware refactor.

## Why

`normalize:` is the preferred way to keep collector-shape coupling **inside
the schema config**, without dragging that logic into Python helpers, large
Jinja blocks, **or `collect.yaml` / Ansible playbooks**. The VMware
`vcsa.yaml`/`vm.yaml` rewrite proved the DSL covers the bulk of what the
existing producers do (path lookups, list shaping, parent/child expansion,
scalar fallbacks, counts), and it surfaces the shape clearly to anyone
reading the config.

### Core principle: normalization lives in schema configs

This rollout is about more than retiring `script:` and `template:` fields
in `ncs_configs/*.yaml`. The same principle applies upstream: **any
shaping of raw collector output belongs in the schema, not in the
playbook that emitted it.**

That means `roles/<sub_platform>/tasks/collect.yaml` (and any task file it
includes) should:

- Run the module / API call.
- Capture the raw response under a single registered variable.
- Drop that raw response into the role's emitted payload (`*_raw_*`
  bundle) verbatim.

It should *not*:

- Build derived dicts via `set_fact` + chained `selectattr` / `items2dict`
  / `map(attribute=…)` pipelines.
- Pre-flatten REST-batch `.results[*].json` arrays into name-keyed dicts.
- Compute counts, ratios, status rollups, or any field a widget or alert
  would later read directly.
- Apply per-host filtering for "interesting subset" lists.

The reporter's `normalize:` DSL is now expressive enough to do all of the
above declaratively. Pulling shaping out of the playbooks gives us:

- A single place to change when a collector field is renamed.
- Diff-able, lint-able config rather than embedded Jinja.
- Faster collect runs (no extra `set_fact` round-trips per host).
- Clean raw bundles in the telemetry lake — anyone re-running the
  reporter against archived `raw_*.yaml` gets identical output.

Where this is in flight today:

- DSL implementation: `ncs-reporter/src/ncs_reporter/normalization/_normalize_dsl.py`
- Schema integration: `ncs-reporter/src/ncs_reporter/normalization/schema_driven.py`
- Reference doc: `docs/ncs-reporter-config/FIELDS.md` (section "`normalize`")
- Already migrated: `ncs-ansible-vmware/ncs_configs/vcsa.yaml`,
  `ncs-ansible-vmware/ncs_configs/vm.yaml` (raw bundles)
- Removed scripts: `assemble_esxi_hosts.py`, `count_vm_compliance.py`,
  `get_vms_list.py`, `normalize_snapshots.py`

## Inventory of remaining work

Survey of all `ncs_configs/` files in the umbrella as of `main`:

| Config | `script:` | `template:` | `compute:`/`list_*` | Notes |
| --- | --- | --- | --- | --- |
| `ncs-ansible-linux/ncs_configs/linux_base_fields.yaml` | 1 (`users`) | 0 | 22 | `script: user_inventory.py`, only `list_filter`/`list_map` site (`disks`), and several non-trivial `compute:` chains |
| `ncs-ansible-vmware/ncs_configs/vm.yaml` | 0 | 0 | 12 | Already partially migrated; remaining filters on `virtual_machines` |
| `ncs-ansible-aci/ncs_configs/aci.yaml` | 0 | 0 | 11 | All `selectattr`/`map(attribute=…)` chains over fault and OSPF lists |
| `ncs-ansible-vmware/ncs_configs/vsphere.yaml` | 0 | 0 | 3 | `metadata.counts` fallbacks |
| `ncs-ansible-vmware/ncs_configs/cluster.yaml` | 0 | 0 | 2 | VM counts |
| `ncs-ansible-vmware/ncs_configs/datacenter.yaml` | 0 | 0 | 2 | `clusters.values() | list` + count |
| `ncs-ansible-vmware/ncs_configs/esxi.yaml` | 0 | 0 | 1 | `uptime_days` |
| `ncs-ansible-windows/ncs_configs/windows.yaml` | 0 | 0 | 0 | Nothing to migrate |
| `ncs-ansible-linux/ncs_configs/photon.yaml` | 0 | 0 | 0 | Nothing to migrate |
| `ncs-ansible-linux/ncs_configs/ubuntu.yaml` | 0 | 0 | 0 | Nothing to migrate |
| `ncs-ansible/ncs_configs/config.yaml`, `inventory_root.yaml` | 0 | 0 | 0 | Out of scope (orchestrator schema) |

External helper scripts still present:

- `ncs-ansible-linux/ncs_configs/scripts/user_inventory.py` — referenced by
  the only remaining `script:` field.

### In-Ansible normalization to relocate

These collect tasks shape data on the playbook side instead of leaving the
raw response intact. Each one needs to move into the matching schema
config under `normalize:`.

| Role / file | LoC | `set_fact` | What it shapes (move to schema) |
| --- | --- | --- | --- |
| `ncs-ansible-vmware/roles/vcsa/tasks/collect.yaml` | 379 | 4 | `_vcenter_datacenters` (pluck names), `_vcsa_rest` (results→items2dict by `item`/`json`), `_all_vcsa_vms` (tagged-vs-untagged fallback), final `vmware_raw_vcenter` map of `default({})` casts |
| `ncs-ansible-vmware/roles/esxi/tasks/collect.yaml` | 231 | 4 | `_vcenter_datacenters`, `_all_esxi_hosts` (cluster-results → flatten → host names), `_raw_host_records` (multi-level `nics_by`/`svcs_by` Jinja join) |
| `ncs-ansible-aci/roles/apic/tasks/collect.yaml` | 120 | 5 | `_aci_by_name` (results zip into dict), `_aci_description_map` (`items2dict` on `l1PhysIf.attributes`), final `_aci_raw_payload` aggregate |
| `ncs-ansible-linux/roles/ubuntu/tasks/collect.yaml` | 206 | 1 | `ubuntu_raw_discovery`: ~100-line `default()`/`float`/`int` casting block — pure auto-importable shape |
| `ncs-ansible-windows/roles/server/tasks/collect.yaml` | 119 | 2 | `_win_raw_payload` `default(...)` casts and nested `default({}).field` lookups |

Anything not in this table should still be inspected during migration —
roles that pre-filter or pre-count for Ansible-side branching often hide
similar shaping in non-`set_fact` tasks (e.g. `vars:` blocks on emit
tasks).

## What `normalize:` already covers

From `_normalize_dsl.py` the DSL ops available today are:

- `const`, `path`/`from`, `flatten`, `first_of` (with `default`), `object`,
  `list` (with `source`, `for_each`/`expand`, `include_source`,
  `exclude_match_any`, `map`)
- `count`, `pluck`, `truthy`, `lookup`, `regex_search`, `age_days`
- `find` (where), `get`, `index`
- Inline `expr`/`compute` and `template` escape hatches inside any DSL
  position

These are enough to express almost every remaining `compute:` chain in the
inventory above, with two known gaps (next section).

## Known DSL gaps to close before/while migrating

1. **Generic list filtering by attribute equality.** `_eval_list` only has
   `exclude_match_any` (regex against one field). Most remaining
   `compute:` chains are `virtual_machines | selectattr('power_state',
   'eq', 'poweredOn') | list` style. Add an `include_where` /
   `exclude_where` clause on `list` (dict of `field: value` or
   `field: {op: eq|ne|gt|...}`) so we don't have to embed an `expr:` per
   field. Without this we'd need to inline Jinja for ~20 fields, which
   defeats the point.
2. **Dictionary iteration as input.** `linux_base_fields.yaml` builds
   users/groups from `getent_passwd`/`getent_group` (dict of name →
   tuple). Today `list.for_each` works on lists; teach it to accept a
   dict and expose `item.key`/`item.value` the same way `expand` already
   does. (`_eval_list` already does this for the `expand` branch — extend
   to top-level dict sources.)
3. **Arithmetic on list elements.** `user_inventory.py` computes
   `password_age_days = epoch_days - shadow_last_change`. Achievable via
   `expr:` inside `map:`, but if we're moving away from large Jinja, a
   small `subtract` / `divide` op is worth considering. Lower priority —
   `expr:` inside a single mapped field is acceptable.

These should be added to `_normalize_dsl.py` with focused tests in
`ncs-reporter/tests/test_schema_driven.py::TestNormalizeFields` before
each migration that depends on them.

## Migration rules of thumb

For each config field, choose in this order:

1. **Auto-imported flat field** → leave alone. Don't declare a field just
   to forward a value the collector already emits.
2. **Single path lookup with a fallback** → `normalize: {first_of: [...]}`.
3. **List shaping (filter/map/flatten/expand)** → `normalize: {list: ...}`.
4. **Single scalar derived from one or two fields** → keep `compute:` if
   it's a one-liner; this is what `compute:` is for.
5. **Multi-statement Jinja or anything that loops to build a structure**
   → `normalize:` (after closing the relevant DSL gap if needed).
6. **External Python helper** → `normalize:` only. We do not want new
   `script:` fields, and we want to retire the existing one.

`template:` and `script:` stay as escape hatches for cases the DSL
genuinely cannot express, but every new use should justify itself in
review. Update `FIELDS.md` if a new escape-hatch case is found that we
expect to recur.

### Playbook-side rules

In `roles/<sub_platform>/tasks/collect.yaml` (and includes):

1. **One `set_fact` per emitted bundle, at the end of `always:`.** Its
   body is a flat map of `key: "{{ _registered_var | default(<empty>) }}"`
   entries. No filters, no `selectattr`, no `items2dict`, no Jinja that
   loops.
2. **Move every other `set_fact` into a schema field.** If a transform
   currently exists only to make a downstream Ansible task easier (gating
   on a count, branching on a status), see if that downstream branch can
   key off the raw shape instead — most of them can.
3. **No new helper modules / filter plugins for shaping.** Collector-shape
   coupling lives in `ncs_configs/`, not in `plugins/`.
4. **If a transform is genuinely needed for the collect run itself**
   (e.g. building an inventory list passed to a *later* module call in
   the same play), keep it as a private `_underscored` fact and do not
   include it in the emitted bundle. The schema then re-derives the
   public field from raw inputs.

## Per-collection task list

### 1. `ncs-reporter` — close DSL gaps

- [ ] Add `include_where` / `exclude_where` to `list` op (attribute
      equality + a small set of comparison operators). Tests in
      `tests/test_schema_driven.py::TestNormalizeFields`.
- [ ] Allow `list.for_each` to accept a dict source and surface
      `item.key` / `item.value` (mirror existing `expand` dict handling).
      Tests as above.
- [ ] (Optional) Add `subtract` / `divide` scalar ops if migration of
      `users`/`recent_journal_events` would otherwise need inline Jinja.
- [ ] Regenerate `ncs-reporter/schemas/ncs_reporter_config_schema.json`
      (`uv run python generate_schema.py`).
- [ ] `uv run pytest` — full reporter suite must pass.

### 2. `ncs-ansible-aci/ncs_configs/aci.yaml`

Lowest risk; entirely list filtering and counts.

- [ ] Migrate `active_faults`, `critical_faults`, `major_faults`,
      `warning_faults`, and the OSPF/ingress/egress fields to
      `normalize: {list: {source: ..., include_where: {...}}}` once the
      filter op is in.
- [ ] Replace `*_count` computes with `normalize: {count: <field>}`.
- [ ] Verify against existing ACI fixtures (whatever tests in
      `ncs-reporter/tests` cover ACI today; if none, add one round-trip
      test similar to `TestVcsaSchema`).

### 3. `ncs-ansible-vmware/ncs_configs/vm.yaml`

Already partially done; finish the filter chains.

- [ ] Migrate `powered_off_vms`, `powered_on_vms`,
      `vms_tools_not_running`, `vms_tools_not_installed`,
      `aged_snapshots`, `vms_never_backup`, `vms_no_backup_tags`,
      `vms_overdue_backup`, `vms_no_owner_email`,
      `vms_missing_owner_desc` to `list` with `include_where`.
- [ ] Replace the matching `*_count` computes with `normalize: count`.
- [ ] Re-run `pytest tests/test_schema_driven.py::TestVmHealthSchema`.

### 4. `ncs-ansible-vmware/ncs_configs/{vsphere,cluster,datacenter,esxi}.yaml`

Tiny surface — one-pass cleanup.

- [ ] `vsphere.yaml`: rewrite the `metadata.counts.*` fallbacks as
      `normalize: {first_of: [...]}` returning ints.
- [ ] `cluster.yaml`: `vm_count` and `powered_on_vm_count` become
      `normalize: {count: ...}` / `list` + `count`.
- [ ] `datacenter.yaml`: `clusters_list` becomes
      `normalize: {pluck: {source: clusters, path: item}}` (or
      equivalent values-as-list helper if we add one); `clusters_list_count`
      becomes `normalize: {count: clusters_list}`.
- [ ] `esxi.yaml`: leave `uptime_days` as `compute:` — it is exactly the
      one-liner case that `compute:` is for.

### 5. `ncs-ansible-linux/ncs_configs/linux_base_fields.yaml`

Highest-impact and the only remaining `script:` field.

- [ ] Rewrite `disks` to `normalize: {list: ...}` with
      `exclude_where`/`exclude_match_any` against `fstype` and `device`.
      Drop the `list_filter`/`list_map` keys once empty.
- [ ] Rewrite `users` from `script: user_inventory.py` to a
      `normalize: {list: {for_each: getent_passwd, ...}}` pipeline that
      indexes `shadow_lines` and computes `password_age_days`. This
      depends on the dict-iteration DSL gap, and likely the
      `subtract`/`divide` op (or an inline `expr:` for the date math).
- [ ] Rewrite `non_standard_users` and `non_standard_groups` as
      `normalize: {list: {source: users / getent_group, exclude_where: {...}}}`
      using regex predicates (re-use `exclude_match_any` for the UID/GID
      regex tests).
- [ ] Rewrite `recent_journal_events`/`critical_journal_event_count`
      using `normalize` (slice + `from_json` map). May need a `slice`
      helper or stay as `compute:` if a slice op is out of scope.
- [ ] Once `users` is migrated, delete
      `ncs-ansible-linux/ncs_configs/scripts/user_inventory.py` plus its
      mirror under
      `ncs-ansible/collections/ansible_collections/internal/linux/ncs_configs/scripts/`.
- [ ] Re-run `pytest` for any Linux schema tests; add a fixture-driven
      `TestUbuntuSchema`/`TestPhotonSchema` round-trip test if not
      already present.

### 6. Playbook-side moves (paired with each schema migration)

> **Status — substantially complete.** Five collections + the
> collection template now ship with raw-emit playbooks and DSL-driven
> schemas. The remaining items are documented in the "Still deferred"
> note at the end of this section.
>
> Done so far (schema reads raw via `index:` / `first_of:` fallback,
> playbook stops emitting the pre-shaped fields):
>
> - **ACI** (`ncs-ansible-aci/roles/apic/tasks/collect.yaml`): dropped
>   the `_aci_by_name` `items2dict` from the bundle; emit raw
>   `aci_responses_raw` instead. Schema's `_aci_by_name` index field
>   re-derives. `_aci_description_map` stays as a private transient
>   used by the in-play utilization-enrichment helper. `TestAciSchema`
>   covers both pre-shaped and raw bundle shapes.
> - **VMware vcsa** (`ncs-ansible-vmware/roles/vcsa/tasks/collect.yaml`):
>   dropped `_vcsa_rest` `items2dict` from the bundle; emit raw
>   `appliance_rest_results`. Schema's `_appliance_rest` index field
>   re-derives, and existing `appliance_health_*` fields are
>   re-pointed at `_appliance_rest.health/...`.
> - **Ubuntu** (`ncs-ansible-linux/roles/ubuntu/tasks/collect.yaml`):
>   removed the redundant `| float`/`| int` casts from
>   `ubuntu_raw_discovery`; type coercion lives in the schema.
> - Collection template (`ncs-ansible-collection-template/.../collect.yaml`)
>   updated with explicit guidance and a comment block linking to this
>   doc.
> - Repo-wide guardrail
>   `ncs-reporter/tests/test_normalize_dsl_guardrails.py::test_no_shaping_set_facts_in_collect_tasks`
>   fails CI if a new public `set_fact` body uses `selectattr`,
>   `items2dict`, `map(attribute=…)`, `dict2items`, `rejectattr`, or
>   `| zip`. Underscored private transients are exempt.
>
> - **Windows** (`ncs-ansible-windows/roles/server/tasks/collect.yaml`):
>   declared every field explicitly in `windows.yaml` with
>   `type:` + `first_of:` chains that read either the legacy flat key
>   or the raw register subtree (`_health_os_info`,
>   `_health_memory_cpu`, `_health_reboot_pending`,
>   `_health_event_logs`, `_health_secure_channel`, `_vuln_results`,
>   `_ccm_service`). Playbook now emits raw register subtrees instead
>   of `default(...)`-cast leaves. Two new tests in `TestWindowsSchema`
>   cover both shapes.
> - **VMware vcsa `_all_vcsa_vms`** tagged-vs-untagged fallback:
>   schema's `virtual_machines.source` first_of chain now picks
>   `vms_raw` → `vms_tagged_raw.virtual_machines` →
>   `vms_untagged_raw.virtual_machines` directly; playbook emits both
>   raw register payloads and dropped the `_all_vcsa_vms` set_fact.
> - **VMware util enrichment** (`_enrich_util.yaml` retired):
>   `ingress_high_util` / `egress_high_util` are now derived in the
>   schema via the new DSL `sort:` / `unique:` / `slice:` ops chained
>   with `list:include_where`/`exclude_where` and `pluck:`. Playbook
>   no longer pre-builds these; helper file deleted. New
>   `TestAciSchema::test_aci_schema_derives_util_enrichment_from_raw_imdata`
>   covers the pipeline.
> - **vSphere "is defined" fallbacks** (`vsphere.yaml`): the three
>   tree-vs-standalone count fields use the new DSL
>   `if: {defined: ...}` op, distinguishing "missing field" from
>   "empty list" (which `first_of` alone cannot do).
> - **DSL primitives added**: `sort:` (with `by:` and `reverse:`),
>   `unique:` (`by:`), `merge:` (precedence-ordered dict combine),
>   top-level `defined:` op, `if:`/`then:`/`else:` op, plus a
>   `defined:` predicate inside `include_where`/`exclude_where`.
>
> **By-design exceptions** (not migrable to the DSL):
>
> - **VMware esxi `_raw_host_records` per-host NIC/service join.** The
>   join runs *before* the emit step's `per_host_split`, which expects
>   a joined list keyed by `item: <hostname>` so it can split one
>   parent bundle into per-host raw files. That contract is enforced
>   by `internal.core.emit`, not by the schema — the schema only sees
>   one already-split host bundle, so it cannot produce the list the
>   splitter consumes. The fold stays in the playbook as a bundle-
>   shape primitive owned by the collector framework. Because it
>   produces the *splitter input*, it isn't classed as the kind of
>   "schema shaping" the rollout retires; it's annotated in the
>   playbook as such and the guardrail's underscore-prefix exemption
>   covers it.

Each collection's playbook cleanup ships in the same PR as its schema
migration so the raw bundle and the schema stay in lockstep.

#### `ncs-ansible-vmware/roles/vcsa/tasks/collect.yaml`

- [ ] Drop the `_vcenter_datacenters` `set_fact`; emit
      `datacenters_raw` verbatim. `vcsa.yaml` already has a `pluck`-able
      list spec for datacenter names.
- [ ] Replace the `_vcsa_rest` `items2dict` shaping with a raw emit of
      `_raw_vcsa_rest_facts.results`; add a schema field that runs
      `index: {source: ..., key: item, value: json}` (the new
      dict-`for_each` gap covers this).
- [ ] Replace the tagged-vs-untagged `_all_vcsa_vms` fallback with a
      `first_of` chain in `vcsa.yaml` over `vms_tagged_raw` →
      `vms_untagged_raw`.
- [ ] Reduce the final `vmware_raw_vcenter` block to a flat
      `key: _raw_var` map (no `default({})` chains — the schema's
      `first_of` handles missing keys).

#### `ncs-ansible-vmware/roles/esxi/tasks/collect.yaml`

- [ ] Drop `_vcenter_datacenters` and `_all_esxi_hosts`; emit raw
      cluster results. `vcsa.yaml`'s existing `esxi_hosts` `for_each` /
      `expand` spec already does this work.
- [ ] Move the `_raw_host_records` `nics_by`/`svcs_by` Jinja into
      `esxi.yaml` as a `list` with `for_each: hosts` and a `map:` that
      joins NIC and service maps via `index` / `get`. The dict-source
      `for_each` and a possible `merge`/`get` op may need to land first.
- [ ] Emit raw NIC/service results untouched alongside the host list.

#### `ncs-ansible-aci/roles/apic/tasks/collect.yaml`

- [ ] Drop `_aci_by_name` and `_aci_description_map`; emit
      `_aci_responses.results` verbatim under `aci_responses_raw`.
- [ ] In `aci.yaml`, derive `aci_by_name` via `index: {source:
      aci_responses_raw, key: item.name, value: json}` and
      `aci_description_map` via a nested `index` over the
      `l1PhysIf.attributes` flatten.
- [ ] Trim the final `_aci_raw_payload` to the registered raw vars; let
      schema fields produce the derived ones.

#### `ncs-ansible-linux/roles/ubuntu/tasks/collect.yaml`

- [ ] Replace the ~100-line `ubuntu_raw_discovery` `set_fact` with a
      thin emit that drops `ansible_facts` (or selected subtrees) into
      the raw bundle. Every `default(0) | float` / `default('')` cast
      becomes a schema `first_of` with a `const` fallback and a `type:`.
- [ ] Audit the resulting bundle size — if `ansible_facts` is too
      heavy, prune at the `gather_subset` level rather than rebuilding
      a hand-curated dict in Jinja.

#### `ncs-ansible-windows/roles/server/tasks/collect.yaml`

- [ ] Replace `_win_raw_payload`'s `default(...)` casts with a flat raw
      emit; move the casts and `default({}).field` lookups to
      `windows.yaml` as `first_of` / `path` fields.

#### Other roles to spot-check

- [ ] `ncs-ansible-vmware/roles/vm/tasks/collect.yaml` (currently no
      `set_fact`, but verify the emit task doesn't shape via `vars:`).
- [ ] `ncs-ansible-linux/roles/photon/tasks/collect.yaml` (empty by the
      same survey — sanity-check before declaring done).
- [ ] `ncs-ansible-collection-template/roles/example/tasks/collect.yaml`
      — update the template to model the new "raw emit only" pattern so
      future collections start in the right shape.

### 7. Documentation + guardrails

- [ ] Update `docs/ncs-reporter-config/FIELDS.md` with any new DSL ops
      (`include_where`/`exclude_where`, dict `for_each`, slice/arith if
      added) once they land. Keep the "Migration rules of thumb"
      decision list above in sync.
- [ ] Add a short note to each collection's `README` (where present)
      pointing at this rollout doc, so future config additions default
      to `normalize:`.
- [ ] After all per-collection items are checked off, consider a
      conftest/lint check: fail if a config introduces a new `script:`
      or `template:` field without an accompanying justification comment.
- [ ] Add an ansible-lint / repo-lint rule (or a small pytest under
      `ncs-reporter/tests/`) that flags `set_fact` blocks in
      `roles/*/tasks/collect.yaml` whose body contains `selectattr`,
      `items2dict`, `map(attribute=`, or `| zip ` — the most common
      "shaping in the playbook" smells.
- [ ] Update `docs/collections/COLLECTION_LAYOUT.md` to reference this
      doc and codify the "collect emits raw, schema normalizes" rule
      for new collections.

## Acceptance criteria

- No `script:` fields in any `ncs-ansible-*/ncs_configs/*.yaml` (helper
  scripts under `ncs_configs/scripts/` may still exist if needed by
  Ansible playbooks, but not as reporter config producers).
- No `template:` fields outside of cases explicitly justified in review.
- `compute:` fields are one-liner scalar derivations; multi-step list
  reshaping lives in `normalize:`.
- Each `roles/<sub_platform>/tasks/collect.yaml` ends with **one**
  `set_fact` whose body is a flat `key: "{{ _registered_var }}"` map.
  No transforming `set_fact`s remain in collect tasks.
- Re-running the reporter against archived `raw_*.yaml` from before the
  migration produces byte-identical rendered output (the schema absorbs
  whatever shaping the playbook used to do).
- All collection-level schema tests in `ncs-reporter/tests/` pass.
- `uv run python generate_schema.py` produces a clean diff after each
  DSL extension.

## Sequencing

The order above is deliberate: close the DSL gaps first so the
collection-level migrations don't have to invent inline Jinja, then go
smallest-blast-radius first (ACI → VMware leftovers → Linux). For each
collection, schema and playbook changes land in the **same** PR — the
schema must be ready to absorb the shaping before the playbook stops
doing it, otherwise rendered output regresses. Each collection's changes
ship behind its own commit so a regression is easy to bisect.

## Per-PR migration recipe

For each collection, run this checklist in order. The recipe assumes the
DSL gaps from section 1 are already closed.

1. **Snapshot a baseline.** Before touching anything, run a full collect
   against representative inventory and copy `raw_*.yaml` plus the
   rendered HTML aside (`/tmp/ncs-baseline-<collection>/`). This is the
   diff target.
2. **Move schema first.** Rewrite the collection's `ncs_configs/*.yaml`
   to read directly from the *raw* registered fields (the ones the
   playbook will soon emit untouched). Run
   `uv run pytest tests/test_schema_driven.py -k <Collection>` until
   green against the baseline raw bundles.
3. **Strip the playbook.** Remove transforming `set_fact`s from
   `roles/<sub_platform>/tasks/collect.yaml`. Reduce the final emit to
   one flat `set_fact` over registered variables.
4. **Re-collect and diff.** Rerun the collect, compare the new
   `raw_*.yaml` to the baseline (`diff -ru`), and confirm the rendered
   HTML diffs to zero meaningful change. Cosmetic key-order differences
   are acceptable; field values must match.
5. **Bump and vendor.** Update the collection's `galaxy.yml`, rebuild
   the vendored tarball under `ncs-ansible/collections/vendor/`, and
   refresh `ncs-ansible/requirements.yml`.
6. **Run lint + full reporter suite.** `cd ncs-ansible && just lint
   ansible-lint lint-configs check && cd ../ncs-reporter && just
   test-all`.
7. **One commit per logical step.** A reviewer should be able to bisect
   "schema absorbed shaping X" vs "playbook stopped emitting derived Y".

## Risks and mitigations

- **Schema field name collisions during the cutover.** If a schema
  field reads `foo` and the playbook still emits a derived `foo`, the
  schema sees the derived value and the migration looks like a no-op.
  Mitigation: rename the playbook's transitional fact to `_foo_derived`
  before the schema PR lands so the schema can never accidentally read
  it.
- **Reporter behavior for archived raw bundles.** Bundles emitted
  before this rollout assume the playbook did the shaping. The schema
  must keep `first_of` chains that fall back to those legacy keys until
  every archived bundle in the lake has rolled forward. Mitigation:
  for at least one release after a collection migrates, keep the
  fallbacks; remove them in a follow-up cleanup PR (good candidate for
  a scheduled agent).
- **Ansible-side branching that depends on derived facts.** A few
  tasks gate on counts/booleans that we plan to compute in the schema
  instead. Mitigation: leave the *underscored, non-emitted* fact in
  place inside the role for that purpose, but exclude it from the
  emitted bundle. The schema re-derives the public field from raw
  inputs.
- **Collect time regressions.** Removing `set_fact` round-trips should
  speed collects up, but unbundling a previously-shaped payload may
  inflate the raw `*.yaml` size. Mitigation: prune at the
  `gather_subset` / API field level if a raw bundle grows by more than
  ~25%, rather than re-introducing playbook-side filtering.
- **Test gap.** Some collections have no schema round-trip test today
  (ACI, Windows, Linux). Mitigation: section 7 makes adding one a
  prerequisite of declaring the collection done.

## Out of scope

The following are intentionally not part of this rollout:

- Changing the collector callback (`ncs_collector`) or telemetry-lake
  layout.
- Reworking how alerts/widgets consume fields — they already read
  schema-produced fields, so they're agnostic to whether the shaping
  happened in Ansible or in the schema.
- Cross-platform schema changes in `ncs-ansible/ncs_configs/`. The
  orchestrator config is structural (lists collections, points at
  inventory) and has no shaping logic to migrate.
- The PowerShell/WPF console (`ncs-console/`).

## Tracking

Maintain a single tracking issue or board column referencing this doc.
Each per-collection PR should link back here and tick the matching
checklist items inline. Once every box in sections 1–7 is checked, this
doc can be archived under `docs/_dev/` as historical context — the
"raw emit + schema normalize" rule should by then live in
`docs/collections/COLLECTION_LAYOUT.md` as the steady-state contract.
