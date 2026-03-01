# NCS (Network Control System) Root Justfile

set dotenv-load := true

# --- Variables ---
python           := if path_exists(".venv/bin/pytest") == "true" { ".venv/bin/python" } else { "python3" }
ansible_playbook := "ansible-playbook"
export PYTHONPATH := "tools/ncs_reporter/src:libs/ncs_core/src"

# --- Default ---
default:
    @just --list

# --- Setup ---

# Install all collections and internal tools
setup: setup-collections setup-tools

# Install Ansible collections from requirements.yml
setup-collections:
    ansible-galaxy collection install -r requirements.yml

# Install internal python tools in editable mode
setup-tools:
    {{ python }} -m pip install -e tools/ncs_reporter

# --- Quality Control ---

# Run all quality checks (lint, check, test)
all: setup lint check test jinja-lint ansible-lint

# Run python linting (Ruff)
lint:
    ruff check .

# Auto-format python code
format:
    ruff format .

# Run static type checking (MyPy & Basedpyright)
check:
    mypy .
    {{ if path_exists(".venv/bin/basedpyright") == "true" { ".venv/bin/basedpyright ." } else { "basedpyright . --pythonpath `which python3`" } }}

# Run all unit and E2E tests
test:
    {{ python }} -m pytest tests/unit tools/ncs_reporter/tests

# Run integration tests
integration:
    {{ python }} -m pytest tests/integration -v

# Run Jinja2 template linting
jinja-lint:
    find . -type d -name .venv -prune -o -name "*.j2" -print | xargs j2lint --ignore jinja-statements-indentation single-statement-per-line --

# Run Ansible linting
ansible-lint:
    ANSIBLE_COLLECTIONS_PATH=$(pwd)/collections ansible-lint --exclude .venv

# --- Orchestration ---

# Run the full fleet audit pipeline (Setup -> Audit -> Report)
site:
    {{ ansible_playbook }} playbooks/site.yml

# Run only the VMware audit
audit-vmware:
    {{ ansible_playbook }} playbooks/vmware_audit.yml

# Run only the Ubuntu audit
audit-ubuntu:
    {{ ansible_playbook }} playbooks/ubuntu_audit.yml

# Run only the Windows audit
audit-windows:
    {{ ansible_playbook }} playbooks/windows_audit.yml

# --- Targeted Orchestration ---

# Run STIG Audit for a specific VM on a specific vCenter
# Example: just stig-audit-vm vc-01 my-vm-01
stig-audit-vm vcenter vm_name:
    {{ ansible_playbook }} playbooks/vmware_stig_audit.yml -l {{ vcenter }} -e "vm_stig_target_vms=['{{ vm_name }}']"

# Run STIG Hardening for a specific VM on a specific vCenter (MUTATING)
stig-harden-vm vcenter vm_name:
    {{ ansible_playbook }} playbooks/vmware_stig_remediate.yml -l {{ vcenter }} -e "vm_stig_target_vms=['{{ vm_name }}']"

# Run STIG Audit for a specific ESXi host on a specific vCenter
# Example: just stig-audit-esxi vc-01 esxi-01.local
stig-audit-esxi vcenter host:
    {{ ansible_playbook }} playbooks/vmware_stig_audit.yml -l {{ vcenter }} -e "esxi_stig_target_hosts=['{{ host }}']"

# Run STIG Hardening for a specific ESXi host on a specific vCenter (MUTATING)
stig-harden-esxi vcenter host:
    {{ ansible_playbook }} playbooks/vmware_stig_remediate.yml -l {{ vcenter }} -e "esxi_stig_target_hosts=['{{ host }}']"

# Apply ESXi STIG rules interactively, one at a time, from a prior audit artifact (MUTATING)
# Requires ncs-reporter installed (just setup-tools). Example: just stig-apply-esxi artifacts/vc1/raw_stig_esxi.yaml vc1 esxi-01.local
stig-apply-esxi artifact vcenter esxi_host:
    ncs-reporter stig-apply {{ artifact }} --limit {{ vcenter }} --esxi-host {{ esxi_host }}

# Audit a specific Linux host
audit-linux-host hostname:
    {{ ansible_playbook }} playbooks/ubuntu_audit.yml -l {{ hostname }}

# Audit a specific Windows host
audit-windows-host hostname:
    {{ ansible_playbook }} playbooks/windows_audit.yml -l {{ hostname }}

# --- Maintenance ---

# Initialize the Samba report share (Run once)
init-samba:
    {{ ansible_playbook }} playbooks/setup_samba.yml

# Clean up all temporary build/cache artifacts
clean:
    rm -rf .venv .mypy_cache .ruff_cache .pytest_cache .coverage
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type d -name ".artifacts" -exec rm -rf {} +
