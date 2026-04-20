# NCS (Non-Core Services) Root Justfile

set dotenv-load := true
# `mod?` below is still flagged unstable in some just releases; opt in here
# so `just setup-all` doesn't require a `--unstable` flag on every call.
set unstable := true

# Ensure ncs_collector callback can find platform configs
export NCS_REPO_ROOT := justfile_directory()

# Expose ncs-console's own Justfile as `just console::<recipe>`.
# Optional mount: silently no-ops on hosts without the subtree or
# without PowerShell installed.
mod? console 'ncs-console'

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
# Complete environment setup (both venvs + all collections + SMB share)
setup-all: setup-main-venv setup-vcsa-venv setup-collections install-collections setup-samba
    @echo "✓ All environments ready"

# Provision the SMB share used by ncs-console to fetch reports
setup-samba:
    #!/usr/bin/env bash
    set -euo pipefail
    if [ ! -f ".vaultpass" ]; then
        echo "⚠ .vaultpass missing — skipping SMB setup." >&2
        echo "  Create it (or populate vault_samba_user_password) then run: just setup-samba" >&2
        exit 0
    fi
    {{ ansible_playbook }} playbooks/core/setup_samba.yml --ask-become-pass
    echo "✓ SMB share 'reports' ready at //localhost/reports (user: ansible)"
    echo "  ncs-console defaults already match — enter the SshHost and SMB password to connect."

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
        .venv/bin/pip install ansible-core pyvmomi pykerberos requests
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
    .venv-vcsa/bin/pip install 'ansible-core>=2.15,<2.16' pyvmomi pykerberos requests
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

# Build a release tarball for one internal collection from its sibling repo.
# Usage: just build-collection core     (outputs dist/internal-core-<ver>.tar.gz)
build-collection name:
    #!/usr/bin/env bash
    set -euo pipefail
    src="../ncs-ansible-{{ name }}"
    [ -d "$src" ] || { echo "sibling repo not found: $src" >&2; exit 1; }
    mkdir -p dist
    .venv/bin/ansible-galaxy collection build "$src" --force --output-path dist
    echo "✓ built dist/internal-{{ name }}-<version>.tar.gz"

# Build tarballs for every internal collection.
build-collections-all: (build-collection "core") (build-collection "vmware") (build-collection "linux") (build-collection "windows") (build-collection "aci")
    @echo "✓ all collections built under dist/"

# Materialize the four internal.* collections as sibling working trees
# at ../ncs-ansible-<col>/. For each tarball in collections/vendor/,
# extract the contents and rsync them into the sibling dir (preserving
# any existing .git). If the sibling has no .git yet, initialize a git
# repo with an initial commit and a v<version> tag from galaxy.yml.
#
# Use this on a fresh clone to bootstrap the four sibling repos without
# access to the dev machine where they originated, or to refresh an
# existing set of siblings against the currently-vendored tarballs.
#
# After placement each sibling is an independent repo — add remotes and
# push to whatever alternative git host you want.
place-collection-siblings:
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    tarballs=(collections/vendor/internal-*.tar.gz)
    if [ ${#tarballs[@]} -eq 0 ]; then
        echo "no tarballs under collections/vendor/; run 'just vendor-collections' first" >&2
        exit 1
    fi
    for tarball in "${tarballs[@]}"; do
        col=$(basename "$tarball" | sed -E 's/^internal-([a-z_]+)-[0-9].*/\1/')
        dest="../ncs-ansible-${col}"
        tmp=$(mktemp -d)
        trap 'rm -rf "$tmp"' EXIT
        .venv/bin/python scripts/extract_collection_tarball.py "$tarball" "$tmp/src"
        mkdir -p "$dest"
        rsync -a --delete --exclude='.git' "$tmp/src"/ "$dest"/
        rm -rf "$tmp"
        trap - EXIT
        if [ ! -d "$dest/.git" ]; then
            version=$(sed -nE 's/^version:[[:space:]]*([^[:space:]]+).*/\1/p' "$dest/galaxy.yml" | head -1)
            (cd "$dest"
                git init --quiet --initial-branch=main
                git add -A
                git commit --quiet -m "Initial placement from $(basename "$tarball")"
                if [ -n "$version" ]; then
                    git tag "v${version}"
                fi
            )
            echo "✓ $dest initialized from $(basename "$tarball") (v${version})"
        else
            echo "✓ $dest refreshed from $(basename "$tarball") — .git preserved; run 'git status' to review drift"
        fi
    done
    echo ""
    echo "Next: cd into each ../ncs-ansible-<col>, review changes, and"
    echo "      git remote add <name> <url> && git push <name> --all --follow-tags"
    echo "      to publish to an alternative repo."

# Scaffold a new sibling collection repo from
# ncs-ansible-collection-template/. Creates ../ncs-ansible-<name>/,
# replaces the __COLLECTION_NAME__ placeholder, initializes git, and
# cuts an initial commit. Fails if the target already exists.
#
# Usage: just new-collection storage
new-collection name:
    #!/usr/bin/env bash
    set -euo pipefail
    dest="../ncs-ansible-{{ name }}"
    if [ -e "$dest" ]; then
        echo "$dest already exists; refusing to overwrite." >&2
        exit 1
    fi
    cp -r ncs-ansible-collection-template "$dest"
    # Substitute placeholders across every text file in the new repo.
    find "$dest" -type f ! -name '*.tar.gz' -print0 \
        | xargs -0 sed -i "s/__COLLECTION_NAME__/{{ name }}/g"
    # Strip the roles/ and playbooks/ .gitkeep sentinels once the
    # operator is ready to add real content — they're fine to leave
    # in place for now so empty dirs survive the initial commit.
    cd "$dest"
    git init --quiet --initial-branch=main
    git add -A
    git commit --quiet -m "Initial scaffold: internal.{{ name }}"
    git tag v0.1.0
    cd - >/dev/null
    echo "✓ Scaffolded $dest (tagged v0.1.0)."
    echo "  Next steps:"
    echo "    1. cd $dest && edit galaxy.yml description + populate roles/playbooks"
    echo "    2. back in this repo: just vendor-collections"
    echo "    3. add the new tarball to requirements.yml + commit"

# Rebuild every collection tarball and stage it under collections/vendor/
# (the committed location requirements.yml Mode A points at). Run this
# after a `just release-collection` so a fresh ncs-ansible `git pull`
# carries the new version to every consumer machine.
vendor-collections: build-collections-all
    #!/usr/bin/env bash
    set -euo pipefail
    shopt -s nullglob
    mkdir -p collections/vendor
    # Drop stale tarballs so a version bump doesn't leave both the old
    # and the new file side by side — each collection should ship at
    # exactly one version per vendor snapshot.
    rm -f collections/vendor/internal-*.tar.gz
    tarballs=(dist/internal-*.tar.gz)
    if [ ${#tarballs[@]} -eq 0 ]; then
        echo "no built tarballs under dist/; build-collections-all failed?" >&2
        exit 1
    fi
    for f in "${tarballs[@]}"; do
        cp -f "$f" collections/vendor/
    done
    echo "✓ collections/vendor/ refreshed:"
    ls -1 collections/vendor/

# Install every internal.* collection from the requirements.yml manifest,
# then regenerate the fleet-level site_<verb>_only.yml orchestrators so
# the list of imported collections stays in lockstep with what's installed.
install-collections:
    #!/usr/bin/env bash
    set -euo pipefail
    .venv/bin/ansible-galaxy collection install -r requirements.yml \
        --collections-path collections/ --force
    echo "✓ collections installed from requirements.yml"
    {{ python }} scripts/regenerate_site_playbooks.py

# Rebuild the fleet-level site_<verb>_only.yml orchestrators from whatever
# internal.* collections are currently installed under collections/. Useful
# when you just added or removed a sibling without running a full install.
regenerate-site-playbooks:
    {{ python }} scripts/regenerate_site_playbooks.py

# Verify every FQCN playbook referenced in ncs-reporter configs resolves
# against the currently-installed collections. Fails non-zero on drift.
verify-fqcn-contract:
    #!/usr/bin/env bash
    set -euo pipefail
    fqcns=$(.venv/bin/python scripts/verify_fqcn_contract.py)
    if [ -z "$fqcns" ]; then
        echo "no FQCN references found in ncs-reporter/src/ncs_reporter/configs/"
        exit 0
    fi
    fail=0
    while read -r fqcn; do
        if .venv/bin/ansible-playbook --syntax-check -i inventory/production "$fqcn" >/dev/null 2>&1; then
            echo "✓ $fqcn"
        else
            echo "✗ $fqcn — referenced in reporter configs but unresolvable" >&2
            fail=1
        fi
    done <<< "$fqcns"
    exit $fail

# Run ansible-lint against one collection's sibling repo.
# Usage: just lint-collection vmware
lint-collection name:
    #!/usr/bin/env bash
    set -euo pipefail
    src="../ncs-ansible-{{ name }}"
    [ -d "$src" ] || { echo "sibling repo not found: $src" >&2; exit 1; }
    if ! .venv/bin/python -c "import ansiblelint" 2>/dev/null; then
        .venv/bin/pip install ansible-lint >/dev/null
    fi
    .venv/bin/ansible-lint "$src"

# Cut a release of one collection. Non-interactive; the `message` becomes
# the CHANGELOG entry for this version. Bumps galaxy.yml, prepends
# CHANGELOG, commits, tags `v<version>`, and rebuilds the tarball.
#
# Usage:
#   just release-collection vmware 1.2.0 "Fix esxi STIG rule 42"
release-collection name version message:
    #!/usr/bin/env bash
    set -euo pipefail
    src="../ncs-ansible-{{ name }}"
    [ -d "$src" ] || { echo "sibling repo not found: $src" >&2; exit 1; }
    cd "$src"
    if ! git diff --quiet || ! git diff --cached --quiet; then
        echo "sibling repo has uncommitted changes; commit or stash first." >&2
        exit 1
    fi
    if git rev-parse --verify "refs/tags/v{{ version }}" >/dev/null 2>&1; then
        echo "tag v{{ version }} already exists in $src" >&2
        exit 1
    fi
    current=$(sed -nE 's/^version:[[:space:]]*([^[:space:]]+).*/\1/p' galaxy.yml | head -1)
    echo "Releasing internal.{{ name }} ${current} → {{ version }}"
    sed -i -E "s/^(version:[[:space:]]*).*/\1{{ version }}/" galaxy.yml
    today=$(date -u +%Y-%m-%d)
    if [ ! -s CHANGELOG.md ]; then
        printf '# Changelog — internal.%s\n\n' "{{ name }}" > CHANGELOG.md
    fi
    tmp=$(mktemp)
    {
        head -1 CHANGELOG.md
        printf '\n## %s — %s\n\n- %s\n\n' "{{ version }}" "$today" "{{ message }}"
        tail -n +2 CHANGELOG.md
    } > "$tmp"
    mv "$tmp" CHANGELOG.md
    git add galaxy.yml CHANGELOG.md
    git commit -m "Release v{{ version }}: {{ message }}"
    git tag "v{{ version }}"
    cd - >/dev/null
    just build-collection {{ name }}
    echo "✓ internal.{{ name }} v{{ version }} released; dist/internal-{{ name }}-{{ version }}.tar.gz"
    echo "  Next: bump internal.{{ name }} in ncs-ansible/requirements.yml, then 'just install-collections'"

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

# Run VMware health audit (all sites or limited)
audit-vmware target="vcsa":
    {{ ansible_playbook }} internal.vmware.collect -l {{ target }} -v

# Run VMware health audit for a single site
audit-vmware-site site:
    {{ ansible_playbook }} internal.vmware.collect -l vcsa-{{ site }}

# Run ESXi health audit (all sites or limited)
audit-esxi target="vcsa":
    {{ ansible_playbook }} internal.vmware.esxi_collect -l {{ target }} -v

# Run ESXi health audit for a single site
audit-esxi-site site:
    {{ ansible_playbook }} internal.vmware.esxi_collect -l vcsa-{{ site }}

# Run VM workload audit (all sites or limited)
audit-vm target="vcsa":
    {{ ansible_playbook }} internal.vmware.vm_collect -l {{ target }} -v

# Run VM workload audit for a single site
audit-vm-site site:
    {{ ansible_playbook }} internal.vmware.vm_collect -l vcsa-{{ site }}

# Run Ubuntu audit
audit-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} internal.linux.ubuntu_collect -l {{ target }}

# Run Ubuntu apt update + dist-upgrade
update-ubuntu target="ubuntu_servers":
    {{ ansible_playbook }} internal.linux.ubuntu_update -l {{ target }}

# Run Ubuntu update (apply only, skip discover)
update-ubuntu-apply target="ubuntu_servers":
    {{ ansible_playbook }} internal.linux.ubuntu_update_apply -l {{ target }}

# Run Ubuntu discovery phase only
audit-ubuntu-discover:
    {{ ansible_playbook }} internal.linux.ubuntu_collect

# Run Windows audit
audit-windows target="windows_servers":
    {{ ansible_playbook }} internal.windows.server_collect -l {{ target }}

# Run Windows update apply phase
update-windows:
    {{ ansible_playbook }} internal.windows.server_patch

# Run Windows health check
health-windows target="windows_servers":
    {{ ansible_playbook }} internal.windows.server_health -l {{ target }}

# Run Windows cleanup
cleanup-windows target="windows_servers":
    {{ ansible_playbook }} internal.windows.server_cleanup -l {{ target }}

# Run Windows post-patch audit phase
audit-windows-post-patch:
    {{ ansible_playbook }} internal.windows.server_post_patch_audit

# Audit a specific Linux host
audit-linux-host hostname:
    {{ ansible_playbook }} internal.linux.ubuntu_collect -l {{ hostname }}

# Audit a specific Windows host
audit-windows-host hostname:
    {{ ansible_playbook }} internal.windows.server_collect -l {{ hostname }}

# =============================================================================
# Windows Administration (targeted single-host actions)
# =============================================================================

# Run Windows health check on a target
windows-health target:
    {{ ansible_playbook }} internal.windows.server_health -l {{ target }}

# Run Windows vulnerability scan on a target
windows-vuln-scan target:
    {{ ansible_playbook }} internal.windows.server_vuln_scan -l {{ target }}

# Apply Windows registry fixes on a target
windows-registry-fix target:
    {{ ansible_playbook }} internal.windows.server_registry_fix -l {{ target }}

# Install a Windows KB update on a target
windows-kb-install target:
    {{ ansible_playbook }} internal.windows.server_kb_install -l {{ target }}

# Update software on a Windows target
windows-update-software target:
    {{ ansible_playbook }} internal.windows.server_update_software -l {{ target }}

# Uninstall software from a Windows target
windows-uninstall-software target:
    {{ ansible_playbook }} internal.windows.server_uninstall_software -l {{ target }}

# Run disk/temp cleanup on a Windows target
windows-cleanup target:
    {{ ansible_playbook }} internal.windows.server_cleanup -l {{ target }}

# Run Windows Update on a target
windows-update target:
    {{ ansible_playbook }} internal.windows.server_windows_update -l {{ target }}

# Manage a Windows service (action: start|stop|restart, name: service name)
windows-service target action name:
    {{ ansible_playbook }} internal.windows.server_service -l {{ target }} -e 'service_action={{ action }} service_name={{ name }}'

# Manage a Windows scheduled task (action: create|delete|enable|disable, name: task name)
windows-scheduled-task target action name:
    {{ ansible_playbook }} internal.windows.server_scheduled_task -l {{ target }} -e 'task_action={{ action }} task_name={{ name }}'

# Enable WinRM on a Windows target
windows-winrm-enable target:
    {{ ansible_playbook }} internal.windows.server_winrm_enable -l {{ target }}

# Run remote operations on a Windows target (op: operation name)
windows-remote-ops target op:
    {{ ansible_playbook }} internal.windows.server_remote_ops -l {{ target }} -e 'remote_op={{ op }}'

# Search Active Directory (type: user|group|computer, term: search term)
windows-ad-search type term:
    {{ ansible_playbook }} internal.windows.server_ad_search -e 'ad_search_type={{ type }} ad_search_term={{ term }}'

# Install/configure OpenSSH on a Windows target
windows-openssh target:
    {{ ansible_playbook }} internal.windows.server_openssh -l {{ target }}

# Bootstrap OpenSSH on Windows targets via WinRM (first-time setup)
windows-openssh-bootstrap target transport="kerberos":
    {{ ansible_playbook }} internal.windows.server_openssh -l {{ target }} -e 'ansible_connection=winrm ansible_winrm_transport={{ transport }} ansible_port=5985'

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
    {{ ansible_playbook }} playbooks/core/generate_reports.yml
    echo "✓ Reports written to {{ reports_dir }}"

# --- ESXi STIG ---

# Audit ESXi hosts (accepts host, group, or vCenter as target)
stig-audit-esxi target: && _stig-report
    {{ ansible_playbook }} internal.vmware.esxi_stig_audit -l {{ target }}

# Audit all ESXi hosts at a site (auto-discovers from vCenter)
stig-audit-esxi-site site: && _stig-report
    {{ ansible_playbook }} internal.vmware.esxi_stig_audit \
        -l vcsa-{{ site }} -f 14

# Audit all ESXi hosts at a site with custom inventory
stig-audit-esxi-site-inv site inv: && _stig-report
    {{ ansible_playbook }} -i {{ inv }} internal.vmware.esxi_stig_audit \
        -l vcsa-{{ site }} -f 10

# --- VM STIG ---

# Audit a single VM
stig-audit-vm vcenter vm_name: && _stig-report
    {{ ansible_playbook }} internal.vmware.vm_stig_audit \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# Audit all VMs at a site (auto-discovers from vCenter)
stig-audit-vm-site site: && _stig-report
    {{ ansible_playbook }} internal.vmware.vm_stig_audit \
        -l vcsa-{{ site }} \
        -f 14

# --- VCSA Health ---

# Run VCSA health audit (all sites or limited)
audit-vcsa target="vcsa":
    {{ ansible_playbook }} internal.vmware.vcsa_collect -l {{ target }} -v

# Run VCSA health audit for a single site
audit-vcsa-site site:
    {{ ansible_playbook }} internal.vmware.vcsa_collect -l vcsa-{{ site }}

# --- VCSA STIG (requires .venv-vcsa for Python 3.7 managed nodes) ---

# Audit all VCSA components
stig-audit-vcsa target="vcsa": && _stig-report
    {{ vcsa_playbook }} internal.vmware.vcsa_stig_audit -l {{ target }}

# Audit VCSA for a single site
stig-audit-vcsa-site site: && _stig-report
    {{ vcsa_playbook }} internal.vmware.vcsa_stig_audit -l vcsa-{{ site }}

# Audit specific VCSA roles only (for incremental testing)
# Example: just stig-audit-vcsa-roles sdhm vami eam postgresql
stig-audit-vcsa-roles site +components:
    #!/usr/bin/env bash
    set -euo pipefail
    roles=$(echo "{{ components }}" | tr ' ' '\n' | sed 's/^vcsa_//' | sed 's/^/internal.vmware.vcsa_/' | jq -R . | jq -s '{"vcsa_stig_roles": .}')
    {{ vcsa_playbook }} internal.vmware.vcsa_stig_audit \
        -l vcsa-{{ site }} \
        -e "$roles"
    just _stig-report

# Audit VCSA with custom inventory
stig-audit-vcsa-inv target inv: && _stig-report
    {{ vcsa_playbook }} -i {{ inv }} internal.vmware.vcsa_stig_audit -l {{ target }}

# --- Photon STIG ---

# Audit Photon OS servers
stig-audit-photon target="photon_servers": && _stig-report
    {{ ansible_playbook }} internal.linux.photon_stig_audit -l {{ target }}

# Audit Photon with custom inventory
stig-audit-photon-inv target inv: && _stig-report
    {{ ansible_playbook }} -i {{ inv }} internal.linux.photon_stig_audit -l {{ target }}

# =============================================================================
# STIG Remediation (MUTATING — changes systems)
# =============================================================================

# --- ESXi Hardening ---

# Harden ESXi hosts (accepts host, group, or vCenter as target)
stig-harden-esxi target:
    {{ ansible_playbook }} internal.vmware.esxi_stig_remediate -l {{ target }}

# Harden all ESXi hosts at a site
stig-harden-esxi-site site:
    {{ ansible_playbook }} internal.vmware.esxi_stig_remediate \
        -l vcsa-{{ site }}

# Harden all ESXi hosts at a site with custom inventory
stig-harden-esxi-site-inv site inv:
    {{ ansible_playbook }} -i {{ inv }} internal.vmware.esxi_stig_remediate \
        -l vcsa-{{ site }}

# --- VM Hardening ---

# Harden a single VM
stig-harden-vm vcenter vm_name:
    {{ ansible_playbook }} internal.vmware.vm_stig_remediate \
        -l {{ vcenter }} \
        -e '{"vm_stig_target_vms": ["{{ vm_name }}"]}'

# --- VCSA Hardening ---

# Harden VCSA (MUTATING)
stig-remediate-vcsa target="vcsa":
    {{ vcsa_playbook }} internal.vmware.vcsa_stig_remediate -l {{ target }}

# Harden VCSA for a single site (MUTATING)
stig-remediate-vcsa-site site:
    {{ vcsa_playbook }} internal.vmware.vcsa_stig_remediate -l vcsa-{{ site }}

# --- Photon Hardening ---

# Harden Photon servers (MUTATING)
stig-remediate-photon target="photon_servers":
    {{ ansible_playbook }} internal.linux.photon_stig_remediate -l {{ target }}

# --- Interactive Apply ---

# Apply ESXi STIG rules interactively from a prior audit artifact (MUTATING)
stig-apply-esxi artifact vcenter esxi_host:
    {{ ncs_reporter }} stig-apply {{ artifact }} --limit {{ vcenter }} --esxi-host {{ esxi_host }}

# =============================================================================
# Password Rotation (MUTATING)
# =============================================================================

# Rotate a local user password on Ubuntu servers
rotate-password-ubuntu target="ubuntu_servers" user="admin":
    {{ ansible_playbook }} internal.linux.ubuntu_rotate_password -l {{ target }} -e 'rotate_user={{ user }}'

# Rotate a local user password on ESXi hosts via vCenter
rotate-password-esxi vcenter +hosts:
    {{ ansible_playbook }} internal.vmware.esxi_rotate_password \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Rotate the root password on VCSA appliances
rotate-password-vcsa target="vcsa":
    {{ vcsa_playbook }} internal.vmware.vcsa_rotate_password -l {{ target }}

# Rotate a local user password on Photon OS servers
rotate-password-photon target="photon_servers" user="root":
    {{ ansible_playbook }} internal.linux.photon_rotate_password -l {{ target }} -e 'rotate_user={{ user }}'

# --- Password Status (read-only) ---

# Show password aging and account status on Ubuntu servers
password-status-ubuntu target="ubuntu_servers" user="root":
    {{ ansible_playbook }} internal.linux.ubuntu_password_status -l {{ target }} -e 'rotate_user={{ user }}'

# Show local user accounts and password policy on ESXi hosts
password-status-esxi vcenter +hosts:
    {{ ansible_playbook }} internal.vmware.esxi_password_status \
        -l {{ vcenter }} \
        -e '{"esxi_stig_target_hosts": {{ hosts }}}'

# Show password aging and account status on VCSA appliances
password-status-vcsa target="vcsa":
    {{ vcsa_playbook }} internal.vmware.vcsa_password_status -l {{ target }}

# Show password aging and account status on Photon OS servers
password-status-photon target="photon_servers" user="root":
    {{ ansible_playbook }} internal.linux.photon_password_status -l {{ target }} -e 'rotate_user={{ user }}'

# =============================================================================
# Reporting
# =============================================================================

# Refresh ESXi host inventory from all vCenters
refresh-esxi-inventory:
    {{ ansible_playbook }} internal.vmware.esxi_refresh_inventory

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
    {{ ansible_playbook }} playbooks/core/setup_samba.yml

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
    {{ ansible_playbook }} playbooks/core/manage_schedules.yml

# Show status of all NCS scheduled timers
schedule-status:
    systemctl list-timers 'ncs-*' --no-pager

# Show recent log output for a scheduled playbook (wrapper log + journal)
schedule-log name:
    @echo "=== /var/log/ncs-schedules/{{ name }}.log ==="
    @tail -n 100 /var/log/ncs-schedules/{{ name }}.log 2>/dev/null || echo "(no wrapper log yet)"
    @echo ""
    @echo "=== journalctl -u ncs-{{ name }}.service ==="
    journalctl -u ncs-{{ name }}.service --no-pager -n 100

# Manually trigger a scheduled playbook immediately
schedule-run-now name:
    systemctl start ncs-{{ name }}.service
