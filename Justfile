# NCS (Non-Core Services) Root Justfile

set dotenv-load := true

# Ensure ncs_collector callback can find platform configs
export NCS_REPO_ROOT := justfile_directory()

# --- Variables ---
python           := if path_exists(".venv/bin/python3") == "true" { ".venv/bin/python3" } else { "python3" }
ansible_playbook := if path_exists(".venv/bin/ansible-playbook") == "true" { ".venv/bin/ansible-playbook" } else { "ansible-playbook" }
ansible_inventory := if path_exists(".venv/bin/ansible-inventory") == "true" { ".venv/bin/ansible-inventory" } else { "ansible-inventory" }
ansible_vault    := if path_exists(".venv/bin/ansible-vault") == "true" { ".venv/bin/ansible-vault" } else { "ansible-vault" }
ncs_reporter     := if path_exists(".venv/bin/ncs-reporter") == "true" { ".venv/bin/ncs-reporter" } else { "ncs-reporter" }
# VCSA SSH-based STIG requires ansible-core 2.15 + Python 3.7-compat collections
vcsa_playbook    := "ANSIBLE_CONFIG=ansible-vcsa.cfg " + (if path_exists(".venv-vcsa/bin/ansible-playbook") == "true" { ".venv-vcsa/bin/ansible-playbook" } else { ansible_playbook })
reporter_config_dir := "files/ncs-reporter_configs"
inventory_file   := "inventory/production/"
reports_dir      := "/srv/samba/reports"
platform_root    := reports_dir + "/platform"
groups_json      := platform_root + "/inventory_groups.json"
vaultpass        := ".vaultpass"

# --- Default ---
default:
    @just --list

# =============================================================================
# Setup
# =============================================================================
# Complete environment setup (both venvs + all collections)
setup-all: setup-main-venv setup-vcsa-venv setup-collections
    @echo "✓ All environments ready"

# Create main .venv with all dependencies
setup-main-venv:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ -f "pyproject.toml" ] && command -v uv >/dev/null 2>&1; then
        echo "Installing via uv sync..."
        UV_CACHE_DIR=/tmp/uv-cache uv sync --dev
    else
        echo "Installing via pip..."
        python3.12 -m venv .venv
        .venv/bin/pip install --upgrade pip
        .venv/bin/pip install ansible-core pyvmomi pykerberos
        .venv/bin/pip install -e ../ncs-reporter
        .venv/bin/pip install ruff mypy pytest basedpyright
    fi
    echo "✓ Main venv ready"
    .venv/bin/ansible --version | head -1
    .venv/bin/python -c "from pyVim.connect import SmartConnect; print('✓ pyvmomi OK')" 2>/dev/null || echo "⚠ pyvmomi not found — run: uv sync"

# Create VCSA-compatible venv with ansible-core 2.15 (Python 3.7 managed nodes)
setup-vcsa-venv:
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf .venv-vcsa
    python3.12 -m venv .venv-vcsa
    .venv-vcsa/bin/pip install --upgrade pip
    .venv-vcsa/bin/pip install 'ansible-core>=2.15,<2.16' pyvmomi pykerberos
    # Python 3.7-compatible community collections in separate path.
    # vmware.vmware pinned to <2.0.0: latest requires ansible-core >=2.17,
    # but VCSA venv is locked to 2.15 for Python 3.7 managed nodes.
    mkdir -p collections_vcsa/ansible_collections
    ANSIBLE_CONFIG=ansible-vcsa.cfg .venv-vcsa/bin/ansible-galaxy collection install \
        'community.general:>=8.0.0,<9.0.0' \
        'community.vmware:>=4.0.0,<5.0.0' \
        'vmware.vmware:<2.0.0' \
        -p collections_vcsa --force
    # Symlink internal collections so both envs share them
    ln -sfn "$(pwd)/collections/ansible_collections/internal" \
        collections_vcsa/ansible_collections/internal
    # Symlink each vmware sub-collection individually (the vmware namespace dir
    # is shared with galaxy-installed vmware.vmware, so we can't symlink the
    # whole namespace)
    if [ -d "collections/ansible_collections/vmware" ]; then
        mkdir -p collections_vcsa/ansible_collections/vmware
        for col in collections/ansible_collections/vmware/*/; do
            [ -d "$col" ] || continue
            name=$(basename "$col")
            ln -sfn "$(pwd)/$col" "collections_vcsa/ansible_collections/vmware/$name"
        done
    fi
    echo "✓ VCSA venv ready"
    .venv-vcsa/bin/ansible --version | head -1

# Install Ansible collections (main venv)
setup-collections:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Installing collections for main venv..."
    .venv/bin/ansible-galaxy collection install ansible.posix community.vmware community.general --force
    echo "✓ Main collections installed"
    # Verify internal collections are symlinked into vcsa path
    if [ -d "collections_vcsa/ansible_collections" ]; then
        ln -sfn "$(pwd)/collections/ansible_collections/internal" \
            collections_vcsa/ansible_collections/internal
        if [ -d "collections/ansible_collections/vmware" ]; then
            mkdir -p collections_vcsa/ansible_collections/vmware
            for col in collections/ansible_collections/vmware/*/; do
                [ -d "$col" ] || continue
                name=$(basename "$col")
                ln -sfn "$(pwd)/$col" "collections_vcsa/ansible_collections/vmware/$name"
            done
        fi
        echo "✓ VCSA collection symlinks refreshed"
    fi

# Verify both environments are correctly configured
verify-env:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "=== Main venv ==="
    .venv/bin/ansible --version | head -1
    .venv/bin/python -c "from pyVim.connect import SmartConnect; print('  pyvmomi: OK')"
    .venv/bin/ansible-galaxy collection list community.vmware 2>/dev/null | tail -1
    .venv/bin/ansible-galaxy collection list internal.core 2>/dev/null | tail -1
    echo ""
    echo "=== VCSA venv ==="
    if [ -f ".venv-vcsa/bin/ansible" ]; then
        .venv-vcsa/bin/ansible --version | head -1
        ANSIBLE_CONFIG=ansible-vcsa.cfg .venv-vcsa/bin/ansible-galaxy collection list community.general 2>/dev/null | tail -1
        ANSIBLE_CONFIG=ansible-vcsa.cfg .venv-vcsa/bin/ansible-galaxy collection list community.vmware 2>/dev/null | tail -1
        ANSIBLE_CONFIG=ansible-vcsa.cfg .venv-vcsa/bin/ansible-galaxy collection list internal.core 2>/dev/null | tail -1
    else
        echo "  ⚠ Not set up — run: just setup-vcsa-venv"
    fi
# =============================================================================
# Quality Control
# =============================================================================

# Run all quality checks
# all: setup lint check test jinja-lint ansible-lint

# Run python linting (Ruff)
lint:
    ruff check .

# Lint ncs-reporter YAML configs for style conventions
lint-configs:
    {{ python }} ncs-reporter/scripts/lint_configs.py

# Auto-format python code
format:
    ruff format .

# Run static type checking
check:
    mypy .
    {{ if path_exists(".venv/bin/basedpyright") == "true" { ".venv/bin/basedpyright ." } else { "basedpyright . --pythonpath `which python3`" } }}

# Run unit tests
test:
    {{ python }} -m pytest tests/unit

# Run integration tests
integration:
    {{ python }} -m pytest tests/integration -v

# Run Jinja2 template linting
jinja-lint:
    find . -type d -name .venv -prune -o -name "*.j2" -print | xargs j2lint --ignore jinja-statements-indentation single-statement-per-line --

# Run Ansible linting
ansible-lint:
    ANSIBLE_COLLECTIONS_PATH=$(pwd)/collections ansible-lint --exclude .venv

# Regenerate JSON Schema for YAML editor autocomplete
schema:
    cd ncs-reporter && {{ python }} generate_schema.py

# =============================================================================
# Fleet Audits (non-STIG health/compliance collection)
# =============================================================================

# Run the full fleet audit pipeline (Setup -> Audit -> Report)
site:
    {{ ansible_playbook }} playbooks/site.yml

# Run collection only (no report rendering)
site-collect:
    {{ ansible_playbook }} playbooks/site_collect_only.yml

# Run reporting only from existing artifacts
site-reports:
    {{ ansible_playbook }} playbooks/site_reports_only.yml

# Run VMware-only collection and reporting
site-vmware:
    {{ ansible_playbook }} playbooks/site_vmware_only.yml

# Run Windows-only collection and reporting
site-windows:
    {{ ansible_playbook }} playbooks/site_windows_only.yml

# Run VMware health audit (all sites or limited)
audit-vmware target="vcsa":
    {{ ansible_playbook }} playbooks/vmware/collect.yml -l {{ target }} -v

# Run VMware health audit for a single site
audit-vmware-site site:
    {{ ansible_playbook }} playbooks/vmware/collect.yml -l vcsa-{{ site }}

# Run ESXi health audit (all sites or limited)
audit-esxi target="vcsa":
    {{ ansible_playbook }} playbooks/vmware/esxi/collect.yml -l {{ target }} -v

# Run ESXi health audit for a single site
audit-esxi-site site:
    {{ ansible_playbook }} playbooks/vmware/esxi/collect.yml -l vcsa-{{ site }}

# Run VM workload audit (all sites or limited)
audit-vm target="vcsa":
    {{ ansible_playbook }} playbooks/vmware/vm/collect.yml -l {{ target }} -v

# Run VM workload audit for a single site
audit-vm-site site:
    {{ ansible_playbook }} playbooks/vmware/vm/collect.yml -l vcsa-{{ site }}

# Run Ubuntu audit
audit-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/linux/ubuntu/collect.yml -l {{ target }}

# Run Ubuntu apt update + dist-upgrade
update-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/linux/ubuntu/update.yml -l {{ target }}

# Run Ubuntu update (apply only, skip discover)
update-ubuntu-apply target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/linux/ubuntu/update_apply.yml -l {{ target }}

# Run Ubuntu discovery phase only
audit-ubuntu-discover:
    {{ ansible_playbook }} playbooks/linux/ubuntu/collect.yml

# Run Windows audit
audit-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/server/collect.yml -l {{ target }}

# Run Windows update apply phase
update-windows:
    {{ ansible_playbook }} playbooks/windows/server/patch.yml

# Run Windows health check
health-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/server/health.yml -l {{ target }}

# Run Windows cleanup
cleanup-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/server/cleanup.yml -l {{ target }}

# Run Windows post-patch audit phase
audit-windows-post-patch:
    {{ ansible_playbook }} playbooks/windows/server/post_patch_audit.yml

# Audit a specific Linux host
audit-linux-host hostname:
    {{ ansible_playbook }} playbooks/linux/ubuntu/collect.yml -l {{ hostname }}

# Audit a specific Windows host
audit-windows-host hostname:
    {{ ansible_playbook }} playbooks/windows/server/collect.yml -l {{ hostname }}

# =============================================================================
# Windows Administration (targeted single-host actions)
# =============================================================================

# Run Windows health check on a target
windows-health target:
    {{ ansible_playbook }} playbooks/windows/server/health.yml -l {{ target }}

# Run Windows vulnerability scan on a target
windows-vuln-scan target:
    {{ ansible_playbook }} playbooks/windows/server/vuln_scan.yml -l {{ target }}

# Apply Windows registry fixes on a target
windows-registry-fix target:
    {{ ansible_playbook }} playbooks/windows/server/registry_fix.yml -l {{ target }}

# Install a Windows KB update on a target
windows-kb-install target:
    {{ ansible_playbook }} playbooks/windows/server/kb_install.yml -l {{ target }}

# Update software on a Windows target
windows-update-software target:
    {{ ansible_playbook }} playbooks/windows/server/update_software.yml -l {{ target }}

# Uninstall software from a Windows target
windows-uninstall-software target:
    {{ ansible_playbook }} playbooks/windows/server/uninstall_software.yml -l {{ target }}

# Run disk/temp cleanup on a Windows target
windows-cleanup target:
    {{ ansible_playbook }} playbooks/windows/server/cleanup.yml -l {{ target }}

# Run Windows Update on a target
windows-update target:
    {{ ansible_playbook }} playbooks/windows/server/windows_update.yml -l {{ target }}

# Manage a Windows service (action: start|stop|restart, name: service name)
windows-service target action name:
    {{ ansible_playbook }} playbooks/windows/server/service.yml -l {{ target }} -e 'service_action={{ action }} service_name={{ name }}'

# Manage a Windows scheduled task (action: create|delete|enable|disable, name: task name)
windows-scheduled-task target action name:
    {{ ansible_playbook }} playbooks/windows/server/scheduled_task.yml -l {{ target }} -e 'task_action={{ action }} task_name={{ name }}'

# Enable WinRM on a Windows target
windows-winrm-enable target:
    {{ ansible_playbook }} playbooks/windows/server/winrm_enable.yml -l {{ target }}

# Run remote operations on a Windows target (op: operation name)
windows-remote-ops target op:
    {{ ansible_playbook }} playbooks/windows/server/remote_ops.yml -l {{ target }} -e 'remote_op={{ op }}'

# Search Active Directory (type: user|group|computer, term: search term)
windows-ad-search type term:
    {{ ansible_playbook }} playbooks/windows/server/ad_search.yml -e 'ad_search_type={{ type }} ad_search_term={{ term }}'

# Install/configure OpenSSH on a Windows target
windows-openssh target:
    {{ ansible_playbook }} playbooks/windows/server/openssh.yml -l {{ target }}

# Bootstrap OpenSSH on Windows targets via WinRM (first-time setup)
windows-openssh-bootstrap target transport="kerberos":
    {{ ansible_playbook }} playbooks/windows/server/openssh.yml -l {{ target }} -e 'ansible_connection=winrm ansible_winrm_transport={{ transport }} ansible_port=5985'

# =============================================================================
# STIG Audits (read-only compliance checks)
# =============================================================================

# Generate STIG HTML reports + CKLB artifacts from collected raw data
[no-exit-message]
_stig-report:
    #!/usr/bin/env bash
    set -euo pipefail
    echo ""
    echo "Generating STIG reports and CKLB artifacts..."
    {{ ansible_playbook }} playbooks/ncs/generate_reports.yml
    echo "✓ Reports written to {{ reports_dir }}"

# --- ESXi STIG ---

# Audit ESXi hosts (accepts host, group, or vCenter as target)
stig-audit-esxi target: && _stig-report
    {{ ansible_playbook }} playbooks/vmware/esxi/stig_audit.yml -l {{ target }}

# Audit all ESXi hosts at a site (auto-discovers from vCenter)
stig-audit-esxi-site site: && _stig-report
    {{ ansible_playbook }} playbooks/vmware/esxi/stig_audit.yml \
        -l vcsa-{{ site }} -f 14

# Audit all ESXi hosts at a site with custom inventory
stig-audit-esxi-site-inv site inv: && _stig-report
    {{ ansible_playbook }} -i {{ inv }} playbooks/vmware/esxi/stig_audit.yml \
        -l vcsa-{{ site }} -f 10

# --- VM STIG ---

# Audit a single VM
stig-audit-vm vcenter vm_name: && _stig-report
    {{ ansible_playbook }} playbooks/vmware/vm/stig_audit.yml \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# Audit all VMs at a site (auto-discovers from vCenter)
stig-audit-vm-site site: && _stig-report
    {{ ansible_playbook }} playbooks/vmware/vm/stig_audit.yml \
        -l vcsa-{{ site }} \
        -f 14

# --- VCSA Health ---

# Run VCSA health audit (all sites or limited)
audit-vcsa target="vcsa":
    {{ ansible_playbook }} playbooks/vmware/vcsa/collect.yml -l {{ target }} -v

# Run VCSA health audit for a single site
audit-vcsa-site site:
    {{ ansible_playbook }} playbooks/vmware/vcsa/collect.yml -l vcsa-{{ site }}

# --- VCSA STIG (requires .venv-vcsa for Python 3.7 managed nodes) ---

# Audit all VCSA components
stig-audit-vcsa target="vcsa": && _stig-report
    {{ vcsa_playbook }} playbooks/vmware/vcsa/stig_audit.yml -l {{ target }}

# Audit VCSA for a single site
stig-audit-vcsa-site site: && _stig-report
    {{ vcsa_playbook }} playbooks/vmware/vcsa/stig_audit.yml -l vcsa-{{ site }}

# Audit specific VCSA roles only (for incremental testing)
# Example: just stig-audit-vcsa-roles sdhm vami eam postgresql
stig-audit-vcsa-roles site +components:
    #!/usr/bin/env bash
    set -euo pipefail
    roles=$(echo "{{ components }}" | tr ' ' '\n' | sed 's/^vcsa_//' | sed 's/^/internal.vmware.vcsa_/' | jq -R . | jq -s '{"vcsa_stig_roles": .}')
    {{ vcsa_playbook }} playbooks/vmware/vcsa/stig_audit.yml \
        -l vcsa-{{ site }} \
        -e "$roles"
    just _stig-report

# Audit VCSA with custom inventory
stig-audit-vcsa-inv target inv: && _stig-report
    {{ vcsa_playbook }} -i {{ inv }} playbooks/vmware/vcsa/stig_audit.yml -l {{ target }}

# --- Photon STIG ---

# Audit Photon OS servers
stig-audit-photon target="photon_servers": && _stig-report
    {{ ansible_playbook }} playbooks/linux/photon/stig_audit.yml -l {{ target }}

# Audit Photon with custom inventory
stig-audit-photon-inv target inv: && _stig-report
    {{ ansible_playbook }} -i {{ inv }} playbooks/linux/photon/stig_audit.yml -l {{ target }}

# =============================================================================
# STIG Remediation (MUTATING — changes systems)
# =============================================================================

# --- ESXi Hardening ---

# Harden ESXi hosts (accepts host, group, or vCenter as target)
stig-harden-esxi target:
    {{ ansible_playbook }} playbooks/vmware/esxi/stig_remediate.yml -l {{ target }}

# Harden all ESXi hosts at a site
stig-harden-esxi-site site:
    {{ ansible_playbook }} playbooks/vmware/esxi/stig_remediate.yml \
        -l vcsa-{{ site }}

# Harden all ESXi hosts at a site with custom inventory
stig-harden-esxi-site-inv site inv:
    {{ ansible_playbook }} -i {{ inv }} playbooks/vmware/esxi/stig_remediate.yml \
        -l vcsa-{{ site }}

# --- VM Hardening ---

# Harden a single VM
stig-harden-vm vcenter vm_name:
    {{ ansible_playbook }} playbooks/vmware/vm/stig_remediate.yml \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# --- VCSA Hardening ---

# Harden VCSA (MUTATING)
stig-remediate-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vmware/vcsa/stig_remediate.yml -l {{ target }}

# Harden VCSA for a single site (MUTATING)
stig-remediate-vcsa-site site:
    {{ vcsa_playbook }} playbooks/vmware/vcsa/stig_remediate.yml -l vcsa-{{ site }}

# --- Photon Hardening ---

# Harden Photon servers (MUTATING)
stig-remediate-photon target="photon_servers":
    {{ ansible_playbook }} playbooks/linux/photon/stig_remediate.yml -l {{ target }}

# --- Interactive Apply ---

# Apply ESXi STIG rules interactively from a prior audit artifact (MUTATING)
stig-apply-esxi artifact vcenter esxi_host:
    {{ ncs_reporter }} stig-apply {{ artifact }} --limit {{ vcenter }} --esxi-host {{ esxi_host }}

# =============================================================================
# Password Rotation (MUTATING)
# =============================================================================

# Rotate a local user password on Ubuntu servers
rotate-password-ubuntu target="ubuntu_servers" user="admin":
    {{ ansible_playbook }} playbooks/linux/ubuntu/rotate_password.yml -l {{ target }} -e 'rotate_user={{ user }}'

# Rotate a local user password on ESXi hosts via vCenter
rotate-password-esxi vcenter +hosts:
    {{ ansible_playbook }} playbooks/vmware/esxi/rotate_password.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Rotate the root password on VCSA appliances
rotate-password-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vmware/vcsa/rotate_password.yml -l {{ target }}

# Rotate a local user password on Photon OS servers
rotate-password-photon target="photon_servers" user="root":
    {{ ansible_playbook }} playbooks/linux/photon/rotate_password.yml -l {{ target }} -e 'rotate_user={{ user }}'

# --- Password Status (read-only) ---

# Show password aging and account status on Ubuntu servers
password-status-ubuntu target="ubuntu_servers" user="root":
    {{ ansible_playbook }} playbooks/linux/ubuntu/password_status.yml -l {{ target }} -e 'rotate_user={{ user }}'

# Show local user accounts and password policy on ESXi hosts
password-status-esxi vcenter +hosts:
    {{ ansible_playbook }} playbooks/vmware/esxi/password_status.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Show password aging and account status on VCSA appliances
password-status-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vmware/vcsa/password_status.yml -l {{ target }}

# Show password aging and account status on Photon OS servers
password-status-photon target="photon_servers" user="root":
    {{ ansible_playbook }} playbooks/linux/photon/password_status.yml -l {{ target }} -e 'rotate_user={{ user }}'

# =============================================================================
# Reporting
# =============================================================================

# Refresh ESXi host inventory from all vCenters
refresh-esxi-inventory:
    {{ ansible_playbook }} playbooks/vmware/esxi/refresh_inventory.yml

# Dump inventory groups JSON to disk
dump-inventory:
    @mkdir -p {{ platform_root }}
    {{ ansible_inventory }} -i {{ inventory_file }} --list --output {{ groups_json }}
    @echo "✓ Inventory written to {{ groups_json }}"

# Generate all platform and site reports from collected artifacts
report:
    #!/usr/bin/env bash
    set -euo pipefail
    mkdir -p {{ platform_root }}
    if command -v {{ ansible_inventory }} >/dev/null 2>&1; then
        {{ ansible_inventory }} -i {{ inventory_file }} --list --output {{ groups_json }}
        echo "✓ Inventory written to {{ groups_json }}"
    fi
    {{ ncs_reporter }} all \
        --config-dir {{ reporter_config_dir }} \
        --platform-root {{ platform_root }} \
        --reports-root {{ reports_dir }}
    {{ python }} scripts/verify_report_artifacts.py --report-root {{ reports_dir }}

# Generate reports with custom paths
report-custom custom_platform_root custom_reports_root custom_groups:
    {{ ncs_reporter }} all \
        --config-dir {{ reporter_config_dir }} \
        --platform-root {{ custom_platform_root }} \
        --reports-root {{ custom_reports_root }} \
        --groups {{ custom_groups }}

# Generate STIG compliance reports only
report-stig input output="reports/stig":
    {{ ncs_reporter }} stig --input {{ input }} --output-dir {{ output }}

# Generate CKLB artifacts for STIG Viewer
report-cklb input output="reports/cklb":
    {{ ncs_reporter }} cklb --input {{ input }} --output-dir {{ output }}

# Verify generated artifacts are complete
verify-report-artifacts report_root=reports_dir:
    {{ python }} scripts/verify_report_artifacts.py --report-root {{ report_root }}

# Validate STIG callback emission coverage by target type
verify-stig-emission report_root=reports_dir required_targets="vcsa,esxi,vm,windows,ubuntu,photon" min_hosts="1":
    {{ python }} scripts/verify_report_artifacts.py \
        --report-root {{ report_root }} \
        --require-targets "{{ required_targets }}" \
        --min-hosts-per-target {{ min_hosts }}

# =============================================================================
# Simulation & Testing
# =============================================================================


# =============================================================================
# Maintenance
# =============================================================================

# Edit vault
vault-edit:
    {{ ansible_vault }} edit 'inventory/production/group_vars/all/vault.yaml' --vault-password-file {{ vaultpass }}

# View vault
vault-view:
    {{ ansible_vault }} view 'inventory/production/group_vars/all/vault.yaml' --vault-password-file {{ vaultpass }}

# Initialize the Samba report share (run once)
init-samba:
    {{ ansible_playbook }} playbooks/ncs/setup_samba.yml

# Clean up all temporary build/cache artifacts (including symlinked collections)
clean:
    rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage
    find . -path './.venv*' -prune -o \( -name '__pycache__' -type d -exec rm -rf {} + \) -o \( -name '*.pyc' -delete \) 2>/dev/null || true
    find collections/ansible_collections/internal -name '__pycache__' -type d -exec rm -rf {} + 2>/dev/null || true
    find . -type d -name ".artifacts" -exec rm -rf {} +

# Deep clean including venvs and vcsa collections
clean-all: clean
    rm -rf .venv .venv-vcsa collections_vcsa/ansible_collections/community

# =============================================================================
# Scheduling
# =============================================================================

# Apply playbook schedules (systemd timers) from schedules.yml
apply-schedules:
    {{ ansible_playbook }} playbooks/ncs/manage_schedules.yml

# Show status of all NCS scheduled timers
schedule-status:
    systemctl list-timers 'ncs-*' --no-pager

# Show recent log output for a scheduled playbook
schedule-log name:
    journalctl -u ncs-{{ name }}.service --no-pager -n 100

# Manually trigger a scheduled playbook immediately
schedule-run-now name:
    systemctl start ncs-{{ name }}.service
