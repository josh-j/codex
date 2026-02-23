from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.errors import AnsibleFilterError


def validate_run_ctx(run_ctx, context="run_ctx"):
    """Validates the run_ctx dict set by init_run_ctx.yaml."""
    if not isinstance(run_ctx, dict):
        raise AnsibleFilterError(f"validate_run_ctx: expected dict, got {type(run_ctx)}")

    for key in ("id", "date", "timestamp", "day"):
        if key not in run_ctx:
            raise AnsibleFilterError(f"validate_run_ctx [{context}]: missing key '{key}'")

    return run_ctx


def validate_vmware_ctx(vmware_ctx, context="vmware_ctx"):
    """Validates the vmware_ctx dict assembled during vmware audit discovery."""
    if not isinstance(vmware_ctx, dict):
        raise AnsibleFilterError(f"validate_vmware_ctx: expected dict, got {type(vmware_ctx)}")

    for key in ("discovery", "health", "inventory"):
        if key not in vmware_ctx:
            raise AnsibleFilterError(f"validate_vmware_ctx [{context}]: missing key '{key}'")

    return vmware_ctx


class FilterModule(object):
    def filters(self):
        return {
            "validate_run_ctx":    validate_run_ctx,
            "validate_vmware_ctx": validate_vmware_ctx,
        }
