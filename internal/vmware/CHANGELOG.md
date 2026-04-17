# Changelog — internal.vmware

## 1.1.0

- Ship platform playbooks inside the collection. The operator-facing entry
  points moved from `playbooks/vmware/<sub>/<action>.yml` (in the app repo)
  into `internal/vmware/playbooks/<sub>_<action>.yml` (inside the collection).
  Invoke via FQCN, e.g. `ansible-playbook internal.vmware.esxi_stig_audit`.
- Standalone lab playbooks relocated from `playbooks/test/` to
  `internal.vmware.dev_esxi_standalone_stig_audit` and
  `internal.vmware.dev_vm_standalone_stig_audit`.
- Roles, action/module plugins, and callbacks are unchanged from 1.0.0.

## 1.0.0

- Initial release with audit + STIG roles for esxi, vcsa, vm.
