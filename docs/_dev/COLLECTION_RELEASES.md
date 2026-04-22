# Releasing a Collection

Each `internal.<name>` collection lives as a tracked subdirectory at
`ncs-ansible-<name>/`. Cutting a release is a commit in this repo plus
a rebuild of the vendored tarball under
`ncs-ansible/collections/vendor/`. No separate remote, no submodules.

Prior reading: [`EXTRACTING_COLLECTIONS.md`](EXTRACTING_COLLECTIONS.md)
describes the one-time split that originally produced the sibling
repos; those have since been inlined (see the "inline built-in
collections" commit in `git log`).

## The release recipe

From `ncs-ansible/`:

```bash
just release-collection <name> <version> "<message>"
```

Example:

```bash
just release-collection vmware 1.2.0 "Add vCenter 8.0 STIG controls"
```

Inside `ncs-ansible-<name>/`:

1. Assert the version bump doesn't duplicate an existing
   `v<version>` tag in the umbrella repo.
2. Rewrite `galaxy.yml: version:` to the new version.
3. Prepend a dated entry to `CHANGELOG.md` using `<message>` as the
   first bullet.
4. `git add ncs-ansible-<name>/galaxy.yml ncs-ansible-<name>/CHANGELOG.md`
   and create a commit `Release internal.<name> v<version>: <message>`.
5. `git tag internal.<name>-v<version>` on that commit (collection-
   qualified tag name to avoid collisions between collections).
6. Call `just build-collection <name>` to produce
   `ncs-ansible/collections/vendor/internal-<name>-<version>.tar.gz`.

Release commits and tags land in the umbrella's history alongside
everything else. Push when you're ready — no per-collection push step.

## After release: update the orchestrator

```bash
# Option A — sibling-dir mode (Mode B in requirements.yml, the default):
# nothing to change in requirements.yml; just re-install.
just install-collections

# Option B — tarball mode (Mode A):
# bump the pinned filename in requirements.yml to match the new
# version, then re-install.
$EDITOR requirements.yml
just install-collections
```

Verify the new version is live:

```bash
.venv/bin/ansible-galaxy collection list | grep internal.<name>
```

## Pre-release checks

Run these before cutting a release; the release recipe does not run
them for you.

```bash
cd ncs-ansible-<name>
just lint                                 # ansible-lint on the collection
just yamllint                             # optional
cd ../ncs-ansible
just verify-fqcn-contract                 # every reporter-config FQCN still resolves
```

`verify-fqcn-contract` is the most important. It catches the case
where a release removes or renames a playbook that
`ncs_configs/ncs-reporter/*.yaml` pins as an FQCN string. The script
reads every `stig.ansible_playbook.path:` from those configs and
syntax-checks each one against the currently-installed collections.
Run it after `install-collections` in the orchestrator.

## Cross-collection coordination

When changes in `internal.core` break a platform collection's
`dependencies: { internal.core: ">=1.0.0,<2.0.0" }` range in each
platform's `galaxy.yml`, the order is:

1. Release `internal.core` first
   (`just release-collection core X.Y.Z …`).
2. In each affected platform's subdirectory, widen the
   `dependencies:` range in `galaxy.yml` to allow the new core
   version. Include that change in the follow-up release of the
   platform collection.
3. `just release-collection vmware X.Y.Z "Bump internal.core range"`.
4. Back in `ncs-ansible/`: `just install-collections`, then
   `just verify-fqcn-contract`.

The `galaxy.yml: dependencies:` range is enforced at install time, so
a mismatch fails fast with a clear error.

## Rolling back a release

Because releases are commits in this repo, rollback is just `git`:

```bash
git tag -d internal.<name>-v<version>
git reset --hard HEAD~1                  # if the release commit is HEAD
rm -f ncs-ansible/collections/vendor/internal-<name>-<version>.tar.gz
```

If the rollback commit has already been pushed, you'll need a
force-push (or, preferably, a forward-rolling "revert release" commit
that bumps the version again with the correction).

In the orchestrator: if the old version is still pinned in
`requirements.yml` (tarball mode), re-run `just install-collections`.
In sibling-dir mode there's no filename pin, so the install picks up
the rolled-back version automatically.

## Linting

`cd ncs-ansible-<name> && just lint` runs `ansible-lint` against the
collection. Each collection ships its own `.ansible-lint` (or imports
one from `shared.just` — see `ncs-ansible/shared.just`) to suppress
ansible-lint's `role-name` rule, which doesn't like the
`ncs-ansible-<name>` directory prefix. That suppression is a one-time
polish item per collection — don't re-add it on every release.

## Testing against a lab before release

Each collection ships a `tests/` harness for standalone lab testing:

```bash
cd ncs-ansible-<name>
# first time only:
cp -r tests/inventory.example tests/inventory
echo 'change-me' > tests/.vault_pass
# populate tests/inventory/ with real lab hosts; vault-encrypt secrets

just test        # --check dry-run against tests/inventory
just test-apply  # same playbook without --check
```

See [`docs/COLLECTION_LAYOUT.md`](../COLLECTION_LAYOUT.md) for the
full inventory + vault contract.
