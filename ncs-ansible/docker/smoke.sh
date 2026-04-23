#!/usr/bin/env bash
# Post-build smoke check — exercises both venvs, all internal.* collections,
# the VCSA community collections, the reporter CLI, and the entrypoint's
# `just --list` path. Exits 0 if all checks pass, 1 otherwise.

set -u

venv=/opt/ncs-ansible/.venv
vcsa=/opt/ncs-ansible/.venv-vcsa
fail=0

check() {
    local label="$1"; shift
    printf '→ %-30s ' "$label"
    if out=$("$@" 2>&1); then
        printf 'OK\n'
        printf '%s\n' "$out" | head -3 | sed 's/^/    /'
    else
        printf 'FAIL\n'
        printf '%s\n' "$out" | sed 's/^/    /'
        fail=$((fail + 1))
    fi
}

# `ansible-galaxy collection list` takes at most one positional arg, so list
# everything once per venv and assert each expected FQCN is present.
check_collections() {
    local label="$1" galaxy="$2"; shift 2
    printf '→ %-30s ' "$label"
    local list missing=()
    if ! list=$("$galaxy" collection list 2>&1); then
        printf 'FAIL\n'
        printf '%s\n' "$list" | sed 's/^/    /'
        fail=$((fail + 1))
        return
    fi
    local name
    for name in "$@"; do
        grep -qE "^${name}([[:space:]]|$)" <<<"$list" || missing+=("$name")
    done
    if ((${#missing[@]})); then
        printf 'FAIL (missing: %s)\n' "${missing[*]}"
        fail=$((fail + 1))
    else
        printf 'OK (%d found)\n' "$#"
    fi
}

check             "ansible (main)"      "$venv/bin/ansible" --version
check             "ansible (vcsa)"      "$vcsa/bin/ansible" --version
check             "ncs-reporter"        "$venv/bin/ncs-reporter" --help
check_collections "internal.* (main)"   "$venv/bin/ansible-galaxy" \
                  internal.core internal.vmware internal.linux internal.windows internal.aci
check_collections "community (vcsa)"    "$vcsa/bin/ansible-galaxy" \
                  community.vmware community.general vmware.vmware
check             "just --list"         just --list

if [ "$fail" -ne 0 ]; then
    printf '✗ %d smoke check(s) failed\n' "$fail" >&2
    exit 1
fi
printf '✓ all smoke checks passed\n'
