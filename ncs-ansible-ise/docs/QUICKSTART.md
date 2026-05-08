# Quickstart

## Install

```bash
python -m pip install ansible ciscoisesdk requests
ansible-galaxy collection install cisco.ise
```

For this NCS wrapper collection, build and install from this directory:

```bash
ansible-galaxy collection build --force
ansible-galaxy collection install internal-ise-*.tar.gz --force
```

## Enable ISE APIs

In Cisco ISE, enable the API Gateway, ERS APIs, and OpenAPIs. Cisco's
current API docs describe API Gateway access through port 443, with ERS
also available on port 9060.

Use an account mapped to the correct API privilege group:

- ERS Admin: read/write ERS API operations
- ERS Operator: read-only ERS API operations
- Super Admin: access to all API services, subject to local policy

## Inventory

```yaml
all:
  children:
    ise_servers:
      hosts:
        ise01.example.test:
          ansible_host: 10.0.4.10
          ise_hostname: "{{ ansible_host }}"
          ise_username: admin
          ise_password: "{{ vault_ise_admin_password }}"
          ise_verify: false
          ise_version: "3.5.0"
          ansible_connection: local
```

Store real passwords with Ansible Vault:

```bash
ansible-vault encrypt_string \
  '<ise-admin-password>' \
  --name vault_ise_admin_password
```

## Minimal Upstream Playbook

```yaml
---
- name: Get Cisco ISE network devices
  hosts: ise_servers
  gather_facts: false
  tasks:
    - name: Get network devices
      cisco.ise.network_device_info:
        ise_hostname: "{{ ise_hostname }}"
        ise_username: "{{ ise_username }}"
        ise_password: "{{ ise_password }}"
        ise_verify: "{{ ise_verify }}"
        ise_version: "{{ ise_version }}"
```

Run it:

```bash
ansible-playbook -i inventory/production network_device.yml
```

## NCS Collection Playbook

```bash
ansible-playbook -i inventory/production internal.ise.ise_collect
```

The NCS playbook emits `raw_ise.yaml` through `internal.core.emit`.
Set these inventory flags to control large or sensitive datasets:

```yaml
ise_collect_network_devices: true
ise_collect_endpoints: false
ise_collect_guests: false
ise_collect_trustsec: true
ise_collect_certificates: true
ise_collect_node_health: true
ise_collect_backup_repository: true
ise_collect_patches: true
ise_collect_policy: true
ise_collect_device_admin: true
ise_collect_identity_sources: true
ise_collect_sessions: true
ise_collect_active_session_list: false
ise_endpoint_repeat_counter_threshold: 3
```
