#!/usr/bin/env python3
# collections/ansible_collections/internal/vmware/roles/stig/files/get_vm_stig_facts.py
# NOTE: Only retrieves information -- no mutations/side-effects
import json
import logging
import ssl
import sys

from pyVim.connect import Disconnect, SmartConnect
from pyVmomi import vim

# [LOGGING SETUP]
# Write to /tmp to ensure persistence across Ansible runs
log_file = "/tmp/get_vm_stig_facts.log"

logging.basicConfig(
    filename=log_file,
    filemode="w",  # Overwrite on each run
    level=logging.DEBUG,
    format="%(asctime)s - %(levelname)s - %(message)s",
)


def get_vm_stig_data(host, user, password, vm_filter=None):
    context = ssl._create_unverified_context()
    si = None

    try:
        logging.info(f"Script started. Target: {host}, User: {user}")
        si = SmartConnect(host=host, user=user, pwd=password, sslContext=context)
        logging.info("Connected to vCenter successfully.")

        content = si.RetrieveContent()
        container = content.rootFolder
        view_type = [vim.VirtualMachine]
        recursive = True

        container_view = content.viewManager.CreateContainerView(
            container, view_type, recursive
        )
        children = container_view.view
        logging.info(f"Retrieved {len(children)} total VMs from vCenter inventory.")

        vms_data = []
        schema_logged = False  # Flag to log the schema only once

        for vm in children:
            try:
                # Apply Filter (Case-Insensitive)
                if vm_filter and vm_filter != "None" and vm_filter != "":
                    if vm.name.lower() != vm_filter.lower():
                        continue

                # Skip templates
                if vm.config.template:
                    logging.debug(f"Skipping Template: {vm.name}")
                    continue

                logging.info(f"Processing VM: {vm.name}")

                # 1. Advanced Settings
                advanced_settings = {}
                if vm.config.extraConfig:
                    for option in vm.config.extraConfig:
                        advanced_settings[option.key] = option.value

                # 2. Hardware Scanning
                floppies = []
                cdroms = []
                serial_ports = []
                parallel_ports = []
                disks = []
                usb_present = False

                for device in vm.config.hardware.device:
                    # Floppy
                    if isinstance(device, vim.vm.device.VirtualFloppy):
                        floppies.append(
                            {
                                "label": device.deviceInfo.label,
                                "connected": device.connectable.connected,
                                "start_connected": device.connectable.startConnected,
                            }
                        )
                        logging.warning(
                            f"  [!] Floppy found: {device.deviceInfo.label}"
                        )

                    # CD-ROM
                    elif isinstance(device, vim.vm.device.VirtualCdrom):
                        backing = "iso"
                        if isinstance(
                            device.backing, vim.vm.device.VirtualCdrom.AtapiBackingInfo
                        ):
                            backing = "host_device"
                        cdroms.append(
                            {
                                "label": device.deviceInfo.label,
                                "connected": device.connectable.connected,
                                "start_connected": device.connectable.startConnected,
                                "backing": backing,
                            }
                        )

                    # Serial
                    elif isinstance(device, vim.vm.device.VirtualSerialPort):
                        serial_ports.append({"label": device.deviceInfo.label})
                        logging.warning(
                            f"  [!] Serial Port found: {device.deviceInfo.label}"
                        )

                    # Parallel
                    elif isinstance(device, vim.vm.device.VirtualParallelPort):
                        parallel_ports.append({"label": device.deviceInfo.label})
                        logging.warning(
                            f"  [!] Parallel Port found: {device.deviceInfo.label}"
                        )

                    # Disks (Persistence Check)
                    elif isinstance(device, vim.vm.device.VirtualDisk):
                        disk_mode = "persistent"
                        if hasattr(device.backing, "diskMode"):
                            disk_mode = device.backing.diskMode
                        disks.append(
                            {"label": device.deviceInfo.label, "disk_mode": disk_mode}
                        )
                        if disk_mode != "persistent":
                            logging.warning(
                                f"  [!] Disk Mode '{disk_mode}' found on {device.deviceInfo.label}"
                            )

                    # USB Controllers
                    elif isinstance(device, vim.vm.device.VirtualUSBController):
                        usb_present = True
                        logging.warning("  [!] USB Controller found")

                # 3. Encryption / TPM / Security Features
                encryption = "None"
                if vm.config.keyId:
                    encryption = "Encrypted"

                vmotion_enc = "disabled"
                if hasattr(vm.config, "migrateEncryption"):
                    vmotion_enc = vm.config.migrateEncryption

                logging_enabled = True
                if hasattr(vm.config, "flags") and hasattr(
                    vm.config.flags, "enableLogging"
                ):
                    logging_enabled = vm.config.flags.enableLogging

                ft_encryption = "ftEncryptionDisabled"
                if hasattr(vm.config, "ftEncryptionMode"):
                    ft_encryption = vm.config.ftEncryptionMode

                # 4. Construct Payload
                vm_info = {
                    "name": vm.name,
                    "uuid": vm.config.uuid,
                    "guest_id": vm.config.guestId,
                    "advanced_settings": advanced_settings,
                    "hardware": {
                        "floppies": floppies,
                        "cdroms": cdroms,
                        "serial_ports": serial_ports,
                        "parallel_ports": parallel_ports,
                        "disks": disks,
                        "usb_present": usb_present,
                    },
                    "tools_status": vm.guest.toolsStatus,
                    "encryption": encryption,
                    "vmotion_encryption": vmotion_enc,
                    "logging_enabled": logging_enabled,
                    "ft_encryption": ft_encryption,
                }

                # [DEBUG] Log the full schema for the first VM found
                if not schema_logged:
                    logging.debug("=== DATA SCHEMA SNAPSHOT ===")
                    logging.debug(json.dumps(vm_info, default=str, indent=4))
                    logging.debug("============================")
                    schema_logged = True

                vms_data.append(vm_info)

            except Exception as vm_e:
                logging.error(f"Error processing VM {vm.name}: {str(vm_e)}")
                continue

        container_view.Destroy()
        Disconnect(si)
        return {"success": True, "vms": vms_data, "count": len(vms_data)}

    except Exception as e:
        logging.critical(f"Critical Failure: {str(e)}")
        if si:
            Disconnect(si)
        return {"success": False, "error": str(e), "vms": [], "count": 0}


if __name__ == "__main__":
    if len(sys.argv) < 4:
        err = "Usage: script.py <host> <user> <password> [filter]"
        logging.error(err)
        print(json.dumps({"success": False, "error": err}))
        sys.exit(1)

    vm_filter_arg = sys.argv[4] if len(sys.argv) > 4 else None

    # Run
    result = get_vm_stig_data(sys.argv[1], sys.argv[2], sys.argv[3], vm_filter_arg)
    print(json.dumps(result))
