# VMware STIG Fact Schema

This document defines the canonical schema for ESXi and VM STIG facts within the `internal.vmware` collection.

## ESXi Host Schema (`esxi_ctx.stig_facts[]`)

| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | string | Hostname of the ESXi host. |
| `identity` | object | Host identity: `{ version, build }`. |
| `advanced_settings_map` | dict | Dict-based advanced settings (for fast lookup). |
| `config.option_value` | list | List-based advanced settings: `[{key, value}]` (Compatibility shim). |
| `services` | dict | Service states: `{ service_key: { running, policy, label } }`. |
| `ssh` | object | SSH configuration: `{ sshd_config, banner_content }`. |
| `discovery_meta` | object | Discovery metadata: `{ timestamp, source }`. |

## VM Schema (`vmware_ctx.stig_facts[]`)

| Key | Type | Description |
| :--- | :--- | :--- |
| `name` | string | VM Name. |
| `identity` | object | VM identity: `{ guest_id, tools_status, uuid }`. |
| `advanced_settings` | dict | Dict-based VMX extraConfig. |
| `hardware` | object | Hardware status: `{ floppies, cdroms, serial_ports, usb_present, disks: [{label, disk_mode}] }`. |
| `security` | object | Security flags: `{ encryption, vmotion_encryption, logging_enabled, ft_encryption }`. |
| `discovery_meta` | object | Discovery metadata: `{ timestamp, source }`. |
