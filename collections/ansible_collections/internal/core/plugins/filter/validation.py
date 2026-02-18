from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.errors import AnsibleFilterError

def validate_ops_data(ops, context="host"):
    """
    Validates the structure of the 'ops' dictionary to ensure it has required keys
    for aggregation and reporting.
    """
    if not isinstance(ops, dict):
        raise AnsibleFilterError("validate_ops_data: input 'ops' must be a dictionary, got %s" % type(ops))

    required_keys = ['check', 'alerts', 'reports', 'overall']
    for key in required_keys:
        if key not in ops:
            raise AnsibleFilterError("validate_ops_data [%s]: missing required key '%s'" % (context, key))

    if not isinstance(ops['check'], dict):
        raise AnsibleFilterError("validate_ops_data [%s]: 'check' must be a dictionary" % context)
        
    check_keys = ['id', 'date', 'timestamp', 'site']
    for key in check_keys:
        if key not in ops['check']:
            raise AnsibleFilterError("validate_ops_data [%s]: 'check' is missing key '%s'" % (context, key))

    if not isinstance(ops['alerts'], list):
        raise AnsibleFilterError("validate_ops_data [%s]: 'alerts' must be a list" % context)
        
    if not isinstance(ops['reports'], list):
        raise AnsibleFilterError("validate_ops_data [%s]: 'reports' must be a list" % context)

    return ops

class FilterModule(object):
    def filters(self):
        return {
            'validate_ops_data': validate_ops_data
        }
