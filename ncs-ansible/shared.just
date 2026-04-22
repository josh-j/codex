# Shared recipes imported by each internal.* collection sibling.
#
# Every recipe here assumes it runs from the invoker's own repo
# (the sibling working tree) — never reaches across to the monorepo.
# See ncs-ansible/Justfile for monorepo-wide recipes.

# Resolve tools from a sibling-local .venv if present, else PATH.
_ag     := if path_exists(justfile_directory() + "/.venv/bin/ansible-galaxy") == "true" { justfile_directory() + "/.venv/bin/ansible-galaxy" } else { "ansible-galaxy" }
_al     := if path_exists(justfile_directory() + "/.venv/bin/ansible-lint") == "true" { justfile_directory() + "/.venv/bin/ansible-lint" } else { "ansible-lint" }
_yl     := if path_exists(justfile_directory() + "/.venv/bin/yamllint") == "true" { justfile_directory() + "/.venv/bin/yamllint" } else { "yamllint" }
_ap     := if path_exists(justfile_directory() + "/.venv/bin/ansible-playbook") == "true" { justfile_directory() + "/.venv/bin/ansible-playbook" } else { "ansible-playbook" }

# Standard per-collection test harness locations — see tests/README.md.
_test_inv   := justfile_directory() + "/tests/inventory"
_test_vault := justfile_directory() + "/tests/.vault_pass"

# Parametrized test helpers. Each collection's Justfile declares:
#
#   test:       (_test_check "playbooks/ubuntu_collect.yml")
#   test-apply: (_test_apply "playbooks/ubuntu_collect.yml")
#
# _test_check runs the playbook in --check mode against tests/inventory;
# _test_apply drops --check for real execution against the lab.
_test_check playbook:
    {{_ap}} -i {{_test_inv}} --vault-password-file {{_test_vault}} --check {{playbook}}

_test_apply playbook:
    {{_ap}} -i {{_test_inv}} --vault-password-file {{_test_vault}} {{playbook}}

# Lint the collection's roles + playbooks against ansible-lint.
lint:
    {{_al}} roles/ playbooks/

# Lint all YAML in the collection with yamllint (if installed).
yamllint:
    {{_yl}} .

# Rebuild the collection tarball under dist/. Does not touch the
# monorepo's collections/vendor/ — use `just vendor-collections` in
# the monorepo for that step.
build:
    mkdir -p dist
    {{_ag}} collection build . --force --output-path dist

# Remove build artifacts.
clean:
    rm -rf dist .ansible
