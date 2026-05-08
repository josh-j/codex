# Reference Links

Primary references for Cisco ISE Ansible work. Prefer these over blog
posts or generated examples.

## Cisco ISE Ansible Collection

- Upstream source: https://github.com/CiscoISE/ansible-ise
- Cisco Code Exchange entry: https://developer.cisco.com/codeexchange/github/repo/CiscoISE/ansible-ise/
- Ansible Galaxy page: https://galaxy.ansible.com/ui/repo/published/cisco/ise/
- Cisco-hosted generated collection docs: https://ciscoise.github.io/ansible-ise/main/plugins/index.html
- Ansible 11 collection docs, `cisco.ise` 2.10.0: https://docs.ansible.com/projects/ansible/11/collections/cisco/ise/index.html
- Ansible latest collection status: https://docs.ansible.com/projects/ansible/latest/collections/cisco/ise/index.html

## Cisco ISE API And SDK

- Cisco ISE API documentation: https://developer.cisco.com/docs/identity-services-engine/latest/
- Cisco ISE Ansible getting started: https://developer.cisco.com/docs/identity-services-engine/latest/ansible-getting-started/
- Cisco ISE API setup: https://developer.cisco.com/docs/identity-services-engine/latest/setting-up/
- Cisco ISE Change of Authorization REST APIs: https://developer.cisco.com/docs/identity-services-engine/latest/using-change-of-authorization-rest-apis/
- Cisco ISE ANC Endpoint API: https://developer.cisco.com/docs/identity-services-engine/3.0/anc-endpoint/
- Cisco ISE API resource version matrix: https://developer.cisco.com/docs/identity-services-engine/latest/api-versioning
- Cisco ISE API deprecation/versioning policy: https://developer.cisco.com/docs/identity-services-engine/latest/versioning/
- Cisco ISE API changelog: https://developer.cisco.com/docs/identity-services-engine/latest/changelog/
- Cisco ISE programmability landing page: https://developer.cisco.com/identity-services-engine/
- Python SDK package: https://pypi.org/project/ciscoisesdk/

## Ansible Core References

- Using collections: https://docs.ansible.com/ansible/latest/collections_guide/index.html
- Installing collections: https://docs.ansible.com/ansible/latest/collections_guide/collections_installing.html
- Ansible Vault: https://docs.ansible.com/ansible/latest/vault_guide/index.html
- Module index: https://docs.ansible.com/ansible/latest/collections/index_module.html

## Version Notes

Cisco's upstream README lists the tested compatibility matrix:

| Cisco ISE version | `cisco.ise` version | `ciscoisesdk` version |
|---|---:|---:|
| 3.1.0 | 2.0.0 | 1.2.0 |
| 3.1 Patch 1 | 2.5.16 | 2.0.10 |
| 3.2 beta | 2.8.0 | 2.1.1 |
| 3.3 Patch 1 | 2.10.0 | 2.2.3 |
| 3.5.0 | 3.0.1 | 2.4.0 |

The upstream README also notes that `ise_version` should match the
Cisco ISE release being automated, and that newer SDK versions may be
usable when they preserve the underlying API support.

A live `ansible-galaxy collection install cisco.ise` on 2026-05-07
resolved `cisco.ise` 3.1.0. The local `internal.ise` role therefore
uses module names verified against that Galaxy package for its starter
collect path.

## Requirements Summary

- Ansible collection: `cisco.ise`
- Python SDK: `ciscoisesdk`
- Python HTTP library: `requests`
- ISE API services enabled: API Gateway, ERS APIs, and OpenAPIs
- ISE API account privileges: ERS Admin for writes, ERS Operator for
  read-only operations, or Super Admin where local policy permits it
