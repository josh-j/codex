# syntax=docker/dockerfile:1.7
#
# ncs-framework control-node image.
#
# Build context MUST be the umbrella repo root so the builder can see both
# ncs-ansible/ and each ncs-ansible-<name>/ sibling working tree:
#
#   docker build -f Dockerfile -t ncs/control-node:dev .
#
# Layer order is tuned for rebuild speed: the two venvs are materialized
# before any application source is copied, so edits under ncs-ansible/,
# ncs-reporter/, or ncs-ansible-<name>/ don't bust the venv layers.
# BuildKit cache mounts keep the uv download cache warm across builds.
#
# Runtime contract — operator bind-mounts:
#   /ncs/inventory   ->  Ansible inventory + group_vars/ + vaulted vault.yaml
#   /ncs/vaultpass   ->  ansible-vault password file (mode 0400)
#   /ncs/configs     ->  customer ncs_configs/ overrides (OPTIONAL)
#   /ncs/reports     ->  report output tree (read-write)
#   /ncs/ssh         ->  SSH keys / known_hosts for managed-node auth

ARG BASE_TAG=24.04
ARG UV_VERSION=0.5.11
ARG VCSA_PYTHON=3.11
# Shared install dir for uv-managed Python(s). Must be identical in both
# stages so venv interpreter symlinks resolve in the final image.
ARG UV_PYTHON_INSTALL_DIR=/opt/uv-python

# =============================================================================
# Stage 1: builder — materialize venvs, build collection tarballs + reporter wheel
# =============================================================================
FROM ubuntu:${BASE_TAG} AS builder

ARG UV_VERSION
ARG VCSA_PYTHON
ARG UV_PYTHON_INSTALL_DIR
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON_INSTALL_DIR=${UV_PYTHON_INSTALL_DIR} \
    UV_CACHE_DIR=/tmp/uv-cache \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PYTHONDONTWRITEBYTECODE=1

RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        build-essential pkg-config \
        libkrb5-dev libssl-dev libffi-dev \
        python3 python3-venv python3-dev \
        openssh-client rsync \
    && rm -rf /var/lib/apt/lists/*

RUN curl -LsSf "https://astral.sh/uv/${UV_VERSION}/install.sh" \
        | env UV_INSTALL_DIR=/usr/local/bin INSTALLER_NO_MODIFY_PATH=1 sh \
    && uv --version \
    && uv python install "${VCSA_PYTHON}"

# Venvs are created directly at their final path (/opt/ncs-ansible/.venv*)
# because uv bakes absolute paths into activate scripts and console-script
# shebangs — moving a venv post-creation breaks it.

# --- VCSA venv first (smallest, fewest deps). Dep list is shared with
# the host-side `just setup-vcsa-venv` recipe via requirements-vcsa.txt.
COPY ncs-ansible/requirements-vcsa.txt /tmp/requirements-vcsa.txt
RUN --mount=type=cache,target=/tmp/uv-cache,sharing=locked \
    uv venv --python "${VCSA_PYTHON}" /opt/ncs-ansible/.venv-vcsa \
    && VIRTUAL_ENV=/opt/ncs-ansible/.venv-vcsa uv pip install \
        -r /tmp/requirements-vcsa.txt

# --- Main venv. No application source has been copied yet, so edits under
# ncs-ansible/, ncs-reporter/, or the sibling trees don't invalidate this
# expensive layer.
RUN --mount=type=cache,target=/tmp/uv-cache,sharing=locked \
    uv venv --python 3.12 /opt/ncs-ansible/.venv \
    && VIRTUAL_ENV=/opt/ncs-ansible/.venv uv pip install \
        'ansible-core>=2.16' \
        pyvmomi requests pykerberos \
        'jinja2>=3.1.0' 'pyyaml>=6.0' 'click>=8.0' 'pydantic>=2.0' 'minify-html>=0.15.0'

# --- Sibling collection trees. Editing one only invalidates layers below.
COPY ncs-ansible-core/       /src/ncs-ansible-core/
COPY ncs-ansible-vmware/     /src/ncs-ansible-vmware/
COPY ncs-ansible-linux/      /src/ncs-ansible-linux/
COPY ncs-ansible-windows/    /src/ncs-ansible-windows/
COPY ncs-ansible-aci/        /src/ncs-ansible-aci/

RUN mkdir -p /build/collections \
    && for name in core vmware linux windows aci; do \
        /opt/ncs-ansible/.venv/bin/ansible-galaxy collection build \
            "/src/ncs-ansible-${name}" --force --output-path /build/collections; \
    done

COPY ncs-reporter/ /src/ncs-reporter/
RUN --mount=type=cache,target=/tmp/uv-cache,sharing=locked \
    mkdir -p /build/wheels \
    && uv build --wheel --sdist --out-dir /build/wheels /src/ncs-reporter \
    && VIRTUAL_ENV=/opt/ncs-ansible/.venv uv pip install --no-deps \
        /build/wheels/ncs_reporter-*.whl

# --- Orchestrator tree merges into /opt/ncs-ansible/ alongside the venvs.
# .dockerignore excludes .venv*/ from the build context so this COPY never
# clobbers the venvs created above.
COPY ncs-ansible/ /opt/ncs-ansible/

# Install internal.* collections — one call, glob-expanded tarball list.
RUN mkdir -p /opt/ncs-ansible/collections/ansible_collections \
    && /opt/ncs-ansible/.venv/bin/ansible-galaxy collection install \
        /build/collections/internal-*.tar.gz \
        -p /opt/ncs-ansible/collections --force

# VCSA collection set — pinned for ansible-core 2.15. Symlink internal.*
# from the main install so both envs share identical collection versions.
RUN cd /opt/ncs-ansible \
    && ANSIBLE_CONFIG=ansible-vcsa.cfg .venv-vcsa/bin/ansible-galaxy collection install \
        'community.general:>=8.0.0,<9.0.0' \
        'community.vmware:>=4.0.0,<5.0.0' \
        'vmware.vmware:<2.0.0' \
        -p collections_vcsa --force \
    && ln -sfn /opt/ncs-ansible/collections/ansible_collections/internal \
        collections_vcsa/ansible_collections/internal

# =============================================================================
# Stage 2: runtime — minimal layer with the two venvs, collections, and code
# =============================================================================
FROM ubuntu:${BASE_TAG} AS runtime

ARG UV_PYTHON_INSTALL_DIR
ENV DEBIAN_FRONTEND=noninteractive \
    UV_PYTHON_INSTALL_DIR=${UV_PYTHON_INSTALL_DIR} \
    NCS_REPO_ROOT=/opt/ncs-ansible \
    PATH=/opt/ncs-ansible/.venv/bin:/usr/local/bin:/usr/bin:/bin \
    ANSIBLE_FORCE_COLOR=1 \
    PYTHONUNBUFFERED=1

# Runtime apt deps only. just is in universe; sshpass for password-auth
# VCSA/Windows flows; libkrb5-3 for pykerberos at runtime; tini for clean
# PID 1 signal handling.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        python3 python3-venv \
        openssh-client sshpass rsync \
        libkrb5-3 libssl3 libffi8 \
        just tini \
    && rm -rf /var/lib/apt/lists/*

# Non-root runtime user first so COPY --chown below sets ownership inline
# instead of requiring a recursive chown over ~1.5 GB of venvs + collections.
RUN groupadd --system --gid 1000 ncs \
    && useradd  --system --uid 1000 --gid 1000 --home-dir /home/ncs \
                --shell /bin/bash --create-home ncs \
    && mkdir -p /ncs/inventory /ncs/configs /ncs/reports /ncs/ssh /srv/samba \
    && chown -R ncs:ncs /ncs /srv/samba /home/ncs

# uv-managed standalone Python(s) — .venv-vcsa's interpreter symlink points
# into this directory, so it must exist at the same path in the runtime stage.
COPY --from=builder --chown=ncs:ncs ${UV_PYTHON_INSTALL_DIR} ${UV_PYTHON_INSTALL_DIR}

# Orchestrator tree — venvs + collections + playbooks + ncs_configs + cfgs.
COPY --from=builder --chown=ncs:ncs /opt/ncs-ansible/ /opt/ncs-ansible/

# Sibling ncs_configs/ dirs — the reporter's config.yaml references these
# at `../../ncs-ansible-<name>/ncs_configs` relative to the orchestrator's
# ncs_configs/, so the paths must exist on disk in the image.
COPY --from=builder --chown=ncs:ncs /src/ncs-ansible-core/ncs_configs/    /opt/ncs-ansible-core/ncs_configs/
COPY --from=builder --chown=ncs:ncs /src/ncs-ansible-vmware/ncs_configs/  /opt/ncs-ansible-vmware/ncs_configs/
COPY --from=builder --chown=ncs:ncs /src/ncs-ansible-linux/ncs_configs/   /opt/ncs-ansible-linux/ncs_configs/
COPY --from=builder --chown=ncs:ncs /src/ncs-ansible-windows/ncs_configs/ /opt/ncs-ansible-windows/ncs_configs/
COPY --from=builder --chown=ncs:ncs /src/ncs-ansible-aci/ncs_configs/     /opt/ncs-ansible-aci/ncs_configs/

# Redirect the Justfile's hardcoded paths (`inventory/production/`,
# `.vaultpass`, `/srv/samba/reports`) at the /ncs bind mounts via symlinks.
# Symlink targets don't need to exist at creation time — the operator's
# bind mounts provide them at runtime.
RUN mkdir -p /opt/ncs-ansible/inventory \
    && cd /opt/ncs-ansible \
    && ln -sfn /ncs/inventory inventory/production \
    && ln -sfn /ncs/vaultpass .vaultpass \
    && ln -sfn /ncs/reports /srv/samba/reports \
    && ln -sfn /ncs/ssh /home/ncs/.ssh \
    && chown -h ncs:ncs inventory inventory/production .vaultpass \
                        /srv/samba/reports /home/ncs/.ssh

COPY --chown=ncs:ncs --chmod=0755 ncs-ansible/docker/entrypoint.sh /usr/local/bin/ncs-entrypoint
COPY --chown=ncs:ncs --chmod=0755 ncs-ansible/docker/smoke.sh      /usr/local/bin/ncs-smoke

ARG IMAGE_VERSION=dev
ARG IMAGE_REVISION=unknown
ARG IMAGE_SOURCE=https://github.com/ncs/codex
LABEL org.opencontainers.image.title="ncs-framework control-node" \
      org.opencontainers.image.description="Ansible control-node runtime bundling the five internal.* collections and ncs-reporter." \
      org.opencontainers.image.source="${IMAGE_SOURCE}" \
      org.opencontainers.image.revision="${IMAGE_REVISION}" \
      org.opencontainers.image.version="${IMAGE_VERSION}" \
      org.opencontainers.image.licenses="GPL-3.0-or-later"

USER ncs
WORKDIR /opt/ncs-ansible

ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/ncs-entrypoint"]
CMD ["--list"]
