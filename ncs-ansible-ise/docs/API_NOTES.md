# Cisco ISE API Notes For Ansible

## API Services

Cisco ISE exposes several API surfaces used by Ansible automation:

- ERS APIs for CRUD operations on ISE resources.
- Open APIs for newer API service resources.
- Monitoring APIs for session and operational visibility.
- pxGrid APIs for context exchange and session/security group data.

Cisco documents API Gateway as the entry point for API service traffic
in standalone and distributed deployments. In distributed deployments,
read requests can be served by a PSN or primary PAN, while write
requests go to the primary PAN.

## Ports

Current Cisco docs identify these API paths:

- API Gateway/API service: HTTPS 443
- ERS APIs: HTTPS 443 through API Gateway, or 9060 for ERS
- Open APIs behind API Gateway: service port 9070 internally
- Monitoring APIs behind API Gateway: service port 9443 internally

Firewall policy should follow the Cisco deployment guide for the exact
node roles in use.

## API Account Privileges

Map the automation account to the least privilege needed:

- ERS Operator for read-only collection.
- ERS Admin for create, update, and delete operations.
- Super Admin only when a workflow explicitly needs broad access and
  local policy approves it.

## Versioning

Always align these three values:

- Cisco ISE product version
- `ise_version` Ansible variable
- Installed `cisco.ise` and `ciscoisesdk` versions

Cisco publishes an API resource version matrix showing the first ISE
release where each API resource appeared. If a module fails with a 404
or "resource not found" against an older ISE release, check that matrix
before treating the failure as an Ansible bug.

Cisco's API deprecation policy says deprecated operations are marked in
the OpenAPI description when possible, supported through the current
release and one subsequent release, and removed in the following
release unless Cisco sunsets earlier.

## Collection Status

The Ansible 12 community docs state that `cisco.ise` was removed from
the bundled Ansible package documentation. Install it explicitly:

```bash
ansible-galaxy collection install cisco.ise
```

This local `internal.ise` collection declares `cisco.ise` as a Galaxy
dependency so fresh installs resolve the upstream modules explicitly.
