#!/usr/bin/env bash
# ncs-framework container entrypoint.
#
# Validates the required /ncs/ bind-mounts are present, then execs `just`
# inside /opt/ncs-ansible with whatever args the operator passed:
#
#   docker run ... ncs/control-node audit-linux
#   -> ncs-entrypoint "audit-linux" -> cd /opt/ncs-ansible && just audit-linux
#
# Mount checks are skipped when no args are given, when the first arg is
# a flag (anything starting with `-`), or when NCS_SKIP_MOUNT_CHECK=1.
# The flag heuristic covers `just --list`, `--help`, `--version`, and any
# future read-only flags without hard-coding them.

set -eu

require_mount() {
    local path="$1" kind="$2" label="$3"
    if [[ "$kind" == dir && ! -d "$path" ]] || [[ "$kind" == file && ! -f "$path" ]]; then
        printf 'ncs-entrypoint: missing bind mount: %s (%s)\n' "$label" "$path" >&2
        printf '  hint: docker run -v <host>:%s ...\n' "$path" >&2
        exit 64
    fi
}

if [[ "${NCS_SKIP_MOUNT_CHECK:-0}" != "1" ]]; then
    case "${1:-}" in
        ""|-*) ;;   # no args or flag-only — skip checks
        *)
            require_mount /ncs/inventory dir  "inventory  -> /ncs/inventory"
            require_mount /ncs/vaultpass file "vaultpass  -> /ncs/vaultpass"
            require_mount /ncs/reports   dir  "reports    -> /ncs/reports"
            if [[ -z "$(ls -A /ncs/ssh 2>/dev/null || true)" ]]; then
                printf 'ncs-entrypoint: /ncs/ssh is empty — managed-node SSH auth may fail.\n' >&2
            fi
            ;;
    esac
fi

cd /opt/ncs-ansible
exec just "$@"
