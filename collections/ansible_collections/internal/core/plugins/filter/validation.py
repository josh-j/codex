from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

from ansible.errors import AnsibleFilterError

def validate_ncs_data(ncs, context="host"):
    """
    Validates the structure of the 'ncs' dictionary to ensure it has required keys
    for aggregation and reporting.
    """
    if not isinstance(ncs, dict):
        raise AnsibleFilterError("validate_ncs_data: input 'ncs' must be a dictionary, got %s" % type(ncs))

    required_keys = ['check', 'alerts', 'reports', 'overall']
    for key in required_keys:
        if key not in ncs:
            raise AnsibleFilterError("validate_ncs_data [%s]: missing required key '%s'" % (context, key))

    if not isinstance(ncs['check'], dict):
        raise AnsibleFilterError("validate_ncs_data [%s]: 'check' must be a dictionary" % context)
        
    check_keys = ['id', 'date', 'timestamp', 'site']
    for key in check_keys:
        if key not in ncs['check']:
            raise AnsibleFilterError("validate_ncs_data [%s]: 'check' is missing key '%s'" % (context, key))

    if not isinstance(ncs['alerts'], list):
        raise AnsibleFilterError("validate_ncs_data [%s]: 'alerts' must be a list" % context)
        
    if not isinstance(ncs['reports'], list):
        raise AnsibleFilterError("validate_ncs_data [%s]: 'reports' must be a list" % context)

    return ncs

class FilterModule(object):
    def filters(self):
        return {
            'validate_ncs_data': validate_ncs_data
        }
