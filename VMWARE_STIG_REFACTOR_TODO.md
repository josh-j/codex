# VMware STIG Refactor TODO

This document outlines the strategy for refactoring the `internal.vmware` collection to better utilize external VMware collections while maintaining robust internal audit and STIG logic.

## High-Level Goals
- **Standardize Data Sourcing:** Move away from mixed VMware collections (`vmware.vmware`, `community.vmware`, `vmware_rest`) and custom scripts where external modules provide equivalent functionality.
- **Isolate Collection from Logic:** Decouple "how we get the data" (collectors) from "how we evaluate the rule" (internal filters/templates).
- **Normalize Schema:** Ensure a stable, versioned data structure for `esxi_ctx` and `vsphere_ctx` so that audit templates are decoupled from collector implementation details.

## Phased Migration Plan

### Phase 0: Schema Stabilization & Normalization
- [x] **Fix ESXi Advanced Settings Schema:** Created `normalize.yaml` to convert dict to list structure.
- [x] **Introduce Compatibility Layer:** Added `identity`, `advanced_settings_map`, and `discovery_meta`.
- [x] **Establish STIG Fact Schema:** Documented in `collections/ansible_collections/internal/vmware/docs/SCHEMA.md`.

### Phase 1: ESXi Discovery Decomposition
- [x] **Refactor `tasks/stig/discovery.yaml`:** Decomposed into `base_api.yaml`, `identity.yaml`, `services.yaml`, `ssh_facts.yaml`, and `normalize.yaml`.
- [x] **Isolate Side Effects:** Added `vmware_stig_enable_ssh_collection` feature flag in `ssh_facts.yaml`.

### Phase 2: VM STIG Discovery Refactor
- [x] **Decompose `get_vm_stig_facts.py` Usage:** Split into logical sub-tasks in `vm/discovery.yaml` and `collectors/`.
    - `vm_inventory.yaml`: Identity, tools status.
    - `vm_security.yaml`: Encryption flags, logging.
    - `vm_extra_config.yaml`: VMX advanced settings.
    - `vm_devices.yaml`: Hardware (floppy, CD-ROM, serial, USB, disk modes).

### Phase 3: External Module Migration (The "Easy Wins")
- [x] **Pin Dependencies:** Added `requirements.yml`.
- [x] **Replace Identity/Service Discovery:**
    - Integrated `community.vmware.vmware_host_info` and `community.vmware.vmware_host_service_info`.
- [x] **Implement `module_defaults`:** Added to `internal.vmware.stig` main task entry point.

### Phase 4: Custom Script Reduction
- [ ] **Shrink `get_esxi_facts.ps1`:** Move all fields covered by external modules out of the script.
- [ ] **Shrink `get_vm_stig_facts.py`:** Focus the script strictly on deep hardware inspection.
- [x] **Replace Alarm Script:** Converted to custom module `vmware_triggered_alarms_info`.

## Technical Details

### Target ESXi Schema (Implemented)
```yaml
esxi_ctx:
  stig_facts:
    - name: "esxi01"
      identity: { version: "7.0.3", build: "xxxxx" }
      services: { TSM-SSH: { running: false, policy: "off" } }
      advanced_settings_map: { "Syslog.global.logHost": "tcp://..." }
      config: # Compatibility shim
        option_value: [{ key: "Syslog.global.logHost", value: "tcp://..." }]
      ssh: { sshd_config: "...", banner: "..." }
      discovery_meta: { timestamp: "...", source: "..." }
```

### Target VM Schema (Implemented)
```yaml
vsphere_ctx:
  stig_facts:
    - name: "app01"
      identity: { guest_id: "ubuntu64Guest", tools_status: "toolsOk" }
      advanced_settings: { "isolation.tools.copy.disable": "TRUE" }
      hardware: { usb_present: false, disks: [...] }
      security: { vmotion_encryption: "opportunistic" }
      discovery_meta: { timestamp: "...", source: "..." }
```
