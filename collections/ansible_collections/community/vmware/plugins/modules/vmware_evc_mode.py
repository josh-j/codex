#!/usr/bin/python

# Copyright: (c) 2019, Michael Tipton <mike () ibeta.org>
# GNU General Public License v3.0+ (see LICENSES/GPL-3.0-or-later.txt or https://www.gnu.org/licenses/gpl-3.0.txt)
# SPDX-License-Identifier: GPL-3.0-or-later



DOCUMENTATION = r'''
---
module: vmware_evc_mode
short_description: Enable/Disable EVC mode on vCenter
description:
    - This module can be used to enable/disable EVC mode on vCenter.
author:
    - Michael Tipton (@castawayegr)
options:
  datacenter_name:
    description:
    - The name of the datacenter the cluster belongs to that you want to enable or disable EVC mode on.
    required: true
    type: str
    aliases:
      - datacenter
  cluster_name:
    description:
    - The name of the cluster to enable or disable EVC mode on.
    required: true
    type: str
    aliases:
      - cluster
  evc_mode:
    description:
    - Required for O(state=present).
    - The EVC mode to enable or disable on the cluster. (intel-broadwell, intel-nehalem, intel-merom, etc.).
    type: str
  state:
    description:
    - Add or remove EVC mode.
    choices: [absent, present]
    default: present
    type: str
extends_documentation_fragment:
- community.vmware.vmware.documentation

'''

EXAMPLES = r'''
    - name: Enable EVC Mode
      community.vmware.vmware_evc_mode:
         hostname: "{{ groups['vcsa'][0] }}"
         username: "{{ vcenter_username }}"
         password: "{{ site_password }}"
         datacenter_name: "{{ datacenter_name }}"
         cluster_name: "{{ cluster_name }}"
         evc_mode: "intel-broadwell"
         state: present
      delegate_to: localhost
      register: enable_evc

    - name: Disable EVC Mode
      community.vmware.vmware_evc_mode:
         hostname: "{{ groups['vcsa'][0] }}"
         username: "{{ vcenter_username }}"
         password: "{{ site_password }}"
         datacenter_name: "{{ datacenter_name }}"
         cluster_name: "{{ cluster_name }}"
         state: absent
      delegate_to: localhost
      register: disable_evc
'''

RETURN = r'''
result:
    description: information about performed operation
    returned: always
    type: str
    sample: "EVC Mode for 'intel-broadwell' has been enabled."
'''


from ansible.module_utils._text import to_native
from ansible.module_utils.basic import AnsibleModule
from ansible_collections.community.vmware.plugins.module_utils.vmware import (
    PyVmomi,
    TaskError,
    find_datacenter_by_name,
    vmware_argument_spec,
    wait_for_task,
)


class VMwareEVC(PyVmomi):
    def __init__(self, module):
        super().__init__(module)
        self.cluster_name = module.params['cluster_name']
        self.evc_mode = module.params['evc_mode']
        self.datacenter_name = module.params['datacenter_name']
        self.desired_state = module.params['state']
        self.datacenter = None
        self.cluster = None

    def process_state(self):
        """
        Manage internal states of evc
        """
        evc_states = {
            'absent': {
                'present': self.state_disable_evc,
                'absent': self.state_exit_unchanged,
            },
            'present': {
                'present': self.state_update_evc,
                'absent': self.state_enable_evc,
            }
        }
        current_state = self.check_evc_configuration()
        # Based on the desired_state and the current_state call
        # the appropriate method from the dictionary
        evc_states[self.desired_state][current_state]()

    def check_evc_configuration(self):
        """
        Check evc configuration
        Returns: 'Present' if evc enabled, else 'absent'
        """
        try:
            self.datacenter = find_datacenter_by_name(self.content, self.datacenter_name)
            if self.datacenter is None:
                self.module.fail_json(msg=f"Datacenter '{self.datacenter_name}' does not exist.")
            self.cluster = self.find_cluster_by_name(cluster_name=self.cluster_name, datacenter_name=self.datacenter)

            if self.cluster is None:
                self.module.fail_json(msg=f"Cluster '{self.cluster_name}' does not exist.")
            self.evcm = self.cluster.EvcManager()

            if not self.evcm:
                self.module.fail_json(msg=f"Unable to get EVC manager for cluster '{self.cluster_name}'.")
            self.evc_state = self.evcm.evcState
            self.current_evc_mode = self.evc_state.currentEVCModeKey

            if not self.current_evc_mode:
                return 'absent'

            return 'present'
        except Exception as generic_exc:
            self.module.fail_json(msg="Failed to check configuration"
                                      f" due to generic exception {to_native(generic_exc)}")

    def state_exit_unchanged(self):
        """
        Exit without any change
        """
        self.module.exit_json(changed=False, msg=f"EVC Mode is already disabled on cluster '{self.cluster_name}'.")

    def state_update_evc(self):
        """
        Update EVC Mode
        """
        changed, _result = False, None
        try:
            if not self.module.check_mode and self.current_evc_mode != self.evc_mode:
                evc_task = self.evcm.ConfigureEvcMode_Task(self.evc_mode)
                changed, _result = wait_for_task(evc_task)
            if self.module.check_mode and self.current_evc_mode != self.evc_mode:
                changed = True
            if self.current_evc_mode == self.evc_mode:
                self.module.exit_json(changed=changed, msg="EVC Mode is already set to '{evc_mode}' on '{cluster_name}'.".format(**self.params))
            self.module.exit_json(changed=changed, msg="EVC Mode has been updated to '{evc_mode}' on '{cluster_name}'.".format(**self.params))
        except TaskError as invalid_argument:
            self.module.fail_json(msg=f"Failed to update EVC mode: {to_native(invalid_argument)}")

    def state_enable_evc(self):
        """
        Enable EVC Mode
        """
        changed, _result = False, None
        try:
            if not self.module.check_mode:
                evc_task = self.evcm.ConfigureEvcMode_Task(self.evc_mode)
                changed, _result = wait_for_task(evc_task)
            if self.module.check_mode:
                changed = True
            self.module.exit_json(changed=changed, msg="EVC Mode for '{evc_mode}' has been enabled on '{cluster_name}'.".format(**self.params))
        except TaskError as invalid_argument:
            self.module.fail_json(msg=f"Failed to enable EVC mode: {to_native(invalid_argument)}")

    def state_disable_evc(self):
        """
        Disable EVC Mode
        """
        changed, _result = False, None
        try:
            if not self.module.check_mode:
                evc_task = self.evcm.DisableEvcMode_Task()
                changed, _result = wait_for_task(evc_task)
            if self.module.check_mode:
                changed = True
            self.module.exit_json(changed=changed, msg=f"EVC Mode has been disabled on cluster '{self.cluster_name}'.")
        except TaskError as invalid_argument:
            self.module.fail_json(msg=f"Failed to disable EVC mode: {to_native(invalid_argument)}")


def main():
    argument_spec = vmware_argument_spec()
    argument_spec.update(dict(
        cluster_name=dict(type='str', required=True, aliases=['cluster']),
        datacenter_name=dict(type='str', required=True, aliases=['datacenter']),
        evc_mode=dict(type='str'),
        state=dict(type='str', default='present', choices=['absent', 'present']),
    ))

    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_if=[
            ['state', 'present', ['evc_mode']]
        ]
    )

    vmware_evc = VMwareEVC(module)
    vmware_evc.process_state()


if __name__ == '__main__':
    main()
