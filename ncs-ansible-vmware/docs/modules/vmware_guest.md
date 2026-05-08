# `community.vmware.vmware_guest`

**Collection:** `community.vmware` v6.2.0  
**Source:** `community/vmware/plugins/modules/vmware_guest.py`

## Synopsis

Manages virtual machines in vCenter

This module can be used to create new virtual machines from templates or other virtual machines, manage power state of virtual machine such as power on, power off, suspend, shutdown, reboot, restart etc., modify various virtual machine components like network, disk, customization etc., rename a virtual machine and remove a virtual machine with associated components.


## Other parameters

**`advanced_settings`**  *(list, default: `[]`)*
  - Define a list of advanced settings to be added to the VMX config.
  - An advanced settings object takes the two fields C(key) and C(value).
  - Incorrect key and values will be ignored.

**`annotation`**  *(str, aliases: `notes`)*
  - A note or annotation to include in the virtual machine.

**`cdrom`**  *(list, default: `[]`)*
  - A list of CD-ROM configurations for the virtual machine.
  - For V(ide) controller, hot-add or hot-remove CD-ROM is not supported.

**`cluster`**  *(str)*
  - The cluster name where the virtual machine will run.
  - This is a required parameter, if O(esxi_hostname) is not set.
  - O(esxi_hostname) and O(cluster) are mutually exclusive parameters.

**`convert`**  *(str)*
  - Specify convert disk type while cloning template or virtual machine.
  - Choices: `thin`, `thick`, `eagerzeroedthick`

**`customization`**  *(dict, default: `{}`)*
  - Parameters for OS customization when cloning from the template or the virtual machine, or apply to the existing virtual machine directly.
  - Not all operating systems are supported for customization with respective vCenter version, please check VMware documentation for respective OS customization.
  - For supported customization operating system matrix, (see U(http://partnerweb.vmware.com/programs/guestOS/guest-os-customization-matrix.pdf))
  - Linux based OSes requires Perl package to be installed for OS customizations.

**`customization_spec`**  *(str)*
  - Unique name identifying the requested customization specification.
  - If set, then overrides O(customization) parameter values.

**`customvalues`**  *(list, default: `[]`)*
  - Define a list of custom values to set on virtual machine.
  - A custom value object takes the two fields C(key) and C(value).
  - Incorrect key and values will be ignored.

**`datacenter`**  *(str, default: `ha-datacenter`)*
  - Destination datacenter for the deploy operation.

**`datastore`**  *(str)*
  - Specify datastore or datastore cluster to provision virtual machine.
  - This parameter takes precedence over O(disk[].datastore) parameter.
  - This parameter can be used to override datastore or datastore cluster setting of the virtual machine when deployed from the template.
  - Please see example for more usage.

**`delete_from_inventory`**  *(bool, default: `False`)*
  - Whether to delete Virtual machine from inventory or delete from disk.

**`disk`**  *(list, default: `[]`)*
  - A list of disks to add.
  - Shrinking disks is not supported.
  - Removing existing disks of the virtual machine is not supported.
  - Attributes O(disk[].controller_type), O(disk[].controller_number), O(disk[].unit_number) are used to configure multiple types of disk controllers and disks for creating or reconfiguring virtual machine.

**`encryption`**  *(dict, default: `{}`)*
  - Manage virtual machine encryption settings

**`esxi_hostname`**  *(str)*
  - The ESXi hostname where the virtual machine will run.
  - This is a required parameter, if O(cluster) is not set.
  - O(esxi_hostname) and O(cluster) are mutually exclusive parameters.

**`folder`**  *(str)*
  - Destination folder, absolute path to find an existing guest or create the new guest.
  - The folder should include the datacenter. ESXi's datacenter is ha-datacenter.
  - If multiple machines are found with same name, this parameter is used to identify
  - uniqueness of the virtual machine.
  - Examples:
  -    folder: /ha-datacenter/vm
  -    folder: ha-datacenter/vm
  -    folder: /datacenter1/vm
  -    folder: datacenter1/vm
  -    folder: /datacenter1/vm/folder1
  -    folder: datacenter1/vm/folder1
  -    folder: /folder1/datacenter1/vm
  -    folder: folder1/datacenter1/vm
  -    folder: /folder1/datacenter1/vm/folder2

**`force`**  *(bool, default: `False`)*
  - Ignore warnings and complete the actions.
  - This parameter is useful while removing virtual machine which is powered on state.
  - This module reflects the VMware vCenter API and UI workflow, as such, in some cases the `force` flag will be mandatory to perform the action to ensure you are certain the action has to be taken, no matter what the consequence. This is specifically the case for removing a powered on the virtual machine when O(state=absent).

**`guest_id`**  *(str)*
  - Set the guest ID.
  - This field is required when creating a virtual machine, not required when creating from the template.
  - Valid values are referenced here: U(https://code.vmware.com/apis/358/doc/vim.vm.GuestOsDescriptor.GuestOsIdentifier.html)


**`hardware`**  *(dict, default: `{}`)*
  - Manage virtual machine's hardware attributes.

**`is_template`**  *(bool, default: `False`)*
  - Flag the instance as a template.
  - This will mark the given virtual machine as template.
  - Note, this may need to be done in a dedicated task invocation that is not making any other changes. For example, user cannot change the state from powered-on to powered-off AND save as template in the same task.
  - See M(community.vmware.vmware_guest) source for more details.

**`linked_clone`**  *(bool, default: `False`)*
  - Whether to create a linked clone from the snapshot specified.
  - If specified, then O(snapshot_src) is required parameter.

**`name`**  *(str)*
  - Name of the virtual machine to work with.
  - Virtual machine names in vCenter are not necessarily unique, which may be problematic, see O(name_match).
  - If multiple virtual machines with same name exists, then O(folder) is required parameter to identify uniqueness of the virtual machine.
  - This parameter is required, if O(state=poweredon), O(state=powered-on), O(state=poweredoff), O(state=powered-off), O(state=present), O(state=restarted), O(state=suspended) and virtual machine does not exists.

**`name_match`**  *(str, default: `first`)*
  - If multiple virtual machines matching the name, use the first or last found.
  - Choices: `first`, `last`

**`networks`**  *(list, default: `[]`)*
  - A list of networks (in the order of the NICs).
  - Removing NICs is not allowed, while reconfiguring the virtual machine.
  - The I(type), I(ip), I(netmask), I(gateway), I(domain), I(dns_servers) options don't set to a guest when creating a blank new virtual machine. They are set by the customization via vmware-tools. If you want to set the value of the options to a guest, you need to clone from a template with installed OS and vmware-tools (also Perl when Linux).

**`nvdimm`**  *(dict, default: `{}`)*
  - Add or remove a virtual NVDIMM device to the virtual machine.
  - VM virtual hardware version must be 14 or higher on vSphere 6.7 or later.
  - Verify that guest OS of the virtual machine supports PMem before adding virtual NVDIMM device.
  - Verify that you have the I(Datastore.Allocate) space privilege on the virtual machine.
  - Make sure that the host or the cluster on which the virtual machine resides has available PMem resources.
  - To add or remove virtual NVDIMM device to the existing virtual machine, it must be in power off state.

**`resource_pool`**  *(str)*
  - Use the given resource pool for virtual machine operation.
  - Resource pool should be child of the selected host parent.
  - When not specified I(Resources) is taken as default value.

**`snapshot_src`**  *(str)*
  - Name of the existing snapshot to use to create a clone of a virtual machine.
  - While creating linked clone using O(linked_clone) parameter, this parameter is required.

**`state`**  *(str, default: `present`)*
  - Specify the state the virtual machine should be in.
  - If V(present) and virtual machine exists, ensure the virtual machine configurations conforms to task arguments.
  - If V(absent) and virtual machine exists, then the specified virtual machine is removed with it's associated components.
  - If set to one of V(poweredon), V(powered-on), V(poweredoff), V(powered-off), V(present), V(restarted), V(suspended) and virtual machine does not exists, virtual machine is deployed with the given parameters.
  - If set to V(poweredon) or V(powered-on) and virtual machine exists with powerstate other than powered on, then the specified virtual machine is powered on.
  - If set to V(poweredoff) or V(powered-off) and virtual machine exists with powerstate other than powered off, then the specified virtual machine is powered off.
  - If set to V(restarted) and virtual machine exists, then the virtual machine is restarted.
  - If set to V(suspended) and virtual machine exists, then the virtual machine is set to suspended mode.
  - If set to V(shutdownguest) or V(shutdown-guest) and virtual machine exists, then the virtual machine is shutdown.
  - If set to V(rebootguest) or V(reboot-guest) and virtual machine exists, then the virtual machine is rebooted.
  - Choices: `absent`, `poweredon`, `powered-on`, `poweredoff`, `powered-off`, `present`, `rebootguest`, `reboot-guest`, `restarted`, `suspended`, `shutdownguest`, `shutdown-guest`

**`state_change_timeout`**  *(int, default: `0`)*
  - If the O(state=shutdownguest), by default the module will return immediately after sending the shutdown signal.
  - If this argument is set to a positive integer, the module will instead wait for the virtual machine to reach the poweredoff state.
  - The value sets a timeout in seconds for the module to wait for the state change.

**`template`**  *(str, aliases: `template_src`)*
  - Template or existing virtual machine used to create new virtual machine.
  - If this value is not set, virtual machine is created without using a template.
  - If the virtual machine already exists, this parameter will be ignored.
  - From version 2.8 onwards, absolute path to virtual machine or template can be used.

**`use_instance_uuid`**  *(bool, default: `False`)*
  - Whether to use the VMware instance UUID rather than the BIOS UUID.

**`uuid`**  *(str)*
  - UUID of the virtual machine to manage if known, this is VMware's unique identifier.
  - This is required if O(name) is not supplied.
  - If virtual machine does not exists, then this parameter is ignored.
  - Please note that a supplied UUID will be ignored on virtual machine creation, as VMware creates the UUID internally.

**`vapp_properties`**  *(list, default: `[]`)*
  - A list of vApp properties.
  - For full list of attributes and types refer to: U(https://code.vmware.com/apis/704/vsphere/vim.vApp.PropertyInfo.html)

**`wait_for_customization`**  *(bool, default: `False`)*
  - Wait until vCenter detects all guest customizations as successfully completed.
  - When enabled, the VM will automatically be powered on.
  - If vCenter does not detect guest customization start or succeed, failed events after time O(wait_for_customization_timeout) parameter specified, warning message will be printed and task result is fail.

**`wait_for_customization_timeout`**  *(int, default: `3600`)*
  - Define a timeout (in seconds) for the wait_for_customization parameter.
  - Be careful when setting this value since the time guest customization took may differ among guest OSes.

**`wait_for_ip_address`**  *(bool, default: `False`)*
  - Wait until vCenter detects an IP address for the virtual machine.
  - This requires vmware-tools (vmtoolsd) to properly work after creation.
  - vmware-tools needs to be installed on the given virtual machine in order to work with this parameter.

**`wait_for_ip_address_timeout`**  *(int, default: `300`)*
  - Define a timeout (in seconds) for the wait_for_ip_address parameter.

## Connection parameters

These come from the role's `module_defaults` block (sourced from `_vmware_creds`); operators do not set them per-task.

**`hostname`**  *(str)*
  - The hostname or IP address of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_HOST) will be used instead.

**`password`**  *(str, aliases: `pass`, `pwd`)*
  - The password of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PASSWORD) will be used instead.

**`port`**  *(int, default: `443`)*
  - The port number of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PORT) will be used instead.

**`proxy_host`**  *(str)*
  - The address of a proxy that will receive all HTTPS requests and relay them.
  - The format is a hostname or a IP.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PROXY_HOST) will be used instead.

**`proxy_port`**  *(int)*
  - The port of the HTTP proxy that will receive all HTTPS requests and relay them.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_PROXY_PORT) will be used instead.

**`username`**  *(str, aliases: `admin`, `user`)*
  - The username of the vSphere vCenter server.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_USER) will be used instead.

**`validate_certs`**  *(bool, default: `True`)*
  - Allows connection when SSL certificates are not valid. Set to V(false) when certificates are not trusted.
  - If the value is not specified in the task, the value of environment variable E(VMWARE_VALIDATE_CERTS) will be used instead.

## Notes

- Please make sure that the user used for M(community.vmware.vmware_guest) has the correct level of privileges.
- For example, following is the list of minimum privileges required by users to create virtual machines.
-    DataStore > Allocate Space
-    Virtual Machine > Configuration > Add New Disk
-    Virtual Machine > Configuration > Add or Remove Device
-    Virtual Machine > Inventory > Create New
-    Network > Assign Network
-    Resource > Assign Virtual Machine to Resource Pool
- Module may require additional privileges as well, which may be required for gathering facts - e.g. ESXi configurations.
- Use SCSI disks instead of IDE when you want to expand online disks by specifying a SCSI controller.
- Uses SysPrep for Windows VM (depends on 'guest_id' parameter match 'win') with PyVmomi.
- In order to change the VM's parameters (e.g. number of CPUs), the VM must be powered off unless the hot-add support is enabled and the O(state=present) must be used to apply the changes.
- For additional information please visit Ansible VMware community wiki - U(https://github.com/ansible/community/wiki/VMware).
- All modules require API write access and hence are not supported on a free ESXi license.
- All variables and VMware object names are case sensitive.
- Modules may rely on the 'requests' python library, which does not use the system certificate store by default. You can specify the certificate store by setting the REQUESTS_CA_BUNDLE environment variable. Note having this variable set may cause a 'false' value for the 'validate_certs' option to be ignored in some cases. Example: 'export REQUESTS_CA_BUNDLE=/path/to/your/ca_bundle.pem'

## Examples

```yaml
- name: Create a virtual machine on given ESXi hostname
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    folder: /DC1/vm/
    name: test_vm_0001
    state: poweredon
    guest_id: centos64Guest
    # This is hostname of particular ESXi server on which user wants VM to be deployed
    esxi_hostname: "{{ esxi_hostname }}"
    disk:
    - size_gb: 10
      type: thin
      datastore: datastore1
    hardware:
      memory_mb: 512
      num_cpus: 4
      scsi: paravirtual
    networks:
    - name: VM Network
      mac: aa:bb:dd:aa:00:14
      ip: 10.10.10.100
      netmask: 255.255.255.0
      device_type: vmxnet3
    wait_for_ip_address: true
    wait_for_ip_address_timeout: 600
  delegate_to: localhost
  register: deploy_vm

- name: Create a virtual machine from a template
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    folder: /testvms
    name: testvm_2
    state: poweredon
    template: template_el7
    disk:
    - size_gb: 10
      type: thin
      datastore: g73_datastore
    # Add another disk from an existing VMDK
    - filename: "[datastore1] testvms/testvm_2_1/testvm_2_1.vmdk"
    hardware:
      memory_mb: 512
      num_cpus: 6
      num_cpu_cores_per_socket: 3
      scsi: paravirtual
      memory_reservation_lock: true
      mem_limit: 8096
      mem_reservation: 4096
      cpu_shares_level: "high"
      mem_shares_level: "high"
      cpu_limit: 8096
      cpu_reservation: 4096
      max_connections: 5
      hotadd_cpu: true
      hotremove_cpu: true
      hotadd_memory: false
      version: 12 # Hardware version of virtual machine
      boot_firmware: "efi"
    cdrom:
        - controller_number: 0
          unit_number: 0
          state: present
          type: iso
          iso_path: "[datastore1] livecd.iso"
    networks:
    - name: VM Network
      mac: aa:bb:dd:aa:00:14
    wait_for_ip_address: true
  delegate_to: localhost
  register: deploy

- name: Clone a virtual machine from Windows template and customize
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    datacenter: datacenter1
    cluster: cluster
    name: testvm-2
    template: template_windows
    networks:
    - name: VM Network
      ip: 192.168.1.100
      netmask: 255.255.255.0
      gateway: 192.168.1.1
      mac: aa:bb:dd:aa:00:14
      domain: my_domain
      dns_servers:
      - 192.168.1.1
      - 192.168.1.2
    - vlan: 1234
      type: dhcp
    customization:
      autologon: true
      dns_servers:
      - 192.168.1.1
      - 192.168.1.2
      domain: my_domain
      password: new_vm_password
      runonce:
      - powershell.exe -ExecutionPolicy Unrestricted -File C:\Windows\Temp\ConfigureRemotingForAnsible.ps1 -ForceNewSSLCert -EnableCredSSP
  delegate_to: localhost

- name:  Clone a virtual machine from Linux template and customize
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    datacenter: "{{ datacenter }}"
    state: present
    folder: /DC1/vm
    template: "{{ template }}"
    name: "{{ vm_name }}"
    cluster: DC1_C1
    networks:
      - name: VM Network
        ip: 192.168.10.11
        netmask: 255.255.255.0
    wait_for_ip_address: true
    customization:
      domain: "{{ guest_domain }}"
      dns_servers:
        - 8.9.9.9
        - 7.8.8.9
      dns_suffix:
        - example.com
        - example2.com
      script_text: |
        #!/bin/bash
        touch /tmp/touch-from-playbook
  delegate_to: localhost

- name: Rename a virtual machine (requires the virtual machine's uuid)
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    uuid: "{{ vm_uuid }}"
    name: new_name
    state: present
  delegate_to: localhost

- name: Remove a virtual machine by uuid
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    uuid: "{{ vm_uuid }}"
    state: absent
  delegate_to: localhost

- name: Remove a virtual machine from inventory
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    name: vm_name
    delete_from_inventory: true
    state: absent
  delegate_to: localhost

- name: Manipulate vApp properties
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    name: vm_name
    state: present
    vapp_properties:
      - id: remoteIP
        category: Backup
        label: Backup server IP
        type: string
        value: 10.10.10.1
      - id: old_property
        operation: remove
  delegate_to: localhost

- name: Set powerstate of a virtual machine to poweroff by using UUID
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    uuid: "{{ vm_uuid }}"
    state: poweredoff
  delegate_to: localhost

- name: Deploy a virtual machine in a datastore different from the datastore of the template
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    name: "{{ vm_name }}"
    state: present
    template: "{{ template_name }}"
    # Here datastore can be different which holds template
    datastore: "{{ virtual_machine_datastore }}"
    hardware:
      memory_mb: 512
      num_cpus: 2
      scsi: paravirtual
  delegate_to: localhost

- name: Create a diskless VM
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    datacenter: "{{ dc1 }}"
    state: poweredoff
    cluster: "{{ ccr1 }}"
    name: diskless_vm
    folder: /Asia-Datacenter1/vm
    guest_id: centos64Guest
    datastore: "{{ ds1 }}"
    hardware:
        memory_mb: 1024
        num_cpus: 2
        num_cpu_cores_per_socket: 1

- name: Create a VM with multiple disks of different disk controller types
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    folder: /DC1/vm/
    name: test_vm_multi_disks
    state: poweredoff
    guest_id: centos64Guest
    datastore: datastore1
    disk:
    - size_gb: 10
      controller_type: 'nvme'
      controller_number: 0
      unit_number: 0
    - size_gb: 10
      controller_type: 'paravirtual'
      controller_number: 0
      unit_number: 1
    - size_gb: 10
      controller_type: 'sata'
      controller_number: 0
      unit_number: 2
    hardware:
      memory_mb: 512
      num_cpus: 4
      version: 14
    networks:
    - name: VM Network
      device_type: vmxnet3
  delegate_to: localhost
  register: deploy_vm

- name: Create a VM with NVDIMM device
  community.vmware.vmware_guest:
    hostname: "{{ vcenter_hostname }}"
    username: "{{ vcenter_username }}"
    password: "{{ vcenter_password }}"
    folder: /DC1/vm/
    name: test_vm_nvdimm
    state: poweredoff
    guest_id: centos7_64Guest
    datastore: datastore1
    hardware:
      memory_mb: 512
      num_cpus: 4
      version: 14
    networks:
    - name: VM Network
      device_type: vmxnet3
    nvdimm:
      state: present
      size_mb: 2048
  delegate_to: localhost
  register: deploy_vm
```
