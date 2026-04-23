# Container image — ncs-framework control node

The `ncs/control-node` image is a single runtime that bundles everything a
bare-metal `just setup-all` installs: the modern Ansible stack (`.venv/` with
`ansible-core>=2.16` + `ncs-reporter`), the VCSA-compatible stack (`.venv-vcsa/`
with `ansible-core 2.15` on Python 3.11), the five `internal.*` collections,
and the full set of orchestrator playbooks and `ncs_configs/` schemas.

The image carries **no customer state** — inventory, vault password, SSH keys,
and the report tree all come in as bind mounts at well-known paths.

## Build

Build context is the umbrella repo root so the builder can see both
`ncs-ansible/` and each `ncs-ansible-<name>/` sibling:

```bash
cd /path/to/codex
docker build -f Dockerfile -t ncs/control-node:dev \
    --build-arg IMAGE_REVISION=$(git rev-parse --short HEAD) \
    .
```

Or from `ncs-ansible/`:

```bash
cd ncs-ansible
just docker-build              # ncs/control-node:dev
just docker-build v2026.04.0   # ncs/control-node:v2026.04.0 + :latest
```

Expected image size: ~1.5–2.5 GB (two Python stacks, two Ansible installs).

### Post-build verification

```bash
cd ncs-ansible
just docker-smoke          # checks :dev
just docker-smoke v2026.04.0
```

`docker-smoke` runs `ansible --version` against both venvs, lists all five
`internal.*` collections plus `community.vmware`, verifies the reporter
CLI resolves, and exercises the entrypoint → `just --list` path. Exits
non-zero if any check fails.

## Runtime mount contract

| Container path  | Purpose                                             | Mode | Required |
|-----------------|-----------------------------------------------------|------|----------|
| `/ncs/inventory`| Inventory tree (group_vars, vaulted vault.yaml)     | ro   | yes      |
| `/ncs/vaultpass`| Ansible vault password file                         | ro   | yes      |
| `/ncs/reports`  | Report output tree                                  | rw   | yes      |
| `/ncs/ssh`      | SSH keys + known_hosts for managed nodes            | ro   | recommended |
| `/ncs/configs`  | Customer `ncs_configs/` override (extra dir)        | ro   | optional |

Trivial commands (`just --list`, `just --help`, `docker run --entrypoint …`)
skip the mount checks; any real recipe invocation requires the mandatory
mounts or the entrypoint exits with code 64.

### File ownership

The image runs as uid/gid **1000:1000** (`ncs` user). If your host uses a
different uid for the operator who owns the reports directory, pass
`--user "$(id -u):$(id -g)"` to `docker run` so the container writes reports
as the host user. The built-in `just docker-run` / `just docker-shell`
recipes do this automatically.

The vault password file must be readable by whatever uid the container
ends up running as. `chmod 0640` + group ownership matching the container
gid is usually the right answer.

## Run against real inventory

```bash
docker run --rm \
    -v "$(pwd)/inventory/production:/ncs/inventory:ro" \
    -v "$(pwd)/.vaultpass:/ncs/vaultpass:ro" \
    -v /srv/samba/reports:/ncs/reports \
    -v "$HOME/.ssh:/ncs/ssh:ro" \
    --user "$(id -u):$(id -g)" \
    ncs/control-node:dev \
    audit-linux
```

Everything after the image tag is forwarded to `just` inside the container,
so any existing recipe name works: `site`, `audit-vmware`, `stig-audit-esxi`,
`report`, `stig-audit-vcsa`, etc.

For a dev convenience wrapper that builds the above command from the
current checkout:

```bash
cd ncs-ansible
just docker-run audit-linux
just docker-run site
```

Set `NCS_REPORTS_DIR=/custom/path` to override `/srv/samba/reports` on
the host. Set `NCS_CONFIGS_OVERRIDE=/path/to/extra/configs` to mount
customer config overrides at `/ncs/configs`.

### Interactive shell

```bash
cd ncs-ansible
just docker-shell
# inside container:
#   .venv/bin/ansible-galaxy collection list
#   .venv-vcsa/bin/ansible --version
#   just --list
```

## Private registry

Push target comes from the `NCS_DOCKER_REGISTRY` env var. Put it in
`ncs-ansible/.env` (loaded by `set dotenv-load` at the top of the
Justfile) or pass it inline. Authenticate with `docker login` against
the same registry first.

```bash
# One-time setup
echo "NCS_DOCKER_REGISTRY=registry.example.com" >> ncs-ansible/.env
docker login registry.example.com

# Build + push a versioned tag
cd ncs-ansible
just docker-build v2026.04.0
just docker-push  v2026.04.0
```

`docker-push` also pushes `:latest` for any tag other than `dev`. Pull
from another host to verify:

```bash
docker pull registry.example.com/ncs/control-node:v2026.04.0
docker run --rm registry.example.com/ncs/control-node:v2026.04.0
```

## Versioning + labels

Each build stamps the image with OCI labels:

- `org.opencontainers.image.version` — build tag (default `dev`)
- `org.opencontainers.image.revision` — short git SHA from the build
- `org.opencontainers.image.source`   — repo URL (overridable build-arg)

Inspect with `docker inspect ncs/control-node:v2026.04.0 | jq '.[0].Config.Labels'`.

## What's NOT in the image

- `.vaultpass` — always a mount; never baked in.
- `inventory/production/` — always a mount; never baked in.
- Samba / SMB share — run on the host, not the container.
- `apt-get` at runtime — the image is stateless; install nothing inside it.
- `setup-*` Justfile recipes — they target a bare-metal host, not a container.

## Troubleshooting

**`missing bind mount: inventory -> /ncs/inventory`**
You forgot `-v <path>:/ncs/inventory:ro`. Pass `-e NCS_SKIP_MOUNT_CHECK=1`
to bypass (useful for `docker run … -- <ad-hoc command>`).

**`Permission denied` reading `/ncs/vaultpass`**
uid mismatch between host file and container user. Either `chmod 0644`
the host file, match the group with `chgrp` + `chmod 0640`, or pass
`--user "$(id -u):$(id -g)"`.

**`Permission denied` writing to `/ncs/reports`**
Same as above — the host directory needs to be writable by the container
uid. `just docker-run` / `just docker-shell` pass `--user` automatically.

**VCSA playbook can't find `community.vmware`**
Make sure the call picks up `ANSIBLE_CONFIG=ansible-vcsa.cfg` — the
bundled Justfile `stig-audit-vcsa` recipe does this already. Ad-hoc
invocations inside the container need to set it explicitly or use the
`just` recipe.
