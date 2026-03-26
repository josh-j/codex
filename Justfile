# NCS (Network Control System) Root Justfile

set dotenv-load := true

# --- Variables ---
python           := if path_exists(".venv/bin/python3") == "true" { ".venv/bin/python3" } else { "python3" }
ansible_playbook := if path_exists(".venv/bin/ansible-playbook") == "true" { ".venv/bin/ansible-playbook" } else { "ansible-playbook" }
ansible_inventory := if path_exists(".venv/bin/ansible-inventory") == "true" { ".venv/bin/ansible-inventory" } else { "ansible-inventory" }
ansible_vault    := if path_exists(".venv/bin/ansible-vault") == "true" { ".venv/bin/ansible-vault" } else { "ansible-vault" }
ncs_reporter     := if path_exists(".venv/bin/ncs-reporter") == "true" { ".venv/bin/ncs-reporter" } else { "ncs-reporter" }
# VCSA SSH-based STIG requires ansible-core 2.15 + Python 3.7-compat collections
vcsa_playbook    := "ANSIBLE_CONFIG=ansible-vcsa.cfg " + (if path_exists(".venv-vcsa/bin/ansible-playbook") == "true" { ".venv-vcsa/bin/ansible-playbook" } else { ansible_playbook })
reporter_config_dir := "files/ncs_reporter_configs"
inventory_file   := "inventory/production/"
simulation_inventory_file := "inventory/simulation/hosts.yaml"
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
        .venv/bin/pip install -e ../ncs_reporter
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
    # Python 3.7-compatible community collections in separate path
    mkdir -p collections_vcsa/ansible_collections
    .venv-vcsa/bin/ansible-galaxy collection install \
        'community.general:>=8.0.0,<9.0.0' \
        'community.vmware:>=4.0.0,<5.0.0' \
        -p collections_vcsa --force
    # Symlink internal collections so both envs share them
    ln -sfn "$(pwd)/collections/ansible_collections/internal" \
        collections_vcsa/ansible_collections/internal
    [ -d "collections/ansible_collections/vmware" ] && \
        ln -sfn "$(pwd)/collections/ansible_collections/vmware" \
        collections_vcsa/ansible_collections/vmware || true
    echo "✓ VCSA venv ready"
    .venv-vcsa/bin/ansible --version | head -1

# Install Ansible collections (main venv)
setup-collections:
    #!/usr/bin/env bash
    set -euo pipefail
    echo "Installing collections for main venv..."
    ansible-galaxy collection install ansible.posix community.vmware community.general --force
    echo "✓ Main collections installed"
    # Verify internal collections are symlinked into vcsa path
    if [ -d "collections_vcsa/ansible_collections" ]; then
        ln -sfn "$(pwd)/collections/ansible_collections/internal" \
            collections_vcsa/ansible_collections/internal
        [ -d "collections/ansible_collections/vmware" ] && \
            ln -sfn "$(pwd)/collections/ansible_collections/vmware" \
            collections_vcsa/ansible_collections/vmware || true
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
    cd ncs_reporter && {{ python }} generate_schema.py

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
    {{ ansible_playbook }} playbooks/vmware/audit.yml -l {{ target }} -v

# Run VMware health audit for a single site
audit-vmware-site site:
    {{ ansible_playbook }} playbooks/vmware/audit.yml -l vcsa-{{ site }}

# Run ESXi health audit (all sites or limited)
audit-esxi target="vcsa":
    {{ ansible_playbook }} playbooks/esxi/audit.yml -l {{ target }} -v

# Run ESXi health audit for a single site
audit-esxi-site site:
    {{ ansible_playbook }} playbooks/esxi/audit.yml -l vcsa-{{ site }}

# Run VM workload audit (all sites or limited)
audit-vm target="vcsa":
    {{ ansible_playbook }} playbooks/vm/audit.yml -l {{ target }} -v

# Run VM workload audit for a single site
audit-vm-site site:
    {{ ansible_playbook }} playbooks/vm/audit.yml -l vcsa-{{ site }}

# Run Ubuntu audit
audit-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/ubuntu/audit.yml -l {{ target }}

# Run Ubuntu apt update + dist-upgrade
update-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/ubuntu/update.yml -l {{ target }}

# Run Ubuntu update (apply only, skip discover)
update-ubuntu-apply target="ubuntu_servers":
    {{ ansible_playbook }} playbooks/ubuntu/update_apply.yml -l {{ target }}

# Run Ubuntu discovery phase only
audit-ubuntu-discover:
    {{ ansible_playbook }} playbooks/ubuntu/discover.yml

# Run Windows audit
audit-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/audit.yml -l {{ target }}

# Run Windows update apply phase
update-windows:
    {{ ansible_playbook }} playbooks/windows/update.yml

# Run Windows health check
health-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/health.yml -l {{ target }}

# Run Windows cleanup
cleanup-windows target="windows_servers":
    {{ ansible_playbook }} playbooks/windows/cleanup.yml -l {{ target }}

# Run Windows post-patch audit phase
audit-windows-post-patch:
    {{ ansible_playbook }} playbooks/windows/post_patch_audit.yml

# Audit a specific Linux host
audit-linux-host hostname:
    {{ ansible_playbook }} playbooks/ubuntu/audit.yml -l {{ hostname }}

# Audit a specific Windows host
audit-windows-host hostname:
    {{ ansible_playbook }} playbooks/windows/audit.yml -l {{ hostname }}

# =============================================================================
# Windows Administration (targeted single-host actions)
# =============================================================================

# Run Windows health check on a target
windows-health target:
    {{ ansible_playbook }} playbooks/windows/health.yml -l {{ target }}

# Run Windows vulnerability scan on a target
windows-vuln-scan target:
    {{ ansible_playbook }} playbooks/windows/vuln_scan.yml -l {{ target }}

# Apply Windows registry fixes on a target
windows-registry-fix target:
    {{ ansible_playbook }} playbooks/windows/registry_fix.yml -l {{ target }}

# Install a Windows KB update on a target
windows-kb-install target:
    {{ ansible_playbook }} playbooks/windows/kb_install.yml -l {{ target }}

# Update software on a Windows target
windows-update-software target:
    {{ ansible_playbook }} playbooks/windows/update_software.yml -l {{ target }}

# Uninstall software from a Windows target
windows-uninstall-software target:
    {{ ansible_playbook }} playbooks/windows/uninstall_software.yml -l {{ target }}

# Run disk/temp cleanup on a Windows target
windows-cleanup target:
    {{ ansible_playbook }} playbooks/windows/cleanup.yml -l {{ target }}

# Run Windows Update on a target
windows-update target:
    {{ ansible_playbook }} playbooks/windows/windows_update.yml -l {{ target }}

# Manage a Windows service (action: start|stop|restart, name: service name)
windows-service target action name:
    {{ ansible_playbook }} playbooks/windows/service.yml -l {{ target }} -e 'service_action={{ action }} service_name={{ name }}'

# Manage a Windows scheduled task (action: create|delete|enable|disable, name: task name)
windows-scheduled-task target action name:
    {{ ansible_playbook }} playbooks/windows/scheduled_task.yml -l {{ target }} -e 'task_action={{ action }} task_name={{ name }}'

# Enable WinRM on a Windows target
windows-winrm-enable target:
    {{ ansible_playbook }} playbooks/windows/winrm_enable.yml -l {{ target }}

# Run remote operations on a Windows target (op: operation name)
windows-remote-ops target op:
    {{ ansible_playbook }} playbooks/windows/remote_ops.yml -l {{ target }} -e 'remote_op={{ op }}'

# Search Active Directory (type: user|group|computer, term: search term)
windows-ad-search type term:
    {{ ansible_playbook }} playbooks/windows/ad_search.yml -e 'ad_search_type={{ type }} ad_search_term={{ term }}'

# Install/configure OpenSSH on a Windows target
windows-openssh target:
    {{ ansible_playbook }} playbooks/windows/openssh.yml -l {{ target }}

# Bootstrap OpenSSH on Windows targets via WinRM (first-time setup)
windows-openssh-bootstrap target transport="kerberos":
    {{ ansible_playbook }} playbooks/windows/openssh.yml -l {{ target }} -e 'ansible_connection=winrm ansible_winrm_transport={{ transport }} ansible_port=5985'

# =============================================================================
# STIG Audits (read-only compliance checks)
# =============================================================================

# --- ESXi STIG ---

# Audit a single ESXi host
stig-audit-esxi vcenter host:
    {{ ansible_playbook }} playbooks/esxi/stig_audit.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": ["{{ host }}"]}'

# Audit all ESXi hosts at a site
stig-audit-esxi-site site:
   #!/usr/bin/env bash
    set -euo pipefail
    tmpfile=$(mktemp /tmp/ncs_esxi_site_XXXXXX.json)
    trap 'rm -f "$tmpfile"' EXIT
    {{ ansible_inventory }} -i {{ inventory_file }} --list | \
        {{ python }} -c 'import json,sys; d=json.load(sys.stdin); g="{{ site }}_esxi_hosts"; hosts=d.get(g,{}).get("hosts",[]); hosts or sys.exit("no hosts in group "+g); print(json.dumps({"esxi_stig_target_hosts":hosts}))' > "$tmpfile"
    {{ ansible_playbook }} playbooks/esxi/stig_audit.yml \
        -l vcsa-{{ site }} -e "@$tmpfile" -f 14

# Audit all ESXi hosts at a site with custom inventory
stig-audit-esxi-site-inv site inv:
    #!/usr/bin/env bash
    set -euo pipefail
    tmpfile=$(mktemp /tmp/ncs_esxi_site_XXXXXX.json)
    trap 'rm -f "$tmpfile"' EXIT
    {{ ansible_inventory }} -i {{ inv }} --list | \
        {{ python }} -c 'import json,sys; d=json.load(sys.stdin); g="{{ site }}_esxi_hosts"; hosts=d.get(g,{}).get("hosts",[]); hosts or sys.exit("no hosts in group "+g); print(json.dumps({"esxi_stig_target_hosts":hosts}))' > "$tmpfile"
    {{ ansible_playbook }} -i {{ inv }} playbooks/esxi/stig_audit.yml \
        -l vcsa-{{ site }} -e "@$tmpfile" -f 10

# --- VM STIG ---

# Audit a single VM
stig-audit-vm vcenter vm_name:
    {{ ansible_playbook }} playbooks/vm/stig_audit.yml \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# Audit all VMs at a site (auto-discovers from vCenter)
stig-audit-vm-site site:
    {{ ansible_playbook }} playbooks/vm/stig_audit.yml \
        -l vcsa-{{ site }} \
        -f 14

# --- VCSA Health ---

# Run VCSA health audit (all sites or limited)
audit-vcsa target="vcsa":
    {{ ansible_playbook }} playbooks/vcsa/audit.yml -l {{ target }} -v

# Run VCSA health audit for a single site
audit-vcsa-site site:
    {{ ansible_playbook }} playbooks/vcsa/audit.yml -l vcsa-{{ site }}

# --- VCSA STIG (requires .venv-vcsa for Python 3.7 managed nodes) ---

# Audit all VCSA components
stig-audit-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vcsa/stig_audit.yml -l {{ target }}

# Audit VCSA for a single site
stig-audit-vcsa-site site:
    {{ vcsa_playbook }} playbooks/vcsa/stig_audit.yml -l vcsa-{{ site }}

# Audit specific VCSA roles only (for incremental testing)
# Example: just stig-audit-vcsa-roles sdhm vami eam postgresql
stig-audit-vcsa-roles site +components:
    #!/usr/bin/env bash
    set -euo pipefail
    roles=$(echo "{{ components }}" | tr ' ' '\n' | sed 's/^vcsa_//' | sed 's/^/internal.vmware.vcsa_/' | jq -R . | jq -s '{"vcsa_stig_roles": .}')
    {{ vcsa_playbook }} playbooks/vcsa/stig_audit.yml \
        -l vcsa-{{ site }} \
        -e "$roles"

# Audit VCSA with custom inventory
stig-audit-vcsa-inv target inv:
    {{ vcsa_playbook }} -i {{ inv }} playbooks/vcsa/stig_audit.yml -l {{ target }}

# --- Photon STIG ---

# Audit Photon OS servers
stig-audit-photon target="photon_servers":
    {{ ansible_playbook }} playbooks/photon/stig_audit.yml -l {{ target }}

# Audit Photon with custom inventory
stig-audit-photon-inv target inv:
    {{ ansible_playbook }} -i {{ inv }} playbooks/photon/stig_audit.yml -l {{ target }}

# =============================================================================
# STIG Remediation (MUTATING — changes systems)
# =============================================================================

# --- ESXi Hardening ---

# Harden a single ESXi host
stig-harden-esxi vcenter host:
    {{ ansible_playbook }} playbooks/esxi/stig_remediate.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": ["{{ host }}"]}'

# Harden all ESXi hosts at a site
stig-harden-esxi-site site:
    #!/usr/bin/env bash
    set -euo pipefail
    tmpfile=$(mktemp /tmp/ncs_esxi_site_XXXXXX.json)
    trap 'rm -f "$tmpfile"' EXIT
    {{ ansible_inventory }} -i {{ inventory_file }} --list | \
        {{ python }} -c 'import json,sys; d=json.load(sys.stdin); g="{{ site }}_esxi_hosts"; hosts=d.get(g,{}).get("hosts",[]); hosts or sys.exit("no hosts in group "+g); print(json.dumps({"esxi_stig_target_hosts":hosts}))' > "$tmpfile"
    {{ ansible_playbook }} playbooks/esxi/stig_remediate.yml \
        -l vcsa-{{ site }} -e "@$tmpfile"

# Harden all ESXi hosts at a site with custom inventory
stig-harden-esxi-site-inv site inv:
    #!/usr/bin/env bash
    set -euo pipefail
    tmpfile=$(mktemp /tmp/ncs_esxi_site_XXXXXX.json)
    trap 'rm -f "$tmpfile"' EXIT
    {{ ansible_inventory }} -i {{ inv }} --list | \
        {{ python }} -c 'import json,sys; d=json.load(sys.stdin); g="{{ site }}_esxi_hosts"; hosts=d.get(g,{}).get("hosts",[]); hosts or sys.exit("no hosts in group "+g); print(json.dumps({"esxi_stig_target_hosts":hosts}))' > "$tmpfile"
    {{ ansible_playbook }} -i {{ inv }} playbooks/esxi/stig_remediate.yml \
        -l vcsa-{{ site }} -e "@$tmpfile"

# --- VM Hardening ---

# Harden a single VM
stig-harden-vm vcenter vm_name:
    {{ ansible_playbook }} playbooks/vm/stig_remediate.yml \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# --- VCSA Hardening ---

# Harden VCSA (MUTATING)
stig-remediate-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vcsa/stig_remediate.yml -l {{ target }}

# Harden VCSA for a single site (MUTATING)
stig-remediate-vcsa-site site:
    {{ vcsa_playbook }} playbooks/vcsa/stig_remediate.yml -l vcsa-{{ site }}

# --- Photon Hardening ---

# Harden Photon servers (MUTATING)
stig-remediate-photon target="photon_servers":
    {{ ansible_playbook }} playbooks/photon/stig_remediate.yml -l {{ target }}

# --- Interactive Apply ---

# Apply ESXi STIG rules interactively from a prior audit artifact (MUTATING)
stig-apply-esxi artifact vcenter esxi_host:
    {{ ncs_reporter }} stig-apply {{ artifact }} --limit {{ vcenter }} --esxi-host {{ esxi_host }}

# =============================================================================
# Password Rotation (MUTATING)
# =============================================================================

# Rotate a local user password on Ubuntu servers
rotate-password-ubuntu target="ubuntu_servers" user="admin":
    {{ ansible_playbook }} playbooks/ubuntu/rotate_password.yml -l {{ target }} -e 'rotate_user={{ user }}'

# Rotate a local user password on ESXi hosts via vCenter
rotate-password-esxi vcenter +hosts:
    {{ ansible_playbook }} playbooks/esxi/rotate_password.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Rotate the root password on VCSA appliances
rotate-password-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vcsa/rotate_password.yml -l {{ target }}

# Rotate a local user password on Photon OS servers
rotate-password-photon target="photon_servers" user="root":
    {{ ansible_playbook }} playbooks/photon/rotate_password.yml -l {{ target }} -e 'rotate_user={{ user }}'

# --- Password Status (read-only) ---

# Show password aging and account status on Ubuntu servers
password-status-ubuntu target="ubuntu_servers" user="root":
    {{ ansible_playbook }} playbooks/ubuntu/password_status.yml -l {{ target }} -e 'rotate_user={{ user }}'

# Show local user accounts and password policy on ESXi hosts
password-status-esxi vcenter +hosts:
    {{ ansible_playbook }} playbooks/esxi/password_status.yml \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Show password aging and account status on VCSA appliances
password-status-vcsa target="vcsa":
    {{ vcsa_playbook }} playbooks/vcsa/password_status.yml -l {{ target }}

# Show password aging and account status on Photon OS servers
password-status-photon target="photon_servers" user="root":
    {{ ansible_playbook }} playbooks/photon/password_status.yml -l {{ target }} -e 'rotate_user={{ user }}'

# =============================================================================
# Reporting
# =============================================================================

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
        {{ ncs_reporter }} all \
            --config-dir {{ reporter_config_dir }} \
            --platform-root {{ platform_root }} \
            --reports-root {{ reports_dir }} \
            --groups {{ groups_json }}
    else
        echo "ansible-inventory not found, running report without --groups"
        {{ ncs_reporter }} all \
            --config-dir {{ reporter_config_dir }} \
            --platform-root {{ platform_root }} \
            --reports-root {{ reports_dir }}
    fi
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

# Build and validate a full deterministic production STIG simulation run
simulate-production-stig-run out_root="tests/reports/mock_production_run":
    {{ python }} scripts/generate_mock_production_stig_run.py \
        --inventory {{ inventory_file }} \
        --out-root {{ out_root }}
    {{ ncs_reporter }} all \
        --config-dir {{ reporter_config_dir }} \
        --platform-root {{ out_root }}/platform \
        --reports-root {{ out_root }} \
        --groups {{ out_root }}/platform/inventory_groups.json
    {{ python }} scripts/verify_report_artifacts.py --report-root {{ out_root }}
    {{ python }} scripts/verify_report_artifacts.py \
        --report-root {{ out_root }} \
        --require-targets "vcsa,esxi,vm,windows,ubuntu,photon,vami,eam,lookup_svc,perfcharts,vcsa_photon_os,postgresql,rhttpproxy,sts,ui" \
        --min-hosts-per-target 1

# Build and validate a production simulation with Ansible-driven artifact emission
simulate-production-ansible-run out_root="tests/reports/mock_production_ansible_run":
    #!/usr/bin/env bash
    set -euo pipefail
    rm -rf "{{ out_root }}/platform" "{{ out_root }}/cklb" "{{ out_root }}/site_health_report.html" "{{ out_root }}/stig_fleet_report.html" "{{ out_root }}/search_index.js"
    mkdir -p "{{ out_root }}/_fixtures" "{{ out_root }}"
    {{ python }} scripts/generate_mock_production_stig_run.py \
        --inventory {{ inventory_file }} \
        --out-root "{{ out_root }}/_fixtures"
    fixture_root="{{ out_root }}/_fixtures"
    case "$fixture_root" in /*) ;; *) fixture_root="$(pwd)/$fixture_root";; esac
    {{ python }} scripts/replay_mock_artifacts_via_ansible.py \
        --inventory {{ inventory_file }} \
        --fixture-root "{{ out_root }}/_fixtures" \
        --out-root "{{ out_root }}" \
        --ansible-playbook {{ ansible_playbook }}
    mkdir -p "{{ out_root }}/platform"
    cp "{{ out_root }}/_fixtures/platform/inventory_groups.json" "{{ out_root }}/platform/inventory_groups.json"
    {{ ncs_reporter }} all \
        --config-dir {{ reporter_config_dir }} \
        --platform-root {{ out_root }}/platform \
        --reports-root {{ out_root }} \
        --groups {{ out_root }}/platform/inventory_groups.json
    {{ python }} scripts/verify_report_artifacts.py --report-root {{ out_root }}
    {{ python }} scripts/verify_report_artifacts.py \
        --report-root {{ out_root }} \
        --require-targets "vcsa,esxi,vm,windows,ubuntu,photon,vami,eam,lookup_svc,perfcharts,vcsa_photon_os,postgresql,rhttpproxy,sts,ui" \
        --min-hosts-per-target 1

# Run VMware audit in simulation mode
simulate-vmware-playbook out_root="tests/reports/simulated_playbook_run":
    #!/usr/bin/env bash
    set -euo pipefail
    {{ python }} scripts/generate_mock_production_stig_run.py \
        --inventory {{ inventory_file }} \
        --out-root {{ out_root }}
    fixture_root="{{ out_root }}"
    case "$fixture_root" in /*) ;; *) fixture_root="$(pwd)/$fixture_root";; esac
    {{ ansible_playbook }} -i {{ simulation_inventory_file }} playbooks/vmware/audit.yml \
        -e "ncs_report_directory={{ out_root }}" \
        -e "simulation_mode=true" \
        -e "simulation_vcsa_fixture_root=$fixture_root/platform/vmware/vcenter/vcsa"
    {{ ncs_reporter }} all \
        --config-dir {{ reporter_config_dir }} \
        --platform-root {{ out_root }}/platform \
        --reports-root {{ out_root }} \
        --groups {{ out_root }}/platform/inventory_groups.json
    {{ python }} scripts/verify_report_artifacts.py --report-root {{ out_root }}

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
    {{ ansible_playbook }} playbooks/infra/setup_samba.yml

# Clean up all temporary build/cache artifacts
clean:
    rm -rf .mypy_cache .ruff_cache .pytest_cache .coverage
    find . -type d -name "__pycache__" -exec rm -rf {} +
    find . -type d -name ".artifacts" -exec rm -rf {} +

# Deep clean including venvs and vcsa collections
clean-all: clean
    rm -rf .venv .venv-vcsa collections_vcsa/ansible_collections/community
